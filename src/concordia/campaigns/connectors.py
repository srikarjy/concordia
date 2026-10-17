"""Provider adapters for campaign model jobs.

Adapters return only validated artifact references. The worker owns job state and
the campaign store owns scientific lineage.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import Protocol
from urllib.parse import urlparse

import httpx
from pydantic import BaseModel, ConfigDict, Field

from concordia.campaigns.artifacts import CampaignArtifactStore
from concordia.campaigns.training import (
    freeze_protein_dataset,
    train_protein_baseline,
)
from concordia.campaigns.worker import ConnectorResult, ModelExecutionContext
from concordia.genomics.boltz_gateway import BoltzGateway
from concordia.genomics.proteinmpnn_nvidia import (
    NvidiaHostedProteinMpnnRunner,
    ProteinMpnnRequest,
)
from concordia.genomics.rfdiffusion_nvidia import (
    NvidiaHostedRFdiffusionRunner,
    RFdiffusionRequest,
)
from concordia.stability.measured import MeasuredCandidate, MeasuredStabilityEngine
from concordia.stability.request import TypedStabilityRequest, candidates_for_request

BIONEMO_HTTP_CONTRACT_VERSION = "bionemo-http-v1"


class BioNeMoPreflightReport(BaseModel):
    """No-inference health contract for a private BioNeMo deployment."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    service: str
    endpoint: str
    contract_version: str
    status_code: int = Field(ge=100, le=599)
    ready: bool
    checked_at: datetime
    scientific_use_allowed: bool = False
    limitation: str = (
        "Health readiness proves only the HTTP deployment contract; it does not "
        "validate model weights, numerical outputs, or biological performance."
    )


def _validate_bionemo_endpoint(endpoint: str, api_key: str) -> str:
    parsed = urlparse(endpoint)
    if parsed.scheme not in {"https", "http"} or not parsed.netloc:
        raise ValueError("BioNeMo endpoint must be an absolute HTTP(S) URL")
    if parsed.scheme != "https" and parsed.hostname not in {"localhost", "127.0.0.1"}:
        raise ValueError("non-local BioNeMo endpoints must use HTTPS")
    if not api_key:
        raise ValueError("BioNeMo API key is required")
    return endpoint.rstrip("/")


def _preflight(
    endpoint: str,
    api_key: str,
    *,
    timeout_seconds: float,
    client: httpx.Client | None,
    expected_service: str,
) -> BioNeMoPreflightReport:
    own_client = client is None
    http_client = client or httpx.Client(timeout=timeout_seconds)
    status_code = 599
    contract_version = "unavailable"
    ready = False
    try:
        response = http_client.get(
            f"{endpoint}/healthz",
            headers={"Authorization": f"Bearer {api_key}", "Accept": "application/json"},
        )
        status_code = response.status_code
        try:
            body = response.json()
        except ValueError:
            body = {}
        if isinstance(body, dict):
            contract_version = str(body.get("contract_version", "unknown"))
            ready = (
                status_code == 200
                and body.get("service") == expected_service
                and body.get("contract_version") == BIONEMO_HTTP_CONTRACT_VERSION
                and body.get("status") == "ready"
            )
    except httpx.HTTPError:
        pass
    finally:
        if own_client:
            http_client.close()
    return BioNeMoPreflightReport(
        service=expected_service,
        endpoint=endpoint,
        contract_version=contract_version,
        status_code=status_code,
        ready=ready,
        checked_at=datetime.now(UTC),
    )


class BioNeMoTrainingRunner(Protocol):
    """Private-worker boundary for BioNeMo Framework training or fine-tuning."""

    def train(
        self,
        *,
        dataset_id: str,
        model: str,
        framework_version: str,
        parameters: dict[str, object],
    ) -> ConnectorResult: ...


class HttpBioNeMoTrainingRunner:
    """HTTP adapter for a privately deployed BioNeMo Framework worker."""

    def __init__(
        self,
        endpoint: str,
        api_key: str,
        *,
        timeout_seconds: float = 30,
        client: httpx.Client | None = None,
    ):
        self.endpoint = _validate_bionemo_endpoint(endpoint, api_key)
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        self.api_key = api_key
        self.timeout_seconds = timeout_seconds
        self.client = client

    def preflight(self) -> BioNeMoPreflightReport:
        """Check the authenticated deployment contract without running inference."""
        return _preflight(
            self.endpoint,
            self.api_key,
            timeout_seconds=self.timeout_seconds,
            client=self.client,
            expected_service="bionemo-framework",
        )

    def train(
        self,
        *,
        dataset_id: str,
        model: str,
        framework_version: str,
        parameters: dict[str, object],
    ) -> ConnectorResult:
        if not dataset_id or not model or not framework_version:
            raise ValueError("dataset_id, model, and framework_version are required")
        payload = {
            "dataset_id": dataset_id,
            "model": model,
            "framework_version": framework_version,
            "parameters": parameters,
        }
        own_client = self.client is None
        client = self.client or httpx.Client(timeout=self.timeout_seconds)
        try:
            response = client.post(
                f"{self.endpoint}/train",
                headers={"Authorization": f"Bearer {self.api_key}"},
                json=payload,
            )
            response.raise_for_status()
            body = response.json()
        except (httpx.HTTPError, ValueError) as error:
            raise RuntimeError("BioNeMo training request failed") from error
        finally:
            if own_client:
                client.close()
        provider_request_id = body.get("provider_request_id")
        output_artifact_digests = body.get("output_artifact_digests")
        if not isinstance(provider_request_id, str) or not provider_request_id:
            raise RuntimeError("BioNeMo response omitted provider_request_id")
        if not isinstance(output_artifact_digests, list) or not all(
            isinstance(digest, str) and digest for digest in output_artifact_digests
        ):
            raise RuntimeError("BioNeMo response omitted output artifact digests")
        return ConnectorResult(
            provider_request_id=provider_request_id,
            output_artifact_digests=tuple(output_artifact_digests),
        )


class UnconfiguredBioNeMoTrainingRunner:
    """Explicit fail-closed adapter when no private worker endpoint exists."""

    def train(
        self,
        *,
        dataset_id: str,
        model: str,
        framework_version: str,
        parameters: dict[str, object],
    ) -> ConnectorResult:
        raise RuntimeError(
            "BioNeMo training adapter present, no endpoint configured; "
            "set CONCORDIA_BIONEMO_TRAINING_URL and CONCORDIA_BIONEMO_API_KEY"
        )


class BioNeMoInferenceRunner(Protocol):
    """Private-worker boundary for BioNeMo inference or scoring."""

    def infer(
        self,
        *,
        model: str,
        sequences: tuple[str, ...],
        parameters: dict[str, object],
    ) -> ConnectorResult: ...


class HttpBioNeMoInferenceRunner:
    """HTTP adapter for a private BioNeMo inference worker."""

    def __init__(
        self,
        endpoint: str,
        api_key: str,
        *,
        timeout_seconds: float = 30,
        client: httpx.Client | None = None,
    ):
        self.endpoint = _validate_bionemo_endpoint(endpoint, api_key)
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        self.api_key = api_key
        self.timeout_seconds = timeout_seconds
        self.client = client

    def preflight(self) -> BioNeMoPreflightReport:
        """Check the authenticated deployment contract without running inference."""
        return _preflight(
            self.endpoint,
            self.api_key,
            timeout_seconds=self.timeout_seconds,
            client=self.client,
            expected_service="bionemo-inference",
        )

    def infer(
        self,
        *,
        model: str,
        sequences: tuple[str, ...],
        parameters: dict[str, object],
    ) -> ConnectorResult:
        if not model or not sequences or any(not sequence for sequence in sequences):
            raise ValueError("model and at least one sequence are required")
        payload = {"model": model, "sequences": list(sequences), "parameters": parameters}
        own_client = self.client is None
        client = self.client or httpx.Client(timeout=self.timeout_seconds)
        try:
            response = client.post(
                f"{self.endpoint}/infer",
                headers={"Authorization": f"Bearer {self.api_key}"},
                json=payload,
            )
            response.raise_for_status()
            body = response.json()
        except (httpx.HTTPError, ValueError) as error:
            raise RuntimeError("BioNeMo inference request failed") from error
        finally:
            if own_client:
                client.close()
        provider_request_id = body.get("provider_request_id")
        output_artifact_digests = body.get("output_artifact_digests")
        if not isinstance(provider_request_id, str) or not provider_request_id:
            raise RuntimeError("BioNeMo response omitted provider_request_id")
        if not isinstance(output_artifact_digests, list) or not all(
            isinstance(digest, str) and digest for digest in output_artifact_digests
        ):
            raise RuntimeError("BioNeMo response omitted output artifact digests")
        return ConnectorResult(
            provider_request_id=provider_request_id,
            output_artifact_digests=tuple(output_artifact_digests),
        )


class UnconfiguredBioNeMoInferenceRunner:
    """Explicit fail-closed adapter when no private worker endpoint exists."""

    def infer(
        self,
        *,
        model: str,
        sequences: tuple[str, ...],
        parameters: dict[str, object],
    ) -> ConnectorResult:
        raise RuntimeError(
            "BioNeMo inference adapter present, no endpoint configured; "
            "set CONCORDIA_BIONEMO_INFERENCE_URL and CONCORDIA_BIONEMO_API_KEY"
        )


class ProteinTrainingDatasetProvider(Protocol):
    def get_training_examples(self, dataset_id: str, *, metric: str | None = None): ...


class BoltzCampaignConnector:
    """Run the existing Boltz gateway for a single protein candidate.

    The hosted gateway currently exposes retained request and response artifact
    digests rather than a provider task ID. The recorded correlation ID is
    therefore explicitly derived from the response artifact, never presented as
    an NVIDIA request ID.
    """

    def __init__(self, gateway: BoltzGateway, *, client_id: str):
        self.gateway = gateway
        self.client_id = client_id

    def execute(self, context: ModelExecutionContext) -> ConnectorResult:
        if len(context.candidates) != 1:
            raise ValueError("the initial Boltz campaign connector accepts one candidate")
        result = self.gateway.predict(
            client_id=self.client_id,
            sequence=context.candidates[0].sequence,
        )
        response_hash = hashlib.sha256(result.response_artifact_digest.encode()).hexdigest()
        correlation_id = f"boltz-response:{response_hash}"
        return ConnectorResult(
            provider_request_id=correlation_id,
            output_artifact_digests=(
                result.request_artifact_digest,
                result.response_artifact_digest,
            ),
        )


class RFdiffusionCampaignConnector:
    """Adapt a campaign model run to RFdiffusion backbone generation."""

    def __init__(self, runner: NvidiaHostedRFdiffusionRunner):
        self.runner = runner

    def execute(self, context: ModelExecutionContext) -> ConnectorResult:
        parameters = context.model_run.parameters
        request = RFdiffusionRequest(
            target_pdb=str(parameters["target_pdb"]),
            contigs=str(parameters["contigs"]),
            hotspot_residues=tuple(parameters.get("hotspot_residues", ())),
            diffusion_steps=int(parameters.get("diffusion_steps", 50)),
            random_seed=(
                int(parameters["random_seed"])
                if parameters.get("random_seed") is not None
                else None
            ),
        )
        result = self.runner.generate(request)
        return ConnectorResult(
            provider_request_id=f"rfdiffusion-response:{result.response_artifact_digest}",
            output_artifact_digests=(
                result.request_artifact_digest,
                result.response_artifact_digest,
            ),
        )


class ProteinMPNNCampaignConnector:
    """Adapt a campaign model run to ProteinMPNN inverse folding."""

    def __init__(self, runner: NvidiaHostedProteinMpnnRunner):
        self.runner = runner

    def execute(self, context: ModelExecutionContext) -> ConnectorResult:
        parameters = context.model_run.parameters
        request = ProteinMpnnRequest(
            input_pdb=str(parameters["input_pdb"]),
            design_chains=tuple(parameters.get("design_chains", ())),
            num_sequences=int(parameters.get("num_sequences", 1)),
            sampling_temperature=float(parameters.get("sampling_temperature", 0.1)),
            ca_only=bool(parameters.get("ca_only", False)),
            use_soluble_model=bool(parameters.get("use_soluble_model", False)),
            random_seed=(
                int(parameters["random_seed"])
                if parameters.get("random_seed") is not None
                else None
            ),
        )
        result = self.runner.design(request)
        return ConnectorResult(
            provider_request_id=f"proteinmpnn-response:{result.response_artifact_digest}",
            output_artifact_digests=(
                result.request_artifact_digest,
                result.response_artifact_digest,
            ),
        )


class BioNeMoTrainingConnector:
    """Adapt a frozen campaign dataset to an approved BioNeMo training worker."""

    def __init__(self, runner: BioNeMoTrainingRunner):
        self.runner = runner

    def execute(self, context: ModelExecutionContext) -> ConnectorResult:
        parameters = context.model_run.parameters
        dataset_id = parameters.get("dataset_id")
        framework_version = parameters.get("framework_version")
        if not isinstance(dataset_id, str) or not dataset_id:
            raise ValueError("BioNeMo training requires a frozen dataset_id")
        if not isinstance(framework_version, str) or not framework_version:
            raise ValueError("BioNeMo training requires a framework_version")
        model = parameters.get("training_model", context.model_run.model)
        if not isinstance(model, str) or not model:
            raise ValueError("BioNeMo training requires a model name")
        return self.runner.train(
            dataset_id=dataset_id,
            model=model,
            framework_version=framework_version,
            parameters=dict(parameters),
        )


class BioNeMoInferenceConnector:
    """Run BioNeMo inference for campaign candidates through the worker."""

    def __init__(self, runner: BioNeMoInferenceRunner):
        self.runner = runner

    def execute(self, context: ModelExecutionContext) -> ConnectorResult:
        model = context.model_run.parameters.get("inference_model", context.model_run.model)
        if not isinstance(model, str) or not model:
            raise ValueError("BioNeMo inference requires a model name")
        sequences = tuple(candidate.sequence for candidate in context.candidates)
        if not sequences:
            raise ValueError("BioNeMo inference requires at least one candidate")
        return self.runner.infer(
            model=model,
            sequences=sequences,
            parameters=dict(context.model_run.parameters),
        )


class ProteinBaselineTrainingConnector:
    """Run the reproducible local protein baseline through a campaign job."""

    def __init__(
        self,
        dataset_provider: ProteinTrainingDatasetProvider,
        artifact_store: CampaignArtifactStore,
    ):
        self.dataset_provider = dataset_provider
        self.artifact_store = artifact_store

    def execute(self, context: ModelExecutionContext) -> ConnectorResult:
        parameters = context.model_run.parameters
        dataset_id = parameters.get("dataset_id")
        if not isinstance(dataset_id, str) or not dataset_id:
            raise ValueError("protein baseline training requires a frozen dataset_id")
        metric = parameters.get("metric")
        if metric is not None and not isinstance(metric, str):
            raise ValueError("training metric must be a string")
        examples = tuple(self.dataset_provider.get_training_examples(dataset_id, metric=metric))
        dataset = freeze_protein_dataset(
            dataset_id,
            examples,
            test_fraction=float(parameters.get("test_fraction", 0.2)),
            seed=int(parameters.get("seed", 0)),
        )
        result = train_protein_baseline(dataset, l2=float(parameters.get("l2", 1.0)))
        manifest = {
            "model_id": result.model_id,
            "dataset_id": result.dataset_id,
            "dataset_digest": result.dataset_digest,
            "coefficients": result.coefficients,
            "intercept": result.intercept,
            "metrics": result.metrics,
            "scientific_use_allowed": result.scientific_use_allowed,
        }
        artifact = self.artifact_store.put(
            json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode(),
            kind="checkpoint",
            media_type="application/json",
        )
        return ConnectorResult(
            provider_request_id=f"concordia-baseline:{artifact.digest}",
            output_artifact_digests=(artifact.digest,),
        )


class MeasuredStabilityConnector:
    """Run the frozen 1IGV measured-stability proposal cycle as a model job."""

    def __init__(self, artifact_store: CampaignArtifactStore):
        self.artifact_store = artifact_store

    def execute(self, context: ModelExecutionContext) -> ConnectorResult:
        engine = MeasuredStabilityEngine()
        typed_payload = context.model_run.parameters.get("typed_request")
        if typed_payload is not None:
            if not isinstance(typed_payload, dict):
                raise ValueError("typed_request model-run parameter must be an object")
            typed_request = TypedStabilityRequest.model_validate(typed_payload)
            candidates = candidates_for_request(engine, typed_request)
        else:
            candidates = []
            for candidate in context.candidates:
                variant_id = candidate.construct_metadata.get("variant_id", candidate.candidate_id)
                if not isinstance(variant_id, str):
                    raise ValueError("measured-stability candidates require a string variant_id")
                row = engine.rows.get(variant_id)
                if row is None:
                    raise ValueError(f"candidate is not in the frozen 1IGV table: {variant_id}")
                candidates.append(
                    MeasuredCandidate(row.variant_id, row.position, row.mutant, row.mutation_count)
                )
        report = engine.rank(candidates)
        payload = json.dumps(report, sort_keys=True, separators=(",", ":")).encode()
        artifact = self.artifact_store.put(payload, kind="report", media_type="application/json")
        return ConnectorResult(
            provider_request_id=f"concordia-measured-stability:{artifact.digest}",
            output_artifact_digests=(artifact.digest,),
        )


__all__ = [
    "BIONEMO_HTTP_CONTRACT_VERSION",
    "BioNeMoPreflightReport",
    "BioNeMoInferenceConnector",
    "BioNeMoInferenceRunner",
    "BioNeMoTrainingConnector",
    "BioNeMoTrainingRunner",
    "HttpBioNeMoInferenceRunner",
    "HttpBioNeMoTrainingRunner",
    "UnconfiguredBioNeMoInferenceRunner",
    "UnconfiguredBioNeMoTrainingRunner",
    "ProteinBaselineTrainingConnector",
    "MeasuredStabilityConnector",
    "ProteinTrainingDatasetProvider",
    "BoltzCampaignConnector",
    "ProteinMPNNCampaignConnector",
    "RFdiffusionCampaignConnector",
]
