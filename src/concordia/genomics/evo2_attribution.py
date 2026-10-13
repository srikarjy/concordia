"""Client adapter for the ZeroGPU Evo2 gradient-attribution worker.

Attribution is **not** a score and this module never lets it become one. The
worker runs one forward pass plus one backward pass over the frozen window and
returns, for every position, a first-order estimate of how each alternative
base would change the total log-likelihood. A first-order estimate is a local
linearization, so it is accurate only where the true effect is small — exactly
the opposite of the variants anyone cares about.

Measured on the real HBB window against exact rescoring
(``reports/evo2-backward-feasibility.json``): Spearman 0.50 over 24 pairs, and
the known c.-78A>G variant estimated at -1.7 against an exact -21.0, an
underestimate of roughly twelvefold. The site still ranked 84th of 8,192, so
the estimates order candidates usefully while badly misstating their size.

The only defensible use is therefore as a **ranking signal**: shortlist
positions here, then confirm each one with an exact forward rescore.
``Evo2AttributionResult`` is pinned to ``scientific_use_allowed=False`` so it
can never be mistaken for the forward score it approximates, and this adapter
returns a bounded ranked shortlist rather than the full tensor, which stays in
the content-addressed store under ``output_artifact_digest``.
"""

from __future__ import annotations

import math
import time
from typing import Any, Literal

import httpx
from pydantic import BaseModel, ConfigDict, Field

from concordia.genomics.evo2_protocol import Evo2ScoringSemantics
from concordia.genomics.evo2_zerogpu import (
    Evo2ForwardExecutionError,
    parse_gradio_call_event_id,
    parse_gradio_sse_result,
)
from concordia.genomics.schema import GenomicSequence
from concordia.storage.content import ContentAddressedStore

SHA256_PATTERN = r"^[0-9a-f]{64}$"

ATTRIBUTION_LIMITATIONS: tuple[str, ...] = (
    "First-order gradient estimates are a ranking signal, not a score; confirm "
    "any shortlisted position with an exact forward rescore before using it.",
    "Measured against exact rescoring on the real HBB window: Spearman 0.50 over "
    "24 pairs, sign agreement 0.625, top-quartile recall 0.5.",
    "Large effects are badly underestimated. The known HBB c.-78A>G variant was "
    "estimated at -1.7 against an exact -21.0, while still ranking 84th of 8,192.",
    "Executed on unverified worker code; see deploy/hf-evo2-worker/app.py for the "
    "current verification status.",
)


class Evo2AttributionError(Evo2ForwardExecutionError):
    """Raised for any worker-reported or transport failure during attribution."""


class RankedSubstitution(BaseModel):
    """One shortlisted position, ordered by its most damaging estimated change."""

    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)

    position: int = Field(ge=0)
    reference: str = Field(min_length=1, max_length=1)
    estimated_deltas: dict[str, float]
    worst_case_delta: float


class AttributionAgreementCheck(BaseModel):
    """The worker's own comparison of its estimates against exact rescoring."""

    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)

    pairs: int = Field(ge=1)
    spearman_predicted_vs_exact: float
    sign_agreement: float = Field(ge=0, le=1)
    top_quartile_recall: float = Field(ge=0, le=1)


class Evo2AttributionResult(BaseModel):
    """A ranking signal over one frozen window. Never scientific evidence."""

    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)

    schema_version: Literal[1] = 1
    model_id: str = Field(min_length=1)
    target: str = Field(min_length=1)
    attribution_method: Literal["gradient_x_embedding_difference_first_order"]
    sequence_hash: str = Field(pattern=SHA256_PATTERN)
    sequence_length: int = Field(ge=1)
    reference_total_log_likelihood: float
    ranked_substitutions: tuple[RankedSubstitution, ...]
    agreement_check: AttributionAgreementCheck
    backward_seconds: float = Field(ge=0)
    peak_memory_bytes: int = Field(ge=0)
    elapsed_seconds: float = Field(ge=0)
    input_artifact_digest: str = Field(pattern=SHA256_PATTERN)
    output_artifact_digest: str = Field(pattern=SHA256_PATTERN)
    scientific_use_allowed: Literal[False] = False
    limitations: tuple[str, ...] = Field(min_length=1)


class ZeroGpuEvo2AttributionRunner:
    """Calls a deployed ZeroGPU Space's ``attribute_sequence`` function."""

    api_name = "attribute_sequence"

    def __init__(
        self,
        artifacts: ContentAddressedStore,
        *,
        space_url: str,
        scoring: Evo2ScoringSemantics,
        shortlist_size: int = 50,
        check_pairs: int = 24,
        timeout_seconds: float = 600.0,
        transport: httpx.BaseTransport | None = None,
        hf_token: str | None = None,
    ):
        if shortlist_size < 1:
            raise ValueError("shortlist_size must be at least 1")
        self._auth = {"Authorization": f"Bearer {hf_token}"} if hf_token else {}
        self.artifacts = artifacts
        self.space_url = space_url.rstrip("/")
        self.scoring = scoring
        self.shortlist_size = shortlist_size
        self.check_pairs = check_pairs
        self.timeout_seconds = timeout_seconds
        self._transport = transport

    def preflight(self, sequence: GenomicSequence) -> None:
        """Reject an off-window sequence before any quota slot is spent."""

        if len(sequence.sequence) != self.scoring.expected_sequence_length:
            raise Evo2AttributionError(
                "sequence length does not match the frozen scoring window "
                f"({self.scoring.expected_sequence_length} bases required)"
            )

    def attribute(
        self, sequence: GenomicSequence, *, checkpoint: str, target: str
    ) -> Evo2AttributionResult:
        self.preflight(sequence)
        request_digest = self.artifacts.put_json(
            {
                "schema_version": 1,
                "space_url": self.space_url,
                "api_name": self.api_name,
                "input_sequence_hash": sequence.content_hash(),
                "input_sequence_length": len(sequence.sequence),
                "check_pairs": self.check_pairs,
                "input_retained": False,
                "scientific_use_allowed": False,
            }
        )
        started = time.monotonic()
        with httpx.Client(
            timeout=self.timeout_seconds, transport=self._transport, headers=self._auth
        ) as client:
            submit_response = client.post(
                f"{self.space_url}/gradio_api/call/{self.api_name}",
                json={"data": [sequence.sequence, self.check_pairs]},
            )
            if submit_response.is_error:
                raise Evo2AttributionError(
                    f"ZeroGPU worker submit failed: HTTP {submit_response.status_code}"
                )
            event_id = parse_gradio_call_event_id(submit_response)
            poll_response = client.get(
                f"{self.space_url}/gradio_api/call/{self.api_name}/{event_id}",
                headers={"Accept": "text/event-stream"},
            )
            if poll_response.is_error:
                raise Evo2AttributionError(
                    f"ZeroGPU worker poll failed: HTTP {poll_response.status_code}"
                )
        elapsed_seconds = time.monotonic() - started
        record = parse_gradio_sse_result(poll_response.text)
        if not isinstance(record, dict):
            raise Evo2AttributionError("ZeroGPU worker result was not a JSON object")
        response_digest = self.artifacts.put_json(record)
        return self._validate(
            record,
            sequence=sequence,
            checkpoint=checkpoint,
            target=target,
            elapsed_seconds=elapsed_seconds,
            request_digest=request_digest,
            response_digest=response_digest,
        )

    def _validate(
        self,
        record: dict[str, Any],
        *,
        sequence: GenomicSequence,
        checkpoint: str,
        target: str,
        elapsed_seconds: float,
        request_digest: str,
        response_digest: str,
    ) -> Evo2AttributionResult:
        """Fail closed on anything the worker did not fully establish."""

        if record.get("execution_status") != "COMPLETED":
            raise Evo2AttributionError(
                "ZeroGPU worker did not complete attribution: "
                f"{record.get('execution_status')} "
                f"({record.get('error', 'no error detail')})"
            )
        if record.get("model_checkpoint") != checkpoint:
            raise Evo2AttributionError(
                "ZeroGPU worker checkpoint identity does not match the declared adapter scope"
            )
        if record.get("target") != target:
            raise Evo2AttributionError(
                "ZeroGPU worker scoring target does not match the declared adapter scope"
            )
        if record.get("gradient_finite") is not True:
            raise Evo2AttributionError(
                "ZeroGPU worker did not confirm the gradient was finite; "
                "a non-finite gradient makes every estimate meaningless"
            )
        expected_length = self.scoring.expected_sequence_length
        if record.get("sequence_length") != expected_length:
            raise Evo2AttributionError(
                "ZeroGPU worker attributed a different window length than the frozen protocol"
            )

        reference_total = record.get("reference_total_log_likelihood")
        if not isinstance(reference_total, int | float) or not math.isfinite(reference_total):
            raise Evo2AttributionError("ZeroGPU worker reference log-likelihood was not finite")

        estimates = record.get("substitution_estimates")
        if not isinstance(estimates, dict) or set(estimates) != set("ACGT"):
            raise Evo2AttributionError(
                "ZeroGPU worker did not return an estimate series for each of A, C, G and T"
            )
        for base, values in estimates.items():
            if not isinstance(values, list) or len(values) != expected_length:
                raise Evo2AttributionError(
                    f"ZeroGPU worker estimate series for {base} did not cover the window"
                )

        check = record.get("agreement_check")
        if not isinstance(check, dict):
            raise Evo2AttributionError("ZeroGPU worker returned no agreement check")
        agreement = AttributionAgreementCheck(
            pairs=check["pairs"],
            spearman_predicted_vs_exact=check["spearman_predicted_vs_exact"],
            sign_agreement=check["sign_agreement"],
            top_quartile_recall=check["top_quartile_recall"],
        )

        return Evo2AttributionResult(
            model_id=checkpoint,
            target=target,
            attribution_method="gradient_x_embedding_difference_first_order",
            sequence_hash=sequence.content_hash(),
            sequence_length=expected_length,
            reference_total_log_likelihood=float(reference_total),
            ranked_substitutions=self._shortlist(sequence.sequence, estimates),
            agreement_check=agreement,
            backward_seconds=float(record.get("backward_seconds", 0.0)),
            peak_memory_bytes=int(record.get("peak_memory_bytes") or 0),
            elapsed_seconds=elapsed_seconds,
            input_artifact_digest=request_digest,
            output_artifact_digest=response_digest,
            limitations=ATTRIBUTION_LIMITATIONS,
        )

    def _shortlist(
        self, sequence: str, estimates: dict[str, list[float]]
    ) -> tuple[RankedSubstitution, ...]:
        """Rank positions by their most damaging estimated substitution.

        The reference base's own estimate is dropped rather than reported: it
        is a substitution to itself, so it carries no information and would
        otherwise dilute the ranking.
        """

        ranked: list[RankedSubstitution] = []
        for position, reference in enumerate(sequence):
            alternates = {
                base: float(values[position])
                for base, values in estimates.items()
                if base != reference
            }
            if not alternates or not all(math.isfinite(v) for v in alternates.values()):
                continue
            ranked.append(
                RankedSubstitution(
                    position=position,
                    reference=reference,
                    estimated_deltas=alternates,
                    worst_case_delta=min(alternates.values()),
                )
            )
        ranked.sort(key=lambda item: item.worst_case_delta)
        return tuple(ranked[: self.shortlist_size])
