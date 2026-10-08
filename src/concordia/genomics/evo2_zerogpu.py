"""Client adapter for the ZeroGPU Evo2 forward-scoring worker.

This is the trust boundary for Phase 2 interactivity: the worker
(``deploy/hf-evo2-worker/app.py``) is untrusted, unverified, external code
running on borrowed GPU hardware. It may fail, time out, or (until a real run
succeeds) may simply be wrong. This adapter never takes the worker's word for
scientific eligibility — it independently checks checkpoint identity, exact
window length, and scored-token count against the frozen
``Evo2ScoringSemantics`` contract before ever setting
``scientific_use_allowed=True``, and it fails closed on every ambiguous case.
"""

from __future__ import annotations

import json
import time
from typing import Any

import httpx

from concordia.genomics.evo2_protocol import Evo2ScoringSemantics
from concordia.genomics.schema import GenomicSequence
from concordia.storage.content import ContentAddressedStore


class Evo2ForwardExecutionError(RuntimeError):
    """Raised for any worker-reported or transport failure; never silently scored."""


def _parse_gradio_call_event_id(response: httpx.Response) -> str:
    try:
        payload = response.json()
    except json.JSONDecodeError as error:
        raise Evo2ForwardExecutionError(
            "ZeroGPU worker did not return a JSON event id"
        ) from error
    event_id = payload.get("event_id")
    if not isinstance(event_id, str) or not event_id:
        raise Evo2ForwardExecutionError("ZeroGPU worker response had no event_id")
    return event_id


def _parse_gradio_sse_result(body: str) -> Any:
    """Parse a Gradio ``/call/<name>/<event_id>`` SSE stream into its final payload.

    Gradio's queue API streams ``event: <kind>`` / ``data: <json>`` pairs and
    terminates with a ``complete`` event carrying the function's return value,
    or an ``error`` event. Heartbeats and intermediate events are ignored.
    """

    event_kind: str | None = None
    for line in body.splitlines():
        if line.startswith("event:"):
            event_kind = line.removeprefix("event:").strip()
        elif line.startswith("data:"):
            raw_data = line.removeprefix("data:").strip()
            if event_kind == "error":
                raise Evo2ForwardExecutionError(
                    f"ZeroGPU worker reported an error event: {raw_data[:500]}"
                )
            if event_kind == "complete":
                try:
                    parsed = json.loads(raw_data)
                except json.JSONDecodeError as error:
                    raise Evo2ForwardExecutionError(
                        "ZeroGPU worker completion payload was not JSON"
                    ) from error
                if not isinstance(parsed, list) or not parsed:
                    raise Evo2ForwardExecutionError(
                        "ZeroGPU worker completion payload had no result"
                    )
                return parsed[0]
    raise Evo2ForwardExecutionError(
        "ZeroGPU worker stream ended without a complete or error event"
    )


class ZeroGpuEvo2ForwardRunner:
    """Calls a deployed Gradio ZeroGPU Space's ``score_sequence`` function."""

    api_name = "score_sequence"

    def __init__(
        self,
        artifacts: ContentAddressedStore,
        *,
        space_url: str,
        scoring: Evo2ScoringSemantics,
        timeout_seconds: float = 330.0,
        poll_interval_seconds: float = 2.0,
        transport: httpx.BaseTransport | None = None,
    ):
        self.artifacts = artifacts
        self.space_url = space_url.rstrip("/")
        self.scoring = scoring
        self.timeout_seconds = timeout_seconds
        self.poll_interval_seconds = poll_interval_seconds
        self._transport = transport

    def score(
        self, sequence: GenomicSequence, *, checkpoint: str, target: str
    ) -> dict[str, Any]:
        if len(sequence.sequence) != self.scoring.expected_sequence_length:
            raise Evo2ForwardExecutionError(
                "sequence length does not match the frozen scoring window "
                f"({self.scoring.expected_sequence_length} bases required)"
            )
        request_payload = {"data": [sequence.sequence]}
        request_digest = self.artifacts.put_json(
            {
                "schema_version": 1,
                "space_url": self.space_url,
                "api_name": self.api_name,
                "input_sequence_hash": sequence.content_hash(),
                "input_sequence_length": len(sequence.sequence),
                "input_retained": False,
                "scientific_use_allowed": False,
            }
        )
        started = time.monotonic()
        with httpx.Client(timeout=self.timeout_seconds, transport=self._transport) as client:
            submit_response = client.post(
                f"{self.space_url}/call/{self.api_name}", json=request_payload
            )
            if submit_response.is_error:
                raise Evo2ForwardExecutionError(
                    f"ZeroGPU worker submit failed: HTTP {submit_response.status_code}"
                )
            event_id = _parse_gradio_call_event_id(submit_response)
            poll_response = client.get(
                f"{self.space_url}/call/{self.api_name}/{event_id}",
                headers={"Accept": "text/event-stream"},
            )
            if poll_response.is_error:
                raise Evo2ForwardExecutionError(
                    f"ZeroGPU worker poll failed: HTTP {poll_response.status_code}"
                )
        elapsed_seconds = time.monotonic() - started
        worker_record = _parse_gradio_sse_result(poll_response.text)
        if not isinstance(worker_record, dict):
            raise Evo2ForwardExecutionError("ZeroGPU worker result was not a JSON object")
        response_digest = self.artifacts.put_json(worker_record)

        if worker_record.get("execution_status") != "COMPLETED":
            raise Evo2ForwardExecutionError(
                "ZeroGPU worker did not complete the forward pass: "
                f"{worker_record.get('execution_status')} "
                f"({worker_record.get('error', 'no error detail')})"
            )
        if worker_record.get("model_checkpoint") != checkpoint:
            raise Evo2ForwardExecutionError(
                "ZeroGPU worker checkpoint identity does not match the declared adapter scope"
            )
        if worker_record.get("target") != target:
            raise Evo2ForwardExecutionError(
                "ZeroGPU worker scoring target does not match the declared adapter scope"
            )

        scored_token_count = worker_record.get("scored_token_count")
        in_scope = (
            worker_record.get("sequence_length") == self.scoring.expected_sequence_length
            and scored_token_count == self.scoring.expected_scored_token_count
            and isinstance(worker_record.get("mean_log_likelihood"), int | float)
        )

        return {
            "model_id": checkpoint,
            "execution_mode": "real" if in_scope else "out_of_scope",
            "sequence_hash": sequence.content_hash(),
            "score": float(worker_record.get("mean_log_likelihood", 0.0)),
            "target": target,
            "scientific_use_allowed": in_scope,
            "input_artifact_digest": request_digest,
            "output_artifact_digest": response_digest,
            "runtime_metadata": {
                "elapsed_seconds": elapsed_seconds,
                "scored_token_count": scored_token_count,
                "sum_log_likelihood": worker_record.get("sum_log_likelihood"),
                "space_url": self.space_url,
                "target_token_log_probabilities": worker_record.get(
                    "target_token_log_probabilities"
                ),
                "limitations": (
                    "Executed on unverified worker code; see "
                    "deploy/hf-evo2-worker/app.py for the current verification status.",
                ),
            },
        }
