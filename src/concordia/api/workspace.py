"""Read-only demonstration API and static scientific workspace host."""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import threading
import uuid
from collections.abc import Awaitable, Callable
from copy import deepcopy
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal, cast

from fastapi import BackgroundTasks, FastAPI, Header, HTTPException, Query, Request
from fastapi.responses import JSONResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field

from concordia.campaigns.artifacts import CampaignArtifactStore
from concordia.campaigns.assay import parse_assay_csv
from concordia.campaigns.benchmark import benchmark_digest, run_retrospective_benchmark
from concordia.campaigns.connectors import (
    BioNeMoInferenceConnector,
    BioNeMoInferenceRunner,
    BioNeMoTrainingConnector,
    BioNeMoTrainingRunner,
    BoltzCampaignConnector,
    HttpBioNeMoInferenceRunner,
    HttpBioNeMoTrainingRunner,
    MeasuredStabilityConnector,
    ProteinBaselineTrainingConnector,
    ProteinMPNNCampaignConnector,
    RFdiffusionCampaignConnector,
    UnconfiguredBioNeMoInferenceRunner,
    UnconfiguredBioNeMoTrainingRunner,
)
from concordia.campaigns.constraints import candidate_constraint_report
from concordia.campaigns.design import CampaignDesignRecord, build_binder_design_plan
from concordia.campaigns.postgres import PostgresCampaignStore
from concordia.campaigns.recommendations import SelectionCandidate, select_candidates
from concordia.campaigns.replay import replay_execute, replay_read
from concordia.campaigns.reporting import build_report_manifest, verify_report_manifest
from concordia.campaigns.schema import (
    Campaign,
    CampaignAuditEvent,
    CampaignModelJob,
    CampaignModelRun,
    CampaignRound,
    Candidate,
    DatasetSnapshot,
    EvidenceClaim,
    Measurement,
    Recommendation,
)
from concordia.campaigns.security import CampaignAction, CampaignPrincipal, require_action
from concordia.campaigns.service import (
    AddCandidateRequest,
    CampaignConflictError,
    CampaignNotFoundError,
    CampaignStore,
    CreateAccessGrantRequest,
    CreateAccessGrantResponse,
    CreateCampaignRequest,
    CreateCampaignResponse,
    CreateDesignPlanRequest,
    CreateEvidenceClaimRequest,
    CreateRoundRequest,
    CreateStudyRequest,
    EnqueueModelJobRequest,
    ImportAssayCSVRequest,
    RecordMeasurementRequest,
    RecordModelRunRequest,
    ReplayExecuteRequest,
    TransitionCampaignRequest,
    TransitionRoundRequest,
    VerifyEvidenceClaimRequest,
)
from concordia.campaigns.study import CampaignStudy
from concordia.campaigns.validation import (
    ALLOWED_EXTERNAL_PROVIDERS,
    ValidationCheck,
    ValidationReport,
    validate_campaign_round,
    validate_recommendation_replay,
)
from concordia.campaigns.worker import CampaignModelWorker, ModelConnector, ModelConnectorError
from concordia.colonies.live_run import run_live_colony
from concordia.experiments.schema import (
    CreateExperimentNodeRequest,
    CreateExperimentRequest,
    CreateExperimentResponse,
    DnaPayload,
    ExperimentComparison,
    ExperimentManifest,
    ExperimentNode,
    ExperimentNodeKind,
    ExperimentOperation,
    ModelRunPayload,
    StructurePayload,
)
from concordia.experiments.service import (
    ExperimentAccessError,
    ExperimentConflictError,
    ExperimentNodeNotFoundError,
    ExperimentNotFoundError,
    ExperimentStore,
)
from concordia.genomics.boltz_gateway import BoltzGateway
from concordia.genomics.boltz_nvidia import (
    BoltzComplexRequest,
    NvidiaHostedBoltzComplexResult,
    NvidiaHostedBoltzResult,
    NvidiaHostedBoltzRunner,
)
from concordia.genomics.evo2_attribution import ZeroGpuEvo2AttributionRunner
from concordia.genomics.evo2_forward_queue import Evo2ForwardJobQueue, JobNotFoundError
from concordia.genomics.evo2_generation_gateway import (
    Evo2GenerationGateway,
    RateLimitExceededError,
)
from concordia.genomics.evo2_nvidia import (
    NvidiaHostedEvo2GenerationRunner,
    NvidiaHostedGenerationResult,
)
from concordia.genomics.evo2_protocol import Evo2ScoringSemantics
from concordia.genomics.evo2_real import RealEvo2Scorer
from concordia.genomics.evo2_zerogpu import ZeroGpuEvo2ForwardRunner
from concordia.genomics.openfold2_nvidia import (
    NvidiaHostedOpenFold2Result,
    NvidiaHostedOpenFold2Runner,
)
from concordia.genomics.proteinmpnn_nvidia import NvidiaHostedProteinMpnnRunner
from concordia.genomics.rate_limiting import SqliteRateLimiter
from concordia.genomics.rfdiffusion_nvidia import NvidiaHostedRFdiffusionRunner
from concordia.genomics.schema import GenomicSequence
from concordia.genomics.structure_gateway import StructureGateway
from concordia.reporting.workspace import build_workspace
from concordia.runtime.model_registry import model_registry_report
from concordia.runtime.secrets import nvidia_api_key
from concordia.scientific.frameworks import framework_catalog
from concordia.verification.cross import StructureScope
from concordia.verification.structure_baseline import (
    StructureBaselineCase,
    run_structure_baseline,
)
from concordia.verification.structure_rules import (
    RULE_PACK_VERSION,
    StructureMeasurements,
    plausibility,
    verify_measurements,
)

HBB_CHECKPOINT = "arcinstitute/evo2_7b@bda0089f92582d5baabf0f22d9fc85f3588f6b58/evo2_7b.pt"
HBB_TARGET: Literal["mean_next_base_log_likelihood"] = "mean_next_base_log_likelihood"


def _client_ip(request: Request, *, trust_proxy_headers: bool) -> str:
    """Resolve the per-visitor identity used for rate limiting.

    Behind a reverse proxy (Hugging Face Spaces included), every request
    arrives from the proxy's own address, so ``request.client.host`` is the
    same value for every visitor and rate limiting would be meaningless.
    ``X-Forwarded-For`` is only trusted when the deployer explicitly opts in
    via ``CONCORDIA_TRUST_PROXY_HEADERS=1`` — trusting it unconditionally
    would let a direct, unproxied caller spoof any client identity simply by
    setting the header itself.
    """

    if trust_proxy_headers:
        forwarded = request.headers.get("x-forwarded-for")
        if forwarded:
            # Proxies append the address they saw, so the leftmost entries are
            # client-supplied and spoofable. Count back from the right by the
            # number of trusted proxy hops (default: one, e.g. the Spaces proxy).
            entries = [entry.strip() for entry in forwarded.split(",") if entry.strip()]
            hops = _trusted_proxy_hops()
            if len(entries) >= hops:
                return entries[-hops]
    return request.client.host if request.client else "unknown"


class StructureClaimVerifyRequest(BaseModel):
    """Measured signals for one predicted interface, plus the scope they were measured in."""

    model_config = ConfigDict(extra="forbid")

    complex_id: str = Field(min_length=1, max_length=120)
    receptor_chains: tuple[str, ...] = Field(min_length=1, max_length=12)
    ligand_chains: tuple[str, ...] = Field(min_length=1, max_length=12)
    model: str = Field(min_length=1, max_length=120)
    assay: str = Field(default="predicted_interface", min_length=1, max_length=80)
    # Free-form but bounded: whatever pins the run that produced the prediction.
    settings: dict[str, str | int | float | bool] = Field(default_factory=dict, max_length=32)
    measurements: StructureMeasurements
    # DockQ against an experimental structure. Must stay false when the verifier
    # itself is being evaluated, because the reference is then the label.
    include_reference: bool = False
    claim_text: str = Field(
        default="The predicted interface is correct.", min_length=1, max_length=500
    )


class StructureBaselineRequest(BaseModel):
    """Retrospective labelled cases for the geometry-only control."""

    model_config = ConfigDict(extra="forbid")

    cases: tuple[StructureBaselineCase, ...] = Field(min_length=2, max_length=500)


MAX_REQUEST_BODY_BYTES = 2_000_000

# Spaces embed the app in a huggingface.co iframe, so framing is limited to
# the app itself and Hugging Face rather than denied outright.
_CONTENT_SECURITY_POLICY = "; ".join(
    (
        "default-src 'self'",
        "script-src 'self' 'wasm-unsafe-eval'",
        "style-src 'self' 'unsafe-inline'",
        "img-src 'self' data: blob:",
        "font-src 'self' data:",
        "connect-src 'self'",
        "worker-src 'self' blob:",
        "object-src 'none'",
        "base-uri 'none'",
        "form-action 'self'",
        "frame-ancestors 'self' https://huggingface.co https://*.hf.space",
    )
)


def _trusted_proxy_hops() -> int:
    try:
        return max(1, int(os.environ.get("CONCORDIA_TRUSTED_PROXY_HOPS", "1")))
    except ValueError:
        return 1


def _hbb_scoring_semantics() -> Evo2ScoringSemantics:
    return Evo2ScoringSemantics(
        target=HBB_TARGET,
        tokenizer="CharLevelTokenizer-vocab-512",
        retained_score_artifacts=(
            "token_ids",
            "target_token_log_probabilities_float32",
            "sum_log_likelihood_float64",
            "mean_log_likelihood_float64",
        ),
    )


class _DictifyingForwardScorer:
    """Adapts RealEvo2Scorer's typed output to the plain-dict ForwardScorer protocol."""

    def __init__(self, scorer: RealEvo2Scorer) -> None:
        self._scorer = scorer

    def preflight(self, sequence: GenomicSequence) -> None:
        self._scorer.preflight(sequence)

    def score(
        self, sequence: GenomicSequence, *, checkpoint: str, target: str
    ) -> dict[str, object]:
        del checkpoint, target
        return self._scorer.score(sequence).model_dump(mode="json")


class _AttributionJob:
    """Runs gradient attribution through the forward queue's job machinery.

    The queue exists to serialize ZeroGPU work and record it; attribution needs
    both, and shares the same single allocation. It satisfies the queue's
    ``score`` contract without producing a score: the result it returns is
    pinned to ``scientific_use_allowed=False``.
    """

    def __init__(self, runner: ZeroGpuEvo2AttributionRunner) -> None:
        self._runner = runner

    def preflight(self, sequence: GenomicSequence) -> None:
        self._runner.preflight(sequence)

    def score(
        self, sequence: GenomicSequence, *, checkpoint: str, target: str
    ) -> dict[str, object]:
        result = self._runner.attribute(sequence, checkpoint=checkpoint, target=target)
        return result.model_dump(mode="json")


class Evo2GenerateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    sequence: str = Field(min_length=1, max_length=8_192)
    num_tokens: int = Field(default=8, ge=1, le=1_200)
    temperature: float = Field(default=0.7, ge=0, le=1.3)
    top_k: int = Field(default=3, ge=0, le=6)
    top_p: float = Field(default=0.0, ge=0, le=1)
    random_seed: int = Field(default=1729)


class Evo2ForwardRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    sequence: str = Field(min_length=8_192, max_length=8_192)


class Evo2AttributeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    sequence: str = Field(min_length=8_192, max_length=8_192)


class OpenFold2PredictRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    sequence: str = Field(min_length=1, max_length=1_000)


class BoltzPredictRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    sequence: str = Field(min_length=1, max_length=4_096)


class ColonyRunRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    population_size: int = Field(default=3, ge=1, le=6)
    generations: int = Field(default=2, ge=1, le=3)
    survivor_count: int = Field(default=1, ge=1, le=6)


class ExperimentEvo2GenerateRequest(Evo2GenerateRequest):
    parent_node_id: str = Field(min_length=1)
    branch: str = Field(default="evo2-generation", min_length=1, max_length=100)


class ExperimentEvo2GenerateResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    result: NvidiaHostedGenerationResult
    run_node: ExperimentNode
    output_node: ExperimentNode


class ExperimentBoltzPredictRequest(BoltzPredictRequest):
    parent_node_id: str = Field(min_length=1)
    branch: str = Field(default="boltz-structure", min_length=1, max_length=100)


class ExperimentBoltzPredictResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    result: NvidiaHostedBoltzResult
    run_node: ExperimentNode
    output_node: ExperimentNode


class RecommendationCandidateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    candidate_id: str = Field(min_length=1, max_length=200)
    score: float | None = None
    sequence: str = Field(default="", max_length=100_000)
    is_reference: bool = False
    measured: bool = False
    uncertainty: float | None = None
    constraint_violations: tuple[str, ...] = Field(default_factory=tuple, max_length=100)


class SelectRecommendationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    policy: str = Field(min_length=1, max_length=50)
    batch_size: int = Field(ge=1, le=100_000)
    seed: int = 0
    candidates: tuple[RecommendationCandidateRequest, ...] = Field(min_length=1, max_length=100_000)
    evidence_snapshot: tuple[str, ...] = Field(default_factory=tuple, max_length=100)
    rationale: dict[str, object] = Field(default_factory=dict)
    reference_candidate_id: str | None = None
    require_measured: bool = False
    max_uncertainty: float | None = Field(default=None, ge=0)


class ReplayRecommendationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    batch_size: int = Field(ge=1, le=100_000)
    seed: int = 0
    candidates: tuple[RecommendationCandidateRequest, ...] = Field(min_length=1, max_length=100_000)


def _selection_input_digest(candidates: tuple[RecommendationCandidateRequest, ...]) -> str:
    canonical = [
        {
            "candidate_id": candidate.candidate_id,
            "score": candidate.score,
            "sequence_hash": hashlib.sha256(candidate.sequence.encode("utf-8")).hexdigest(),
        }
        for candidate in candidates
    ]
    return hashlib.sha256(
        json.dumps(canonical, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


TOOL_PATHS = (
    "/api/workspace",
    "/api/artifacts",
    "/api/artifacts/{digest}",
    "/api/graph",
    "/api/events",
    "/api/report",
)


def _tool_manifest(persistence: str = "ephemeral_sqlite") -> dict[str, object]:
    return {
        "schema_version": 1,
        "name": "concordia-read-only-evidence-tools",
        "mode": "read_only_fixture",
        "openapi_url": "/api/tools/openapi.json",
        "privacy_policy_url": ("https://srikarjy025-concordia-colony.hf.space/privacy"),
        "operation_ids": [
            "inspect_saved_workspace",
            "list_saved_artifacts",
            "read_saved_artifact",
            "slice_saved_evidence_graph",
            "list_saved_run_events",
            "download_saved_report",
        ],
        "execution_exposed": False,
        "accepts_user_sequences": False,
        "model_inference_exposed": False,
        "scientific_use_allowed": False,
        "state_persistence": {
            "backend": persistence,
            "survives_restart": persistence == "postgres",
            "note": (
                "Rate-limit counters, the event ledger and cached model responses live "
                "in this backend. With ephemeral_sqlite, a restart resets per-client "
                "and global daily counters; set CONCORDIA_DATABASE_URL to a reachable "
                "Postgres instance for counters that persist."
            ),
        },
        "note": (
            "This manifest describes the curated GET-only tool contract above only. "
            "This deployment separately exposes five rate-limited, non-tool endpoints: "
            "POST /nvidia/evo2/generate (real hosted NVIDIA Evo2 generation, always "
            "scientific_use_allowed=false), POST /nvidia/evo2/forward (real Evo2 7B "
            "forward scoring on an unverified ZeroGPU worker; its output can be "
            "scientific_use_allowed=true only when the execution independently matches "
            "the frozen scoring protocol), POST /nvidia/boltz/predict (real hosted "
            "NVIDIA Boltz-2 protein structure prediction, always "
            "scientific_use_allowed=false; confirmed live), POST /nvidia/openfold2/predict "
            "(real hosted NVIDIA OpenFold2 monomer prediction, also never scientific "
            "evidence), and POST /colony/run (executes a real, fresh colony "
            "simulation with the deterministic fixture executor on every call; no user "
            "sequence accepted, always scientific_use_allowed=false since the evaluated "
            "task is a frozen software fixture). See /privacy."
        ),
        "verification_endpoint": {
            "path": "/v1/structure-claims/verify",
            "method": "POST",
            "spends_nothing": True,
            "stores_nothing": True,
            "accepts_user_sequences": False,
            "description": (
                "Applies the deterministic structure rule pack to measured interface "
                "signals and returns a status with its reasons. No language model "
                "judges anything. A claim needs independent evidence families and a "
                "passing counterfactual; agreement across samples of one model is "
                "deliberately too weak to carry a claim alone, so a lone prediction "
                "cannot verify itself."
            ),
        },
    }


def _reachable_database_url(database_url: str | None, *, required: bool = False) -> str | None:
    """Return a reachable Postgres URL, optionally failing closed instead of falling back.

    A wrong secret must degrade persistence, not take every write endpoint down.
    """
    if not database_url:
        return None
    try:
        import psycopg

        with psycopg.connect(database_url, connect_timeout=5):
            return database_url
    except Exception as error:  # noqa: BLE001 - any failure means fallback or fail-closed
        if required:
            logging.getLogger(__name__).error(
                "CONCORDIA_DATABASE_URL unusable (%s); refusing SQLite fallback",
                type(error).__name__,
            )
            raise RuntimeError(
                "CONCORDIA_REQUIRE_POSTGRES=1 but CONCORDIA_DATABASE_URL is unreachable"
            ) from error
        logging.getLogger(__name__).warning(
            "CONCORDIA_DATABASE_URL unusable (%s); using local SQLite state", type(error).__name__
        )
        return None


def _live_probe(
    url: str,
    *,
    headers: dict[str, str] | None = None,
    expect_json: Callable[[object], bool] | None = None,
) -> dict[str, object]:
    """Perform a bounded liveness request without returning response contents."""
    from datetime import datetime

    import httpx

    try:
        response = httpx.get(url, headers=headers, timeout=3.0)
        body: object = {}
        if expect_json is not None:
            try:
                body = response.json()
            except ValueError:
                body = {}
        reachable = 200 <= response.status_code < 400 and (
            expect_json(body) if expect_json is not None else True
        )
        return {
            "reachable": reachable,
            "reachable_at": datetime.now(UTC).isoformat() if reachable else None,
            "status_code": response.status_code,
        }
    except httpx.HTTPError:
        return {"reachable": False, "reachable_at": None, "status_code": None}


def _ollama_probe(url: str, model: str) -> dict[str, object]:
    return _live_probe(
        f"{url.rstrip('/')}/api/tags",
        expect_json=lambda body: (
            isinstance(body, dict)
            and isinstance(body.get("models"), list)
            and any(
                isinstance(item, dict) and item.get("name") == model
                for item in body["models"]
            )
        ),
    )


def _connector_state(
    *,
    configured: bool,
    probe: dict[str, object] | None = None,
    tested: bool = False,
    last_success: str | None = None,
) -> dict[str, object]:
    """Map connector observations to mutually exclusive operational states."""
    if not configured:
        status = "unconfigured"
    elif not tested:
        status = "untested"
    else:
        code = probe.get("status_code") if probe else None
        if code == 429:
            status = "rate_limited"
        elif bool(probe and probe.get("reachable")):
            status = "healthy"
        else:
            status = "unavailable"
    return {
        "state": status,
        "reachable_at": probe.get("reachable_at") if probe else None,
        "last_success": last_success,
    }


def create_workspace_app(
    state_root: str | Path = ".concordia/workspace",
    frontend: str | Path = "frontend/dist",
    *,
    bionemo_training_runner: BioNeMoTrainingRunner | None = None,
    bionemo_inference_runner: BioNeMoInferenceRunner | None = None,
) -> FastAPI:
    state_path = Path(state_root)
    secret_root = state_path.parent.parent if state_path.name == "workspace" else state_path
    local_nvidia_key = nvidia_api_key(secret_root)
    if local_nvidia_key and not os.environ.get("NVIDIA_API_KEY"):
        os.environ["NVIDIA_API_KEY"] = local_nvidia_key
    data = build_workspace(state_root)
    app = FastAPI(
        title="Concordia scientific workspace",
        description="Read-only access to a saved fixture-backed evidence workspace.",
        version="1.1.0",
    )
    from concordia.storage.content import ContentAddressedStore

    trust_proxy_headers = os.environ.get("CONCORDIA_TRUST_PROXY_HEADERS") == "1"

    # A Hugging Face Space's local filesystem is ephemeral: every SQLite file
    # below is wiped on redeploy/restart. Setting CONCORDIA_DATABASE_URL (a
    # Postgres/Supabase connection string) swaps every one of these for a
    # Postgres-backed equivalent instead; see genomics/postgres_backend.py
    # and docs/deployment.md. Local development is unaffected either way.
    database_url = _reachable_database_url(
        os.environ.get("CONCORDIA_DATABASE_URL"),
        required=os.environ.get("CONCORDIA_REQUIRE_POSTGRES") == "1",
    )
    experiment_store = ExperimentStore(Path(state_root) / "experiments")
    campaign_store = (
        PostgresCampaignStore(database_url)
        if database_url
        else CampaignStore(Path(state_root) / "campaigns")
    )
    campaign_artifact_store = CampaignArtifactStore(
        ContentAddressedStore(Path(state_root) / "artifacts")
    )

    generation_gateway = Evo2GenerationGateway(
        NvidiaHostedEvo2GenerationRunner(ContentAddressedStore(Path(state_root) / "artifacts")),
        database_path=None if database_url else Path(state_root) / "evo2_generation.sqlite3",
        postgres_dsn=database_url,
    )

    openfold2_gateway = StructureGateway(
        NvidiaHostedOpenFold2Runner(ContentAddressedStore(Path(state_root) / "artifacts")),
        namespace="openfold2",
        result_model=NvidiaHostedOpenFold2Result,
        database_path=None if database_url else Path(state_root) / "openfold2.sqlite3",
        postgres_dsn=database_url,
    )

    boltz_gateway = BoltzGateway(
        NvidiaHostedBoltzRunner(ContentAddressedStore(Path(state_root) / "artifacts")),
        database_path=None if database_url else Path(state_root) / "boltz.sqlite3",
        postgres_dsn=database_url,
    )
    campaign_connectors: dict[str, ModelConnector] = {
        "nvidia-boltz": BoltzCampaignConnector(boltz_gateway, client_id="campaign-api"),
        "nvidia-rfdiffusion": RFdiffusionCampaignConnector(
            NvidiaHostedRFdiffusionRunner(ContentAddressedStore(Path(state_root) / "artifacts"))
        ),
        "nvidia-proteinmpnn": ProteinMPNNCampaignConnector(
            NvidiaHostedProteinMpnnRunner(ContentAddressedStore(Path(state_root) / "artifacts"))
        ),
        "concordia-protein-baseline": ProteinBaselineTrainingConnector(
            campaign_store,
            campaign_artifact_store,
        ),
        "concordia-measured-stability": MeasuredStabilityConnector(campaign_artifact_store),
    }
    if bionemo_training_runner is None:
        bionemo_endpoint = os.environ.get("CONCORDIA_BIONEMO_TRAINING_URL")
        bionemo_api_key = os.environ.get("CONCORDIA_BIONEMO_API_KEY")
        if bionemo_endpoint and bionemo_api_key:
            try:
                bionemo_training_runner = HttpBioNeMoTrainingRunner(
                    bionemo_endpoint, bionemo_api_key
                )
            except ValueError as error:
                logging.getLogger(__name__).warning(
                    "BioNeMo runner configuration rejected (%s)", type(error).__name__
                )
    if bionemo_training_runner is None:
        bionemo_training_runner = UnconfiguredBioNeMoTrainingRunner()
    campaign_connectors["nvidia-bionemo-framework"] = BioNeMoTrainingConnector(
        bionemo_training_runner
    )
    if bionemo_inference_runner is None:
        bionemo_inference_endpoint = os.environ.get("CONCORDIA_BIONEMO_INFERENCE_URL")
        bionemo_inference_api_key = os.environ.get("CONCORDIA_BIONEMO_API_KEY")
        if bionemo_inference_endpoint and bionemo_inference_api_key:
            try:
                bionemo_inference_runner = HttpBioNeMoInferenceRunner(
                    bionemo_inference_endpoint, bionemo_inference_api_key
                )
            except ValueError as error:
                logging.getLogger(__name__).warning(
                    "BioNeMo inference configuration rejected (%s)", type(error).__name__
                )
    if bionemo_inference_runner is None:
        bionemo_inference_runner = UnconfiguredBioNeMoInferenceRunner()
    campaign_connectors["nvidia-bionemo-inference"] = BioNeMoInferenceConnector(
        bionemo_inference_runner
    )
    campaign_worker = CampaignModelWorker(
        cast(CampaignStore, campaign_store),
        campaign_connectors,
        owner="campaign-api-worker",
    )

    if database_url:
        from concordia.genomics.postgres_backend import PostgresRateLimiter

        colony_run_limiter: SqliteRateLimiter | PostgresRateLimiter = PostgresRateLimiter(
            dsn=database_url,
            namespace="colony_run",
            per_client_limit=5,
            per_client_window_seconds=60,
            global_daily_limit=500,
        )
    else:
        colony_run_limiter = SqliteRateLimiter(
            database_path=Path(state_root) / "colony_runs.sqlite3",
            table_name="colony_run_requests",
            per_client_limit=5,
            per_client_window_seconds=60,
            global_daily_limit=500,
        )

    if database_url:
        experiment_create_limiter: SqliteRateLimiter | PostgresRateLimiter = PostgresRateLimiter(
            dsn=database_url,
            namespace="experiment_create",
            per_client_limit=10,
            per_client_window_seconds=3_600,
            global_daily_limit=500,
        )
    else:
        experiment_create_limiter = SqliteRateLimiter(
            database_path=Path(state_root) / "experiment_creates.sqlite3",
            table_name="experiment_create_requests",
            per_client_limit=10,
            per_client_window_seconds=3_600,
            global_daily_limit=500,
        )

    forward_space_url = os.environ.get("CONCORDIA_EVO2_FORWARD_SPACE_URL")
    forward_queue: Evo2ForwardJobQueue | None = None
    attribution_queue: Evo2ForwardJobQueue | None = None
    if forward_space_url:
        forward_hf_token = os.environ.get("CONCORDIA_EVO2_FORWARD_HF_TOKEN")
        forward_artifacts = ContentAddressedStore(Path(state_root) / "artifacts")
        forward_job_database = (
            None if database_url else Path(state_root) / "evo2_forward_jobs.sqlite3"
        )
        # One ZeroGPU allocation serves both operations, so they share the
        # single-flight lock and - because they record into the same job table -
        # one combined per-client budget of scarce GPU jobs.
        zerogpu_lock = threading.Lock()
        forward_runner = ZeroGpuEvo2ForwardRunner(
            forward_artifacts,
            space_url=forward_space_url,
            scoring=_hbb_scoring_semantics(),
            hf_token=forward_hf_token,
        )
        forward_queue = Evo2ForwardJobQueue(
            _DictifyingForwardScorer(
                RealEvo2Scorer(forward_runner, checkpoint=HBB_CHECKPOINT, target=HBB_TARGET)
            ),
            database_path=forward_job_database,
            postgres_dsn=database_url,
            checkpoint=HBB_CHECKPOINT,
            target=HBB_TARGET,
            execution_lock=zerogpu_lock,
        )
        attribution_queue = Evo2ForwardJobQueue(
            _AttributionJob(
                ZeroGpuEvo2AttributionRunner(
                    forward_artifacts,
                    space_url=forward_space_url,
                    scoring=_hbb_scoring_semantics(),
                    hf_token=forward_hf_token,
                )
            ),
            database_path=forward_job_database,
            postgres_dsn=database_url,
            checkpoint=HBB_CHECKPOINT,
            target=HBB_TARGET,
            execution_lock=zerogpu_lock,
        )

    @app.exception_handler(RateLimitExceededError)
    async def rate_limit_exceeded(request: Request, error: RateLimitExceededError) -> Response:
        response = JSONResponse(
            status_code=429,
            content={"code": "RATE_LIMIT_EXCEEDED", "message": str(error)},
        )
        response.headers["Retry-After"] = str(error.retry_after_seconds)
        return response

    @app.middleware("http")
    async def bounded_request_body(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        # Pydantic bounds fields only after the whole body is read, so the body is
        # bounded first. Registered before the security-headers middleware so that
        # these rejections still carry the security headers.
        if request.method in {"POST", "PUT", "PATCH"}:
            length = request.headers.get("content-length")
            if length is None or not length.isdigit():
                return JSONResponse(status_code=411, content={"detail": "Content-Length required"})
            if int(length) > MAX_REQUEST_BODY_BYTES:
                return JSONResponse(status_code=413, content={"detail": "request body too large"})
        return await call_next(request)

    @app.middleware("http")
    async def public_security_headers(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        # The interactive API docs load third-party assets, so they keep their
        # own policy; everything else, including the app shell, is locked down.
        if not request.url.path.startswith(("/docs", "/redoc")):
            response.headers["Content-Security-Policy"] = _CONTENT_SECURITY_POLICY
        if request.headers.get("x-forwarded-proto") == "https" or request.url.scheme == "https":
            response.headers["Strict-Transport-Security"] = "max-age=31536000"
        return response

    @app.get("/api/capabilities")
    def capabilities() -> dict[str, object]:
        """Report configuration only; never expose credentials or claim live health."""
        nvidia_configured = nvidia_api_key(secret_root) is not None
        return {
            "nvidia": nvidia_configured,
            "forward": forward_queue is not None,
            "attribution": attribution_queue is not None,
        }

    @app.get("/api/models")
    def models() -> dict[str, object]:
        """Expose pinned model identities and loading policy, never model bytes."""
        return model_registry_report()

    @app.get("/api/connectors/health")
    def connector_health() -> dict[str, object]:
        """Expose configured, live reachability, and last-call state separately."""
        nvidia_key = nvidia_api_key(secret_root)
        nvidia_configured = nvidia_key is not None
        nvidia_probe = (
            _live_probe(
                "https://health.api.nvidia.com",
                headers={"Authorization": f"Bearer {nvidia_key}"},
            )
            if nvidia_key
            else {"reachable": False, "reachable_at": None}
        )
        ollama_url = os.environ.get("OLLAMA_HOST", "http://127.0.0.1:11434")
        ollama_configured = bool(os.environ.get("OLLAMA_HOST", "").strip())
        ollama_probe = (
            _ollama_probe(ollama_url, os.environ.get("OLLAMA_MODEL", "qwen3:1.7b"))
            if ollama_configured
            else {"reachable": False, "reachable_at": None}
        )
        training_endpoint = os.environ.get("CONCORDIA_BIONEMO_TRAINING_URL", "").strip()
        inference_endpoint = os.environ.get("CONCORDIA_BIONEMO_INFERENCE_URL", "").strip()
        bionemo_key = os.environ.get("CONCORDIA_BIONEMO_API_KEY", "").strip()
        bionemo_headers = {"Authorization": f"Bearer {bionemo_key}"} if bionemo_key else None
        training_probe = (
            _live_probe(f"{training_endpoint}/healthz", headers=bionemo_headers)
            if training_endpoint and bionemo_key
            else {"reachable": False, "reachable_at": None}
        )
        inference_probe = (
            _live_probe(f"{inference_endpoint}/healthz", headers=bionemo_headers)
            if inference_endpoint and bionemo_key
            else {"reachable": False, "reachable_at": None}
        )

        return {
            "connectors": {
                "nvidia_hosted": {
                    "configured": nvidia_configured,
                    **_connector_state(
                        configured=nvidia_configured,
                        probe=nvidia_probe,
                        tested=nvidia_configured,
                    ),
                },
                "evo2_generate": {
                    "configured": nvidia_configured,
                    **_connector_state(
                        configured=nvidia_configured,
                        probe=nvidia_probe,
                        tested=nvidia_configured,
                    ),
                },
                "evo2_forward": {
                    "configured": forward_queue is not None,
                    **_connector_state(
                        configured=forward_queue is not None,
                        tested=False,
                    ),
                },
                "evo2_attribute": {
                    "configured": attribution_queue is not None,
                    **_connector_state(
                        configured=attribution_queue is not None,
                        tested=False,
                    ),
                },
                "openfold2": {
                    "configured": nvidia_configured,
                    **_connector_state(
                        configured=nvidia_configured,
                        probe=nvidia_probe,
                        tested=nvidia_configured,
                    ),
                },
                "boltz": {
                    "configured": nvidia_configured,
                    **_connector_state(
                        configured=nvidia_configured,
                        probe=nvidia_probe,
                        tested=nvidia_configured,
                    ),
                },
                "boltz_complex": {
                    "configured": nvidia_configured,
                    **_connector_state(
                        configured=nvidia_configured,
                        probe=nvidia_probe,
                        tested=nvidia_configured,
                    ),
                },
                "proteinmpnn": {
                    "configured": nvidia_configured,
                    **_connector_state(
                        configured=nvidia_configured,
                        probe=nvidia_probe,
                        tested=nvidia_configured,
                    ),
                },
                "rfdiffusion": {
                    "configured": nvidia_configured,
                    **_connector_state(
                        configured=nvidia_configured,
                        probe=nvidia_probe,
                        tested=nvidia_configured,
                    ),
                },
                "ollama_local": {
                    "configured": ollama_configured,
                    **_connector_state(
                        configured=ollama_configured,
                        probe=ollama_probe,
                        tested=ollama_configured,
                    ),
                    "cloud_disabled": os.environ.get("OLLAMA_NO_CLOUD", "") == "1",
                },
                "bionemo_training": {
                    "configured": bool(training_endpoint and bionemo_key),
                    **_connector_state(
                        configured=bool(training_endpoint and bionemo_key),
                        probe=training_probe,
                        tested=bool(training_endpoint and bionemo_key),
                    ),
                },
                "bionemo_inference": {
                    "configured": bool(inference_endpoint and bionemo_key),
                    **_connector_state(
                        configured=bool(inference_endpoint and bionemo_key),
                        probe=inference_probe,
                        tested=bool(inference_endpoint and bionemo_key),
                    ),
                },
                "biorender": {
                    "configured": False,
                    **_connector_state(configured=False),
                },
            },
            "scientific_use_allowed": False,
        }

    @app.get("/health")
    def health():
        return {"status": "ok", "mode": "read_only_fixture", "schema_version": 1}

    @app.get("/ready")
    def ready():
        return {"status": "ready", "snapshot_digest": data["snapshot_digest"]}

    @app.get("/privacy", include_in_schema=False)
    def privacy():
        return Response(
            "\n".join(
                [
                    "# Concordia public workspace privacy notice",
                    "",
                    "This demonstration does not provide accounts, set application cookies, "
                    "or request API credentials from visitors.",
                    "",
                    "Most of the service is read-only: it inspects a saved fixture-backed "
                    "evidence workspace and never runs a model.",
                    "",
                    "One endpoint, POST /nvidia/evo2/generate, is interactive. It accepts a "
                    "DNA sequence you supply, forwards it to NVIDIA's hosted Evo2 generation "
                    "API using this deployment's own server-side credential, and returns the "
                    "real response. The submitted sequence and the generated output are sent "
                    "to NVIDIA for processing. Requests are rate-limited per client and "
                    "cached by content hash; identical requests are not re-sent. Generation "
                    "output always has scientific_use_allowed=false: it is a real API call, "
                    "not an Evo2 forward score or a biological finding.",
                    "",
                    "A second pair of endpoints, POST /nvidia/evo2/forward and "
                    "GET /nvidia/evo2/forward/{job_id}, is interactive and experimental. "
                    "It accepts an exact 8,192-base sequence you supply, queues one real "
                    "Evo2 7B forward pass on a separate ZeroGPU worker this deployment "
                    "operates, and returns the result when you poll for it. At most one "
                    "such job runs at a time across all visitors. This worker has not yet "
                    "completed a successful run; early requests may fail while it is being "
                    "brought up. Its output is only ever treated as scientific evidence when "
                    "the execution independently matches the frozen scoring protocol "
                    "(exact checkpoint, exact window length, exact scored-token count); "
                    "otherwise it is returned labeled scientific_use_allowed=false like "
                    "every other result from this service.",
                    "",
                    "A third endpoint, POST /nvidia/boltz/predict, accepts an amino acid "
                    "sequence you supply, forwards it to NVIDIA's hosted Boltz-2 protein "
                    "structure prediction API using this deployment's own credential "
                    "(including NVIDIA's own asynchronous long-polling protocol when a job "
                    "is queued), and returns the real predicted structure. Confirmed live "
                    "against a real account as of 2026-10-02. The multiple-sequence "
                    "alignment sent is a one-sequence self-reference, not a real alignment, "
                    "which reduces accuracy. Requests are rate-limited per client and cached "
                    "by sequence. Output always has scientific_use_allowed=false: a "
                    "predicted structure is not validated and its confidence has not been "
                    "inspected.",
                    "",
                    "A fourth endpoint, POST /nvidia/openfold2/predict, returns a real "
                    "AlphaFold2-class monomer structure from NVIDIA's hosted OpenFold2 NIM "
                    "(up to 1,000 residues, no MSA or templates). Output is never scientific "
                    "evidence.",
                    "",
                    "A fifth endpoint, POST /colony/run, does not accept a sequence at all. "
                    "It executes a real, fresh colony simulation (new digital genomes, "
                    "mutations, fitness evaluation, and survivor selection) using the "
                    "deterministic software-fixture executor, no NVIDIA call involved. "
                    "Requests are rate-limited per client.",
                    "",
                    "The experiment sandbox endpoints intentionally persist molecular objects, "
                    "model-run metadata, lineage edges, candidate selections, and evidence "
                    "references so an experiment can be replayed. Each experiment receives a "
                    "random access token that is returned once and must be supplied through "
                    "X-Concordia-Experiment-Token. This is capability-based access for a "
                    "sandbox demonstration, not an account system or a substitute for a "
                    "multi-user authorization service.",
                    "",
                    "Request provenance does not retain the raw submitted DNA or protein "
                    "sequence. It stores a SHA-256 sequence digest, sequence length, "
                    "non-sequence inference parameters, rate-limit records, cached model "
                    "outputs, raw provider responses, and forward-job status for provenance "
                    "and quota enforcement. Provider responses and derived outputs, including "
                    "protein structures, can reflect biological information from the submitted "
                    "sequence. Its hosting provider "
                    "may process standard connection and access-log metadata under the "
                    "provider's own privacy terms.",
                    "",
                    "All scientific content returned by this service is a public, "
                    "fixture-labeled software demonstration and is not a medical or biological "
                    "finding.",
                    "",
                    "Questions or corrections may be filed at "
                    "https://github.com/srikarjy/concordia/issues.",
                ]
            ),
            media_type="text/markdown",
        )

    @app.get(
        "/api/workspace",
        operation_id="inspect_saved_workspace",
        summary="Inspect the saved scientific workspace",
        description=(
            "Returns persisted fixture-backed claims, lineage, evidence, and study readiness. "
            "It does not run a model."
        ),
    )
    def workspace():
        return {key: value for key, value in data.items() if key != "artifacts"}

    @app.get(
        "/api/artifacts",
        operation_id="list_saved_artifacts",
        summary="List immutable saved artifacts",
    )
    def artifacts():
        return [
            {"digest": digest, "media_type": "application/json", "schema_version": 1}
            for digest in data["artifacts"]
        ]

    @app.get(
        "/api/artifacts/{digest}",
        operation_id="read_saved_artifact",
        summary="Read one immutable saved artifact",
        description=(
            "The digest must belong to the saved demonstration and its bytes must pass "
            "SHA-256 verification."
        ),
    )
    def artifact(digest: str):
        if digest not in data["artifacts"]:
            raise HTTPException(404, "artifact is not part of this demonstration")
        from concordia.storage.content import ContentAddressedStore

        store = ContentAddressedStore(Path(state_root) / "artifacts")
        try:
            payload = store.get_bytes(digest)
        except (ValueError, OSError) as error:
            raise HTTPException(409, "artifact integrity check failed") from error
        return Response(
            payload, media_type="application/json" if payload.startswith(b"{") else "text/plain"
        )

    @app.get(
        "/api/graph",
        operation_id="slice_saved_evidence_graph",
        summary="Slice the saved evidence graph",
    )
    def graph(focus: str | None = None, depth: int = Query(default=2, ge=0, le=5)):
        graph_data = data["graph"]
        if focus is None:
            return graph_data
        if focus not in {node["id"] for node in graph_data["nodes"]}:
            raise HTTPException(404, "graph node not found")
        selected = {focus}
        for _ in range(depth):
            selected.update(
                edge["target"] for edge in graph_data["edges"] if edge["source"] in selected.copy()
            )
        return {
            "schema_version": 1,
            "nodes": [node for node in graph_data["nodes"] if node["id"] in selected],
            "edges": [
                edge
                for edge in graph_data["edges"]
                if edge["source"] in selected and edge["target"] in selected
            ],
        }

    @app.get(
        "/api/events",
        operation_id="list_saved_run_events",
        summary="List saved run events",
    )
    def events(cursor: int = Query(default=0, ge=0), limit: int = Query(default=100, ge=1, le=500)):
        rows = data["events"][cursor : cursor + limit]
        next_cursor = cursor + len(rows)
        return {
            "items": rows,
            "next_cursor": next_cursor if next_cursor < len(data["events"]) else None,
        }

    @app.get("/api/stream")
    async def stream(last_event_id: str | None = Header(default=None)):
        try:
            cursor = int(last_event_id or "0")
            if cursor < 0:
                raise ValueError
        except ValueError as error:
            raise HTTPException(400, "Last-Event-ID must be a nonnegative integer") from error

        async def source():
            yield ": saved demonstration replay\n\n"
            for event in data["events"][cursor:]:
                yield f"id: {event['sequence_number']}\ndata: {json.dumps(event)}\n\n"
                await asyncio.sleep(0)
            yield "event: end\ndata: {}\n\n"

        return StreamingResponse(source(), media_type="text/event-stream")

    @app.get(
        "/api/report",
        operation_id="download_saved_report",
        summary="Download the saved fixture report",
    )
    def report():
        lines = [
            "# Concordia saved demonstration",
            "",
            "Software fixture; no scientific findings.",
            f"Snapshot: {data['snapshot_digest']}",
            "",
            "## Claim verification",
            "",
        ]
        for claim in data["claims"]:
            lines.append(f"- {claim['text']}: {claim['verification']['status']}")
        lines.extend(["", "## Study readiness", "", data["study"]["reason"]])
        return Response(
            "\n".join(lines),
            media_type="text/markdown",
            headers={"Content-Disposition": 'attachment; filename="concordia-report.md"'},
        )

    @app.post(
        "/nvidia/evo2/generate",
        response_model=NvidiaHostedGenerationResult,
        summary="Interactive hosted Evo2 generation (not part of the read-only tool contract)",
        description=(
            "Accepts a visitor-supplied DNA sequence and calls NVIDIA's hosted "
            "arc/evo2-40b generation API with this deployment's own credential. "
            "Rate-limited per client and cached by content hash. The response is a "
            "real NVIDIA API result but is never scientific evidence."
        ),
    )
    def generate_evo2(
        payload: Evo2GenerateRequest, request: Request
    ) -> NvidiaHostedGenerationResult:
        client_id = _client_ip(request, trust_proxy_headers=trust_proxy_headers)
        try:
            sequence = GenomicSequence(
                sequence_id="interactive:evo2-generate", sequence=payload.sequence, strand="+"
            )
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        try:
            return generation_gateway.generate(
                client_id=client_id,
                sequence=sequence,
                num_tokens=payload.num_tokens,
                temperature=payload.temperature,
                top_k=payload.top_k,
                top_p=payload.top_p,
                random_seed=payload.random_seed,
            )
        except RateLimitExceededError:
            raise
        except RuntimeError as error:
            if "NVIDIA_API_KEY" in str(error):
                raise HTTPException(status_code=503, detail=str(error)) from error
            raise HTTPException(status_code=502, detail=str(error)) from error

    @app.post(
        "/nvidia/evo2/forward",
        summary="Submit a real Evo2 forward-scoring job (unverified, ZeroGPU)",
        description=(
            "Accepts an exact 8,192-base sequence and queues one real forward pass on "
            "a ZeroGPU worker under the frozen HBB scoring protocol. At most one job "
            "runs at a time across all visitors; a job submitted while another is "
            "running completes as REJECTED_BUSY. The result is computational evidence "
            "only and is always marked scientific_use_allowed=false. Poll GET "
            "/nvidia/evo2/forward/{job_id} for the result."
        ),
    )
    def submit_forward_job(
        payload: Evo2ForwardRequest, request: Request, background_tasks: BackgroundTasks
    ) -> dict[str, str]:
        if forward_queue is None:
            raise HTTPException(
                status_code=503,
                detail="forward scoring is not configured on this deployment "
                "(CONCORDIA_EVO2_FORWARD_SPACE_URL is unset)",
            )
        client_id = _client_ip(request, trust_proxy_headers=trust_proxy_headers)
        try:
            sequence = GenomicSequence(
                sequence_id="interactive:evo2-forward", sequence=payload.sequence, strand="+"
            )
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        job_id = forward_queue.submit(client_id=client_id, sequence=sequence)
        background_tasks.add_task(forward_queue.run, job_id, sequence)
        return {"job_id": job_id, "status": "QUEUED"}

    @app.get(
        "/nvidia/evo2/forward/{job_id}",
        summary="Poll a real Evo2 forward-scoring job",
    )
    def get_forward_job(job_id: str) -> dict[str, object]:
        if forward_queue is None:
            raise HTTPException(
                status_code=503, detail="forward scoring is not configured on this deployment"
            )
        try:
            return forward_queue.get(job_id)
        except JobNotFoundError as error:
            raise HTTPException(status_code=404, detail="forward job not found") from error

    @app.post(
        "/nvidia/evo2/attribute",
        summary="Submit an Evo2 gradient-attribution job (ranking signal, not a score)",
        description=(
            "Accepts an exact 8,192-base sequence and queues one forward pass plus "
            "one backward pass on a ZeroGPU worker, returning a ranked shortlist of "
            "the positions whose substitutions are estimated to be most damaging.\n\n"
            "These are first-order estimates, so they are a weak ranking signal and "
            "not a score: confirm any shortlisted position with POST "
            "/nvidia/evo2/forward before relying on it, and do not assume the "
            "shortlist is complete. Measured against exact rescoring on the real HBB "
            "window over 256 sampled substitutions, rank correlation was 0.27 and "
            "effect magnitudes were understated about sevenfold; as a pre-filter for "
            "the most damaging substitutions that is roughly a 1.8-3.6x enrichment "
            "over random at equal budget, so it misses most of them. Every result is "
            "returned with scientific_use_allowed=false.\n\n"
            "This shares one ZeroGPU allocation and one per-client job budget with "
            "/nvidia/evo2/forward; at most one job of either kind runs at a time. "
            "Poll GET /nvidia/evo2/attribute/{job_id} for the result."
        ),
    )
    def submit_attribution_job(
        payload: Evo2AttributeRequest, request: Request, background_tasks: BackgroundTasks
    ) -> dict[str, str]:
        if attribution_queue is None:
            raise HTTPException(
                status_code=503,
                detail="gradient attribution is not configured on this deployment "
                "(CONCORDIA_EVO2_FORWARD_SPACE_URL is unset)",
            )
        client_id = _client_ip(request, trust_proxy_headers=trust_proxy_headers)
        try:
            sequence = GenomicSequence(
                sequence_id="interactive:evo2-attribute", sequence=payload.sequence, strand="+"
            )
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        job_id = attribution_queue.submit(client_id=client_id, sequence=sequence)
        background_tasks.add_task(attribution_queue.run, job_id, sequence)
        return {"job_id": job_id, "status": "QUEUED"}

    @app.get(
        "/nvidia/evo2/attribute/{job_id}",
        summary="Poll an Evo2 gradient-attribution job",
    )
    def get_attribution_job(job_id: str) -> dict[str, object]:
        if attribution_queue is None:
            raise HTTPException(
                status_code=503,
                detail="gradient attribution is not configured on this deployment",
            )
        try:
            return attribution_queue.get(job_id)
        except JobNotFoundError as error:
            raise HTTPException(status_code=404, detail="attribution job not found") from error

    @app.post(
        "/nvidia/openfold2/predict",
        response_model=NvidiaHostedOpenFold2Result,
        summary="Interactive hosted OpenFold2 structure prediction (AlphaFold2-class)",
        description=(
            "Accepts a visitor-supplied amino acid sequence (up to 1,000 residues) and "
            "calls NVIDIA's hosted OpenFold2 NIM with this deployment's own credential. "
            "No MSA or templates are supplied. Output is never scientific evidence."
        ),
    )
    def predict_openfold2(
        payload: OpenFold2PredictRequest, request: Request
    ) -> NvidiaHostedOpenFold2Result:
        client_id = _client_ip(request, trust_proxy_headers=trust_proxy_headers)
        try:
            result: NvidiaHostedOpenFold2Result = openfold2_gateway.predict(
                client_id=client_id, sequence=payload.sequence
            )
            return result
        except RateLimitExceededError:
            raise
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        except RuntimeError as error:
            if "NVIDIA_API_KEY" in str(error):
                raise HTTPException(status_code=503, detail=str(error)) from error
            raise HTTPException(status_code=502, detail=str(error)) from error

    @app.post(
        "/nvidia/boltz/predict",
        response_model=NvidiaHostedBoltzResult,
        summary="Interactive hosted Boltz-2 structure prediction",
        description=(
            "Accepts a visitor-supplied amino acid sequence and calls NVIDIA's hosted "
            "Boltz-2 NIM (mit/boltz2) with this deployment's own credential, including "
            "its async NVCF long-polling protocol when NVIDIA queues the job. "
            "Confirmed live (not deprecated) as of 2026-10-02 — the replacement for the "
            "retired ESMFold model. Rate-limited per client and cached by sequence; "
            "the MSA sent is a one-sequence self-reference, not a real alignment. The "
            "response is a real structure but is never scientific evidence."
        ),
    )
    def predict_boltz(payload: BoltzPredictRequest, request: Request) -> NvidiaHostedBoltzResult:
        client_id = _client_ip(request, trust_proxy_headers=trust_proxy_headers)
        try:
            return boltz_gateway.predict(client_id=client_id, sequence=payload.sequence)
        except RateLimitExceededError:
            raise
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        except RuntimeError as error:
            if "NVIDIA_API_KEY" in str(error):
                raise HTTPException(status_code=503, detail=str(error)) from error
            raise HTTPException(status_code=502, detail=str(error)) from error

    @app.post(
        "/nvidia/boltz/complex",
        response_model=NvidiaHostedBoltzComplexResult,
        summary="Interactive hosted Boltz-2 antibody-antigen complex prediction",
        description=(
            "Accepts a validated multi-chain polymer request and calls NVIDIA's hosted "
            "Boltz-2 NIM through the same rate-limited, cached gateway as the single-chain "
            "endpoint. This is a computational structure hypothesis, never validated "
            "affinity or therapeutic evidence."
        ),
    )
    def predict_boltz_complex(
        payload: BoltzComplexRequest, request: Request
    ) -> NvidiaHostedBoltzComplexResult:
        client_id = _client_ip(request, trust_proxy_headers=trust_proxy_headers)
        try:
            return boltz_gateway.predict_complex(client_id=client_id, request=payload)
        except RateLimitExceededError:
            raise
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        except RuntimeError as error:
            if "NVIDIA_API_KEY" in str(error):
                raise HTTPException(status_code=503, detail=str(error)) from error
            raise HTTPException(status_code=502, detail=str(error)) from error

    @app.post(
        "/colony/run",
        summary="Run one fresh, real colony simulation on demand",
        description=(
            "Executes ColonyScheduler end to end on this request: a new digital "
            "genome, real allowlisted mutations, real deterministic fitness "
            "evaluation, and real survivor selection. No LLM or GPU is involved "
            "(the deterministic fixture executor), so it runs in well under a "
            "second. This is a real execution of real scheduling code, not a "
            "replay of the saved workspace fixture above, but it remains "
            "scientific_use_allowed=false: the evaluated task is a frozen "
            "software fixture, not a genomic question."
        ),
    )
    def run_colony(payload: ColonyRunRequest, request: Request) -> dict[str, object]:
        client_id = _client_ip(request, trust_proxy_headers=trust_proxy_headers)
        colony_run_limiter.check_and_record(client_id)
        try:
            return run_live_colony(
                state_root,
                population_size=payload.population_size,
                generations=payload.generations,
                survivor_count=payload.survivor_count,
            )
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error

    def authorize_experiment(experiment_id: str, token: str | None) -> None:
        if not token:
            raise HTTPException(status_code=401, detail="experiment access token is required")
        try:
            experiment_store.authorize(experiment_id, token)
        except ExperimentNotFoundError as error:
            raise HTTPException(status_code=404, detail="experiment not found") from error
        except ExperimentAccessError as error:
            raise HTTPException(
                status_code=403, detail="invalid experiment access token"
            ) from error

    def authorize_campaign_principal(campaign_id: str, token: str | None) -> CampaignPrincipal:
        if not token:
            raise HTTPException(status_code=401, detail="campaign access token is required")
        try:
            return campaign_store.authorize_principal(campaign_id, token)
        except CampaignNotFoundError as error:
            raise HTTPException(status_code=404, detail="campaign not found") from error
        except CampaignConflictError as error:
            raise HTTPException(status_code=403, detail="invalid campaign access token") from error

    def authorize_campaign_action(
        campaign_id: str, token: str | None, action: CampaignAction
    ) -> Campaign:
        principal = authorize_campaign_principal(campaign_id, token)
        try:
            require_action(principal, action)
        except PermissionError as error:
            raise HTTPException(
                status_code=403, detail="campaign action is not permitted"
            ) from error
        return campaign_store.get_campaign(campaign_id)

    def authorize_campaign(campaign_id: str, token: str | None) -> Campaign:
        return authorize_campaign_action(campaign_id, token, CampaignAction.READ)

    @app.post(
        "/campaigns",
        response_model=CreateCampaignResponse,
        summary="Create a private protein engineering campaign",
    )
    def create_campaign(payload: CreateCampaignRequest, request: Request) -> CreateCampaignResponse:
        experiment_create_limiter.check_and_record(
            _client_ip(request, trust_proxy_headers=trust_proxy_headers)
        )
        return campaign_store.create_campaign_with_token(payload)

    @app.get("/campaigns/{campaign_id}", response_model=Campaign)
    def get_campaign(
        campaign_id: str,
        x_concordia_campaign_token: str | None = Header(default=None),
    ) -> Campaign:
        return authorize_campaign(campaign_id, x_concordia_campaign_token)

    @app.post(
        "/campaigns/{campaign_id}/access-grants",
        response_model=CreateAccessGrantResponse,
        summary="Create a scoped campaign access token",
    )
    def create_campaign_access_grant(
        campaign_id: str,
        payload: CreateAccessGrantRequest,
        x_concordia_campaign_token: str | None = Header(default=None),
    ) -> CreateAccessGrantResponse:
        try:
            return campaign_store.create_access_grant(
                campaign_id, x_concordia_campaign_token or "", payload
            )
        except CampaignNotFoundError as error:
            raise HTTPException(status_code=404, detail="campaign not found") from error
        except CampaignConflictError as error:
            raise HTTPException(status_code=403, detail="invalid campaign access token") from error
        except PermissionError as error:
            raise HTTPException(
                status_code=403, detail="access management is not permitted"
            ) from error

    @app.post(
        "/campaigns/{campaign_id}/access-grants/{grant_id}/revoke",
        status_code=204,
        summary="Revoke a scoped campaign access token",
    )
    def revoke_campaign_access_grant(
        campaign_id: str,
        grant_id: str,
        x_concordia_campaign_token: str | None = Header(default=None),
    ) -> Response:
        try:
            campaign_store.revoke_access_grant(
                campaign_id, x_concordia_campaign_token or "", grant_id
            )
        except CampaignNotFoundError as error:
            raise HTTPException(status_code=404, detail="access grant not found") from error
        except CampaignConflictError as error:
            raise HTTPException(status_code=403, detail="invalid campaign access token") from error
        except PermissionError as error:
            raise HTTPException(
                status_code=403, detail="access management is not permitted"
            ) from error
        return Response(status_code=204)

    @app.get("/campaigns/{campaign_id}/audit-events", response_model=list[CampaignAuditEvent])
    def list_campaign_audit_events(
        campaign_id: str,
        x_concordia_campaign_token: str | None = Header(default=None),
    ) -> list[CampaignAuditEvent]:
        authorize_campaign(campaign_id, x_concordia_campaign_token)
        return list(campaign_store.list_audit_events(campaign_id))

    @app.post("/campaigns/{campaign_id}/status", response_model=Campaign)
    def transition_campaign_status(
        campaign_id: str,
        payload: TransitionCampaignRequest,
        x_concordia_campaign_token: str | None = Header(default=None),
    ) -> Campaign:
        authorize_campaign_action(
            campaign_id, x_concordia_campaign_token, CampaignAction.EDIT_PROTOCOL
        )
        try:
            return campaign_store.transition_campaign(campaign_id, payload.status)
        except CampaignNotFoundError as error:
            raise HTTPException(status_code=404, detail="campaign not found") from error
        except CampaignConflictError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error

    @app.get("/campaigns/{campaign_id}/rounds", response_model=list[CampaignRound])
    def list_campaign_rounds(
        campaign_id: str,
        x_concordia_campaign_token: str | None = Header(default=None),
    ) -> list[CampaignRound]:
        authorize_campaign(campaign_id, x_concordia_campaign_token)
        return list(campaign_store.list_rounds(campaign_id))

    @app.get("/campaigns/{campaign_id}/rounds/{round_id}", response_model=CampaignRound)
    def get_campaign_round(
        campaign_id: str,
        round_id: str,
        x_concordia_campaign_token: str | None = Header(default=None),
    ) -> CampaignRound:
        authorize_campaign(campaign_id, x_concordia_campaign_token)
        try:
            round_record = campaign_store.get_round(round_id)
            if round_record.campaign_id != campaign_id:
                raise CampaignConflictError("round does not belong to campaign")
            return round_record
        except CampaignNotFoundError as error:
            raise HTTPException(status_code=404, detail="round not found") from error
        except CampaignConflictError as error:
            raise HTTPException(status_code=403, detail=str(error)) from error

    @app.post("/campaigns/{campaign_id}/rounds/{round_id}/status", response_model=CampaignRound)
    def transition_campaign_round_status(
        campaign_id: str,
        round_id: str,
        payload: TransitionRoundRequest,
        x_concordia_campaign_token: str | None = Header(default=None),
    ) -> CampaignRound:
        authorize_campaign_action(
            campaign_id, x_concordia_campaign_token, CampaignAction.EDIT_PROTOCOL
        )
        try:
            round_record = campaign_store.get_round(round_id)
            if round_record.campaign_id != campaign_id:
                raise CampaignConflictError("round does not belong to campaign")
            return campaign_store.transition_round(round_id, payload.status)
        except CampaignNotFoundError as error:
            raise HTTPException(status_code=404, detail="round not found") from error
        except CampaignConflictError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error

    @app.post("/campaigns/{campaign_id}/rounds", response_model=CampaignRound)
    def create_campaign_round(
        campaign_id: str,
        payload: CreateRoundRequest,
        x_concordia_campaign_token: str | None = Header(default=None),
    ) -> CampaignRound:
        authorize_campaign_action(
            campaign_id, x_concordia_campaign_token, CampaignAction.EDIT_PROTOCOL
        )
        try:
            return campaign_store.create_round(campaign_id, payload)
        except CampaignNotFoundError as error:
            raise HTTPException(status_code=404, detail="campaign not found") from error
        except CampaignConflictError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error

    @app.post(
        "/campaigns/{campaign_id}/rounds/{round_id}/candidates",
        response_model=Candidate,
    )
    def add_campaign_candidate(
        campaign_id: str,
        round_id: str,
        payload: AddCandidateRequest,
        x_concordia_campaign_token: str | None = Header(default=None),
    ) -> Candidate:
        authorize_campaign_action(
            campaign_id, x_concordia_campaign_token, CampaignAction.EDIT_PROTOCOL
        )
        try:
            round_record = campaign_store.get_round(round_id)
            if round_record.campaign_id != campaign_id:
                raise CampaignConflictError("round does not belong to campaign")
            return campaign_store.add_candidate(round_id, payload)
        except CampaignNotFoundError as error:
            raise HTTPException(status_code=404, detail="round not found") from error
        except CampaignConflictError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error

    @app.get(
        "/campaigns/{campaign_id}/rounds/{round_id}/candidates",
        response_model=list[Candidate],
    )
    def list_campaign_candidates(
        campaign_id: str,
        round_id: str,
        x_concordia_campaign_token: str | None = Header(default=None),
    ) -> list[Candidate]:
        authorize_campaign(campaign_id, x_concordia_campaign_token)
        try:
            round_record = campaign_store.get_round(round_id)
            if round_record.campaign_id != campaign_id:
                raise CampaignConflictError("round does not belong to campaign")
            return list(campaign_store.list_candidates(round_id))
        except CampaignNotFoundError as error:
            raise HTTPException(status_code=404, detail="round not found") from error
        except CampaignConflictError as error:
            raise HTTPException(status_code=403, detail=str(error)) from error

    @app.post(
        "/campaigns/{campaign_id}/rounds/{round_id}/design-plans",
        response_model=CampaignDesignRecord,
        summary="Persist a staged binder-design plan",
    )
    def create_campaign_design_plan(
        campaign_id: str,
        round_id: str,
        payload: CreateDesignPlanRequest,
        x_concordia_campaign_token: str | None = Header(default=None),
    ) -> CampaignDesignRecord:
        authorize_campaign_action(
            campaign_id, x_concordia_campaign_token, CampaignAction.EDIT_PROTOCOL
        )
        try:
            round_record = campaign_store.get_round(round_id)
            if round_record.campaign_id != campaign_id:
                raise CampaignConflictError("round does not belong to campaign")
            plan = build_binder_design_plan(
                plan_id=str(uuid.uuid4()),
                target_structure_digest=payload.target_structure_digest,
                contigs=payload.contigs,
                hotspot_residues=payload.hotspot_residues,
                num_backbones=payload.num_backbones,
                sequences_per_backbone=payload.sequences_per_backbone,
                max_cofolds=payload.max_cofolds,
                budget_units=payload.budget_units,
            )
            return campaign_store.create_design_plan(round_id, plan)
        except CampaignNotFoundError as error:
            raise HTTPException(status_code=404, detail="round not found") from error
        except CampaignConflictError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error

    @app.post(
        "/campaigns/{campaign_id}/rounds/{round_id}/evidence-claims",
        response_model=EvidenceClaim,
        summary="Create an unverified campaign evidence claim",
    )
    def create_campaign_evidence_claim(
        campaign_id: str,
        round_id: str,
        payload: CreateEvidenceClaimRequest,
        x_concordia_campaign_token: str | None = Header(default=None),
    ) -> EvidenceClaim:
        authorize_campaign_action(
            campaign_id, x_concordia_campaign_token, CampaignAction.VERIFY_EVIDENCE
        )
        try:
            round_record = campaign_store.get_round(round_id)
            if round_record.campaign_id != campaign_id:
                raise CampaignConflictError("round does not belong to campaign")
            return campaign_store.create_evidence_claim(round_id, payload)
        except CampaignNotFoundError as error:
            raise HTTPException(status_code=404, detail="round not found") from error
        except CampaignConflictError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error

    @app.post(
        "/campaigns/{campaign_id}/evidence-claims/{claim_id}/verify",
        response_model=EvidenceClaim,
        summary="Verify a campaign evidence claim",
    )
    def verify_campaign_evidence_claim(
        campaign_id: str,
        claim_id: str,
        payload: VerifyEvidenceClaimRequest,
        x_concordia_campaign_token: str | None = Header(default=None),
    ) -> EvidenceClaim:
        authorize_campaign_action(
            campaign_id, x_concordia_campaign_token, CampaignAction.VERIFY_EVIDENCE
        )
        try:
            claim = campaign_store.get_evidence_claim(claim_id)
            if claim.campaign_id != campaign_id:
                raise CampaignConflictError("evidence claim does not belong to campaign")
            return campaign_store.verify_evidence_claim(
                claim_id,
                status=payload.status,
                verifier=payload.verifier,
                independent_validation=payload.independent_validation,
            )
        except CampaignNotFoundError as error:
            raise HTTPException(status_code=404, detail="evidence claim not found") from error
        except (CampaignConflictError, ValueError) as error:
            raise HTTPException(status_code=409, detail=str(error)) from error

    @app.get(
        "/campaigns/{campaign_id}/rounds/{round_id}/report",
        summary="Get a redacted BioRender-compatible campaign report manifest",
    )
    def get_campaign_report(
        campaign_id: str,
        round_id: str,
        x_concordia_campaign_token: str | None = Header(default=None),
    ) -> dict[str, object]:
        authorize_campaign(campaign_id, x_concordia_campaign_token)
        try:
            round_record = campaign_store.get_round(round_id)
            if round_record.campaign_id != campaign_id:
                raise CampaignConflictError("round does not belong to campaign")
            manifest = build_report_manifest(
                campaign_store.get_campaign(campaign_id),
                candidates=campaign_store.list_candidates(round_id),
                datasets=campaign_store.list_datasets(round_id),
                model_runs=campaign_store.list_model_runs(round_id),
                recommendations=campaign_store.list_recommendations(round_id),
                evidence_claims=campaign_store.list_evidence_claims(round_id),
                audit_events=campaign_store.list_audit_events(campaign_id),
                generated_at=datetime.now(UTC),
            )
            return manifest
        except CampaignNotFoundError as error:
            raise HTTPException(status_code=404, detail="round not found") from error
        except CampaignConflictError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error

    @app.post(
        "/campaigns/{campaign_id}/rounds/{round_id}/report:verify",
        summary="Verify an exported campaign report manifest digest",
    )
    def verify_campaign_report(
        campaign_id: str,
        round_id: str,
        manifest: dict[str, object],
        x_concordia_campaign_token: str | None = Header(default=None),
    ) -> dict[str, object]:
        authorize_campaign(campaign_id, x_concordia_campaign_token)
        try:
            round_record = campaign_store.get_round(round_id)
            if round_record.campaign_id != campaign_id:
                raise CampaignConflictError("round does not belong to campaign")
            valid = verify_report_manifest(manifest)
            return {
                "valid": valid,
                "manifest_digest": manifest.get("manifest_digest"),
                "reason": "manifest digest matches canonical payload"
                if valid
                else "manifest digest does not match canonical payload",
            }
        except CampaignNotFoundError as error:
            raise HTTPException(status_code=404, detail="round not found") from error
        except CampaignConflictError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error

    @app.post(
        "/campaigns/{campaign_id}/rounds/{round_id}/measurements",
    )
    def record_campaign_measurement(
        campaign_id: str,
        round_id: str,
        payload: RecordMeasurementRequest,
        x_concordia_campaign_token: str | None = Header(default=None),
    ) -> dict[str, object]:
        authorize_campaign_action(
            campaign_id, x_concordia_campaign_token, CampaignAction.WRITE_ASSAY
        )
        try:
            round_record = campaign_store.get_round(round_id)
            if round_record.campaign_id != campaign_id:
                raise CampaignConflictError("round does not belong to campaign")
            measurement = campaign_store.record_measurement(round_id, payload)
            return measurement.model_dump(mode="json")
        except CampaignNotFoundError as error:
            raise HTTPException(status_code=404, detail="round not found") from error
        except CampaignConflictError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error

    @app.get(
        "/campaigns/{campaign_id}/rounds/{round_id}/measurements",
        response_model=list[Measurement],
    )
    def list_campaign_measurements(
        campaign_id: str,
        round_id: str,
        x_concordia_campaign_token: str | None = Header(default=None),
    ) -> list[Measurement]:
        authorize_campaign(campaign_id, x_concordia_campaign_token)
        try:
            round_record = campaign_store.get_round(round_id)
            if round_record.campaign_id != campaign_id:
                raise CampaignConflictError("round does not belong to campaign")
            return list(campaign_store.list_measurements(round_id))
        except CampaignNotFoundError as error:
            raise HTTPException(status_code=404, detail="round not found") from error
        except CampaignConflictError as error:
            raise HTTPException(status_code=403, detail=str(error)) from error

    @app.get("/campaigns/{campaign_id}/rounds/{round_id}/feedback-summary")
    def campaign_feedback_summary(
        campaign_id: str,
        round_id: str,
        x_concordia_campaign_token: str | None = Header(default=None),
    ) -> dict[str, object]:
        """Summarize imported experimental feedback for the next training round."""
        authorize_campaign(campaign_id, x_concordia_campaign_token)
        try:
            round_record = campaign_store.get_round(round_id)
            if round_record.campaign_id != campaign_id:
                raise CampaignConflictError("round does not belong to campaign")
            measurements = campaign_store.list_measurements(round_id)
            grouped: dict[tuple[str, str], list[float]] = {}
            for item in measurements:
                if item.status.value == "measured" and item.value is not None:
                    grouped.setdefault((item.candidate_id, item.metric), []).append(item.value)
            rows = []
            for (candidate_id, metric), values in sorted(grouped.items()):
                mean = sum(values) / len(values)
                variance = sum((value - mean) ** 2 for value in values) / len(values)
                rows.append({
                    "candidate_id": candidate_id,
                    "metric": metric,
                    "replicates": len(values),
                    "mean": mean,
                    "std": variance ** 0.5,
                })
            return {
                "round_id": round_id,
                "rows": rows,
                "measurement_count": len(measurements),
                "status": "ready_for_training" if rows else "insufficient_evidence",
                "scientific_use_allowed": False,
            }
        except CampaignNotFoundError as error:
            raise HTTPException(status_code=404, detail="round not found") from error
        except CampaignConflictError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error

    @app.post("/campaigns/{campaign_id}/rounds/{round_id}/constraint-check")
    def check_campaign_constraints(
        campaign_id: str,
        round_id: str,
        reference_sequence: str = Query(min_length=1, max_length=100_000),
        candidate_sequence: str = Query(min_length=1, max_length=100_000),
        protected_positions: tuple[int, ...] = Query(default=()),
        x_concordia_campaign_token: str | None = Header(default=None),
    ) -> dict[str, object]:
        authorize_campaign(campaign_id, x_concordia_campaign_token)
        try:
            round_record = campaign_store.get_round(round_id)
            if round_record.campaign_id != campaign_id:
                raise CampaignConflictError("round does not belong to campaign")
            return candidate_constraint_report(
                reference_sequence, candidate_sequence, protected_positions
            )
        except CampaignNotFoundError as error:
            raise HTTPException(status_code=404, detail="round not found") from error
        except CampaignConflictError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error

    @app.post(
        "/campaigns/{campaign_id}/rounds/{round_id}/assays:import",
        summary="Import a validated assay CSV atomically",
    )
    def import_campaign_assays(
        campaign_id: str,
        round_id: str,
        payload: ImportAssayCSVRequest,
        x_concordia_campaign_token: str | None = Header(default=None),
    ) -> dict[str, object]:
        authorize_campaign_action(
            campaign_id, x_concordia_campaign_token, CampaignAction.WRITE_ASSAY
        )
        try:
            round_record = campaign_store.get_round(round_id)
            if round_record.campaign_id != campaign_id:
                raise CampaignConflictError("round does not belong to campaign")
            report = parse_assay_csv(payload.csv_text)
            if not report.valid:
                return {
                    "accepted_count": report.accepted_count,
                    "imported_count": 0,
                    "errors": [error.__dict__ for error in report.errors],
                }
            measurements = campaign_store.record_measurements(round_id, report.rows)
            return {
                "accepted_count": report.accepted_count,
                "imported_count": len(measurements),
                "measurement_ids": [measurement.measurement_id for measurement in measurements],
                "errors": [],
            }
        except CampaignNotFoundError as error:
            raise HTTPException(status_code=404, detail="round not found") from error
        except CampaignConflictError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error

    @app.post(
        "/campaigns/{campaign_id}/rounds/{round_id}/model-runs",
        response_model=CampaignModelRun,
    )
    def record_campaign_model_run(
        campaign_id: str,
        round_id: str,
        payload: RecordModelRunRequest,
        x_concordia_campaign_token: str | None = Header(default=None),
    ) -> CampaignModelRun:
        authorize_campaign_action(campaign_id, x_concordia_campaign_token, CampaignAction.RUN_MODEL)
        if payload.scientific_use_allowed:
            raise HTTPException(
                status_code=422,
                detail="scientific_use_allowed cannot be set by clients",
            )
        if payload.provider not in ALLOWED_EXTERNAL_PROVIDERS | {
            "concordia-protein-baseline",
            "concordia-measured-stability",
        }:
            raise HTTPException(status_code=422, detail="provider is not allow-listed")
        try:
            round_record = campaign_store.get_round(round_id)
            if round_record.campaign_id != campaign_id:
                raise CampaignConflictError("round does not belong to campaign")
            return campaign_store.record_model_run(round_id, payload)
        except CampaignNotFoundError as error:
            raise HTTPException(status_code=404, detail="round not found") from error
        except CampaignConflictError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error

    @app.get(
        "/campaigns/{campaign_id}/model-runs/{model_run_id}/replay-read",
        summary="Replay a recorded campaign model result without execution",
    )
    def replay_read_campaign_model_run(
        campaign_id: str,
        model_run_id: str,
        x_concordia_campaign_token: str | None = Header(default=None),
    ) -> dict[str, object]:
        authorize_campaign(campaign_id, x_concordia_campaign_token)
        try:
            run = campaign_store.get_model_run(model_run_id)
            if run.campaign_id != campaign_id:
                raise CampaignConflictError("model run does not belong to campaign")
            return replay_read(run).model_dump(mode="json")
        except CampaignNotFoundError as error:
            raise HTTPException(status_code=404, detail="model run not found") from error
        except CampaignConflictError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error

    @app.post(
        "/campaigns/{campaign_id}/model-runs/{model_run_id}/replay-execute",
        summary="Queue a fresh campaign model execution for comparison",
    )
    def replay_execute_campaign_model_run(
        campaign_id: str,
        model_run_id: str,
        payload: ReplayExecuteRequest,
        x_concordia_campaign_token: str | None = Header(default=None),
    ) -> dict[str, object]:
        authorize_campaign_action(campaign_id, x_concordia_campaign_token, CampaignAction.RUN_MODEL)
        try:
            source = campaign_store.get_model_run(model_run_id)
            if source.campaign_id != campaign_id:
                raise CampaignConflictError("model run does not belong to campaign")
            replay = campaign_store.clone_model_run_for_replay(model_run_id)
            job = campaign_store.enqueue_model_job(
                campaign_id,
                EnqueueModelJobRequest(
                    model_run_id=replay.model_run_id,
                    budget_units=payload.budget_units,
                ),
            )
            return {"replay": replay_execute(source, replay), "job": job}
        except CampaignNotFoundError as error:
            raise HTTPException(status_code=404, detail="model run not found") from error
        except CampaignConflictError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error

    @app.get("/campaigns/{campaign_id}/model-jobs", response_model=list[CampaignModelJob])
    def list_campaign_model_jobs(
        campaign_id: str,
        x_concordia_campaign_token: str | None = Header(default=None),
    ) -> list[CampaignModelJob]:
        authorize_campaign(campaign_id, x_concordia_campaign_token)
        return list(campaign_store.list_model_jobs(campaign_id))

    @app.post("/campaigns/{campaign_id}/model-jobs", response_model=CampaignModelJob)
    def enqueue_campaign_model_job(
        campaign_id: str,
        payload: EnqueueModelJobRequest,
        x_concordia_campaign_token: str | None = Header(default=None),
    ) -> CampaignModelJob:
        authorize_campaign_action(campaign_id, x_concordia_campaign_token, CampaignAction.RUN_MODEL)
        try:
            return campaign_store.enqueue_model_job(campaign_id, payload)
        except CampaignNotFoundError as error:
            raise HTTPException(status_code=404, detail="model run not found") from error
        except CampaignConflictError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error

    @app.get("/campaigns/{campaign_id}/model-jobs/{job_id}", response_model=CampaignModelJob)
    def get_campaign_model_job(
        campaign_id: str,
        job_id: str,
        x_concordia_campaign_token: str | None = Header(default=None),
    ) -> CampaignModelJob:
        authorize_campaign(campaign_id, x_concordia_campaign_token)
        try:
            job = campaign_store.get_model_job(job_id)
            if job.campaign_id != campaign_id:
                raise CampaignConflictError("model job does not belong to campaign")
            return job
        except CampaignNotFoundError as error:
            raise HTTPException(status_code=404, detail="model job not found") from error
        except CampaignConflictError as error:
            raise HTTPException(status_code=403, detail=str(error)) from error

    @app.post(
        "/campaigns/{campaign_id}/model-jobs/{job_id}/cancel",
        response_model=CampaignModelJob,
    )
    def cancel_campaign_model_job(
        campaign_id: str,
        job_id: str,
        x_concordia_campaign_token: str | None = Header(default=None),
    ) -> CampaignModelJob:
        authorize_campaign_action(campaign_id, x_concordia_campaign_token, CampaignAction.RUN_MODEL)
        try:
            job = campaign_store.get_model_job(job_id)
            if job.campaign_id != campaign_id:
                raise CampaignConflictError("model job does not belong to campaign")
            return campaign_store.cancel_model_job(job_id)
        except CampaignNotFoundError as error:
            raise HTTPException(status_code=404, detail="model job not found") from error
        except CampaignConflictError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error

    @app.post("/campaigns/{campaign_id}/model-jobs/{job_id}/run", response_model=CampaignModelJob)
    def run_campaign_model_job(
        campaign_id: str,
        job_id: str,
        x_concordia_campaign_token: str | None = Header(default=None),
    ) -> CampaignModelJob:
        """Execute one explicitly selected job through its registered connector."""
        authorize_campaign_action(campaign_id, x_concordia_campaign_token, CampaignAction.RUN_MODEL)
        try:
            job = campaign_store.get_model_job(job_id)
            if job.campaign_id != campaign_id:
                raise CampaignConflictError("model job does not belong to campaign")
            result = campaign_worker.run_once(job_id=job_id)
            if result is None:
                raise HTTPException(status_code=409, detail="model job is not runnable")
            return result
        except ModelConnectorError as error:
            raise HTTPException(status_code=502, detail="model connector failed") from error
        except CampaignNotFoundError as error:
            raise HTTPException(status_code=404, detail="model job not found") from error
        except CampaignConflictError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error

    @app.post("/campaigns/{campaign_id}/rounds/{round_id}/datasets", response_model=DatasetSnapshot)
    def freeze_campaign_dataset(
        campaign_id: str,
        round_id: str,
        transformation_policy: str = Query(min_length=1, max_length=500),
        x_concordia_campaign_token: str | None = Header(default=None),
    ) -> DatasetSnapshot:
        authorize_campaign_action(
            campaign_id, x_concordia_campaign_token, CampaignAction.WRITE_ASSAY
        )
        try:
            round_record = campaign_store.get_round(round_id)
            if round_record.campaign_id != campaign_id:
                raise CampaignConflictError("round does not belong to campaign")
            return campaign_store.freeze_dataset(round_id, transformation_policy)
        except CampaignNotFoundError as error:
            raise HTTPException(status_code=404, detail="round not found") from error
        except CampaignConflictError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error

    @app.post(
        "/campaigns/{campaign_id}/rounds/{round_id}/studies",
        response_model=CampaignStudy,
        summary="Create a preregistered campaign study record",
    )
    def create_campaign_study(
        campaign_id: str,
        round_id: str,
        payload: CreateStudyRequest,
        x_concordia_campaign_token: str | None = Header(default=None),
    ) -> CampaignStudy:
        authorize_campaign_action(
            campaign_id, x_concordia_campaign_token, CampaignAction.EDIT_PROTOCOL
        )
        try:
            round_record = campaign_store.get_round(round_id)
            if round_record.campaign_id != campaign_id:
                raise CampaignConflictError("round does not belong to campaign")
            return campaign_store.create_study(round_id, payload)
        except CampaignNotFoundError as error:
            raise HTTPException(status_code=404, detail="round or dataset not found") from error
        except CampaignConflictError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error

    @app.get(
        "/campaigns/{campaign_id}/studies/{study_id}",
        response_model=CampaignStudy,
        summary="Read a campaign study admission record",
    )
    def get_campaign_study(
        campaign_id: str,
        study_id: str,
        x_concordia_campaign_token: str | None = Header(default=None),
    ) -> CampaignStudy:
        authorize_campaign(campaign_id, x_concordia_campaign_token)
        try:
            study = campaign_store.get_study(study_id)
            if study.campaign_id != campaign_id:
                raise CampaignConflictError("study does not belong to campaign")
            return study
        except CampaignNotFoundError as error:
            raise HTTPException(status_code=404, detail="study not found") from error
        except CampaignConflictError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error

    @app.post(
        "/campaigns/{campaign_id}/studies/{study_id}/freeze",
        response_model=CampaignStudy,
        summary="Freeze a preregistered campaign study",
    )
    def freeze_campaign_study(
        campaign_id: str,
        study_id: str,
        x_concordia_campaign_token: str | None = Header(default=None),
    ) -> CampaignStudy:
        authorize_campaign_action(
            campaign_id, x_concordia_campaign_token, CampaignAction.EDIT_PROTOCOL
        )
        try:
            study = campaign_store.get_study(study_id)
            if study.campaign_id != campaign_id:
                raise CampaignConflictError("study does not belong to campaign")
            return campaign_store.freeze_study_record(study_id)
        except CampaignNotFoundError as error:
            raise HTTPException(status_code=404, detail="study not found") from error
        except (CampaignConflictError, ValueError) as error:
            raise HTTPException(status_code=409, detail=str(error)) from error

    @app.post(
        "/campaigns/{campaign_id}/studies/{study_id}/admit",
        response_model=dict[str, object],
        summary="Evaluate fail-closed study admission",
    )
    def admit_campaign_study(
        campaign_id: str,
        study_id: str,
        x_concordia_campaign_token: str | None = Header(default=None),
    ) -> dict[str, object]:
        authorize_campaign_action(
            campaign_id, x_concordia_campaign_token, CampaignAction.VERIFY_EVIDENCE
        )
        try:
            study = campaign_store.get_study(study_id)
            if study.campaign_id != campaign_id:
                raise CampaignConflictError("study does not belong to campaign")
            updated, report = campaign_store.admit_study(study_id)
            return {"study": updated, "report": report, "passed": report.passed}
        except CampaignNotFoundError as error:
            raise HTTPException(status_code=404, detail="study not found") from error
        except CampaignConflictError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error

    @app.post(
        "/campaigns/{campaign_id}/rounds/{round_id}/datasets/{dataset_id}/benchmark",
        summary="Run a retrospective benchmark on a frozen campaign dataset",
    )
    def benchmark_campaign_dataset(
        campaign_id: str,
        round_id: str,
        dataset_id: str,
        metric: str | None = Query(default=None, min_length=1, max_length=200),
        seeds: tuple[int, ...] = Query(default=(0, 1, 2), min_length=1, max_length=10),
        x_concordia_campaign_token: str | None = Header(default=None),
    ) -> dict[str, object]:
        authorize_campaign(campaign_id, x_concordia_campaign_token)
        try:
            round_record = campaign_store.get_round(round_id)
            dataset = campaign_store.get_dataset_snapshot(dataset_id)
            if round_record.campaign_id != campaign_id or dataset.round_id != round_id:
                raise CampaignConflictError("dataset does not belong to this campaign round")
            examples = campaign_store.get_training_examples(dataset_id, metric=metric)
            benchmark = run_retrospective_benchmark(examples, seeds=seeds)
            digest = benchmark_digest(benchmark)
            artifact_payload = {
                "schema_version": 1,
                "kind": "campaign_retrospective_benchmark",
                "campaign_id": campaign_id,
                "round_id": round_id,
                "dataset_id": dataset_id,
                "metric": metric,
                "seeds": list(seeds),
                "benchmark_digest": digest,
                "benchmark": asdict(benchmark),
            }
            artifact = campaign_artifact_store.put(
                json.dumps(artifact_payload, sort_keys=True, separators=(",", ":")).encode(),
                kind="report",
                media_type="application/json",
            )
            campaign_store.append_audit_event(
                campaign_id,
                actor="campaign-token",
                action="benchmark.completed",
                resource_type="dataset",
                resource_id=dataset_id,
                payload={
                    "round_id": round_id,
                    "metric": metric,
                    "seeds": seeds,
                    "benchmark_digest": digest,
                    "artifact_digest": artifact.digest,
                    "prospective_claim_allowed": benchmark.prospective_claim_allowed,
                },
            )
            return asdict(benchmark) | {
                "benchmark_digest": digest,
                "benchmark_artifact": artifact,
            }
        except CampaignNotFoundError as error:
            raise HTTPException(status_code=404, detail="dataset or round not found") from error
        except CampaignConflictError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error

    @app.get(
        "/campaigns/{campaign_id}/artifacts/{digest}",
        response_class=Response,
        summary="Read an authenticated campaign artifact",
    )
    def read_campaign_artifact(
        campaign_id: str,
        digest: str,
        x_concordia_campaign_token: str | None = Header(default=None),
    ) -> Response:
        authorize_campaign(campaign_id, x_concordia_campaign_token)
        if len(digest) != 64 or any(character not in "0123456789abcdef" for character in digest):
            raise HTTPException(status_code=404, detail="artifact not found")
        linked = any(
            event.action == "benchmark.completed"
            and event.payload.get("artifact_digest") == digest
            for event in campaign_store.list_audit_events(campaign_id)
        )
        if not linked:
            raise HTTPException(status_code=404, detail="artifact not found")
        try:
            payload = campaign_artifact_store.store.get_bytes(digest)
        except KeyError as error:
            raise HTTPException(status_code=404, detail="artifact not found") from error
        except ValueError as error:
            raise HTTPException(
                status_code=409, detail="artifact integrity check failed"
            ) from error
        if hashlib.sha256(payload).hexdigest() != digest:
            raise HTTPException(status_code=409, detail="artifact integrity check failed")
        return Response(
            content=payload,
            media_type="application/json",
            headers={"ETag": f'"{digest}"'},
        )

    @app.get(
        "/campaigns/{campaign_id}/rounds/{round_id}/validation",
        summary="Run campaign release validation gates",
    )
    def validate_campaign_round_api(
        campaign_id: str,
        round_id: str,
        x_concordia_campaign_token: str | None = Header(default=None),
    ) -> dict[str, object]:
        authorize_campaign(campaign_id, x_concordia_campaign_token)
        try:
            round_record = campaign_store.get_round(round_id)
            if round_record.campaign_id != campaign_id:
                raise CampaignConflictError("round does not belong to campaign")
            report = validate_campaign_round(
                campaign_store.list_measurements(round_id),
                campaign_store.list_model_runs(round_id),
                campaign_store.list_datasets(round_id),
                campaign_store.list_audit_events(campaign_id),
            )
            return asdict(report) | {"passed": report.passed}
        except CampaignNotFoundError as error:
            raise HTTPException(status_code=404, detail="round not found") from error
        except CampaignConflictError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error

    @app.post(
        "/campaigns/{campaign_id}/rounds/{round_id}/recommendations",
        response_model=Recommendation,
    )
    def create_campaign_recommendation(
        campaign_id: str,
        round_id: str,
        candidate_ids: tuple[str, ...],
        policy: str = Query(min_length=1, max_length=200),
        evidence_snapshot: tuple[str, ...] = (),
        rationale: dict[str, object] | None = None,
        x_concordia_campaign_token: str | None = Header(default=None),
    ) -> Recommendation:
        authorize_campaign_action(campaign_id, x_concordia_campaign_token, CampaignAction.RUN_MODEL)
        try:
            round_record = campaign_store.get_round(round_id)
            if round_record.campaign_id != campaign_id:
                raise CampaignConflictError("round does not belong to campaign")
            return campaign_store.create_recommendation(
                round_id,
                candidate_ids,
                policy=policy,
                evidence_snapshot=evidence_snapshot,
                rationale=rationale or {},
            )
        except CampaignNotFoundError as error:
            raise HTTPException(status_code=404, detail="round not found") from error
        except CampaignConflictError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error

    @app.post(
        "/campaigns/{campaign_id}/rounds/{round_id}/recommendations:select",
        response_model=Recommendation,
        summary="Select and persist a deterministic recommendation batch",
    )
    def select_campaign_recommendation(
        campaign_id: str,
        round_id: str,
        payload: SelectRecommendationRequest,
        x_concordia_campaign_token: str | None = Header(default=None),
    ) -> Recommendation:
        authorize_campaign_action(campaign_id, x_concordia_campaign_token, CampaignAction.RUN_MODEL)
        try:
            round_record = campaign_store.get_round(round_id)
            if round_record.campaign_id != campaign_id:
                raise CampaignConflictError("round does not belong to campaign")
            result = select_candidates(
                tuple(
                    SelectionCandidate(
                        candidate_id=candidate.candidate_id,
                        score=candidate.score,
                        sequence=candidate.sequence,
                        is_reference=candidate.is_reference,
                        measured=candidate.measured,
                        uncertainty=candidate.uncertainty,
                        constraint_violations=candidate.constraint_violations,
                    )
                    for candidate in payload.candidates
                ),
                policy=payload.policy,
                batch_size=payload.batch_size,
                seed=payload.seed,
                reference_candidate_id=payload.reference_candidate_id,
                require_measured=payload.require_measured,
                max_uncertainty=payload.max_uncertainty,
            )
            rationale = {
                **result.rationale,
                **payload.rationale,
                "selection_input_digest": _selection_input_digest(payload.candidates),
            }
            return campaign_store.create_recommendation(
                round_id,
                result.candidate_ids,
                policy=result.policy,
                evidence_snapshot=payload.evidence_snapshot,
                rationale=rationale,
            )
        except CampaignNotFoundError as error:
            raise HTTPException(status_code=404, detail="round not found") from error
        except CampaignConflictError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error

    @app.post(
        "/campaigns/{campaign_id}/recommendations/{recommendation_id}/replay",
        summary="Replay a persisted recommendation against scored candidates",
    )
    def replay_campaign_recommendation(
        campaign_id: str,
        recommendation_id: str,
        payload: ReplayRecommendationRequest,
        x_concordia_campaign_token: str | None = Header(default=None),
    ) -> dict[str, object]:
        authorize_campaign(campaign_id, x_concordia_campaign_token)
        try:
            recommendation = campaign_store.get_recommendation(recommendation_id)
            if recommendation.campaign_id != campaign_id:
                raise CampaignConflictError("recommendation does not belong to campaign")
            report = validate_recommendation_replay(
                recommendation,
                tuple(
                    SelectionCandidate(
                        candidate_id=candidate.candidate_id,
                        score=candidate.score,
                        sequence=candidate.sequence,
                    )
                    for candidate in payload.candidates
                ),
                batch_size=payload.batch_size,
                seed=payload.seed,
            )
            expected_digest = recommendation.rationale.get("selection_input_digest")
            if isinstance(expected_digest, str):
                digest_matches = expected_digest == _selection_input_digest(payload.candidates)
                report = ValidationReport(
                    (
                        ValidationCheck(
                            "selection_input_digest",
                            digest_matches,
                            "replay inputs match the persisted selection input digest"
                            if digest_matches
                            else "replay inputs differ from the persisted selection input digest",
                        ),
                        *report.checks,
                    )
                )
            return asdict(report) | {"passed": report.passed}
        except CampaignNotFoundError as error:
            raise HTTPException(status_code=404, detail="recommendation not found") from error
        except CampaignConflictError as error:
            raise HTTPException(status_code=403, detail=str(error)) from error

    @app.post(
        "/experiments",
        response_model=CreateExperimentResponse,
        summary="Create a private molecular experiment sandbox",
    )
    def create_experiment(
        payload: CreateExperimentRequest, request: Request
    ) -> CreateExperimentResponse:
        experiment_create_limiter.check_and_record(
            _client_ip(request, trust_proxy_headers=trust_proxy_headers)
        )
        return experiment_store.create(payload)

    @app.get(
        "/experiments/{experiment_id}",
        response_model=ExperimentManifest,
        summary="Replay an experiment as a reproducible provenance graph",
    )
    def get_experiment(
        experiment_id: str,
        x_concordia_experiment_token: str | None = Header(default=None),
    ) -> ExperimentManifest:
        authorize_experiment(experiment_id, x_concordia_experiment_token)
        return experiment_store.manifest(experiment_id)

    @app.post(
        "/experiments/{experiment_id}/nodes",
        response_model=ExperimentNode,
        summary="Add an immutable molecular object or operation to an experiment",
    )
    def add_experiment_node(
        experiment_id: str,
        payload: CreateExperimentNodeRequest,
        x_concordia_experiment_token: str | None = Header(default=None),
    ) -> ExperimentNode:
        authorize_experiment(experiment_id, x_concordia_experiment_token)
        if payload.scientific_use_allowed:
            # Only server-side verified operations may mark an object usable as
            # scientific evidence; a client must never self-certify its own nodes.
            raise HTTPException(
                status_code=422,
                detail="scientific_use_allowed cannot be set by clients",
            )
        try:
            return experiment_store.add_node(experiment_id, payload)
        except ExperimentConflictError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error

    @app.get(
        "/experiments/{experiment_id}/nodes/{node_id}/payload",
        summary="Read one authorized experiment node payload",
    )
    def get_experiment_node_payload(
        experiment_id: str,
        node_id: str,
        x_concordia_experiment_token: str | None = Header(default=None),
    ) -> dict[str, object]:
        authorize_experiment(experiment_id, x_concordia_experiment_token)
        try:
            return experiment_store.payload(experiment_id, node_id)
        except ExperimentNodeNotFoundError as error:
            raise HTTPException(status_code=404, detail="experiment node not found") from error

    @app.post(
        "/experiments/{experiment_id}/candidates/{node_id}",
        response_model=ExperimentManifest,
        summary="Save an experiment node as a promising candidate",
    )
    def select_experiment_candidate(
        experiment_id: str,
        node_id: str,
        x_concordia_experiment_token: str | None = Header(default=None),
    ) -> ExperimentManifest:
        authorize_experiment(experiment_id, x_concordia_experiment_token)
        try:
            return experiment_store.select(experiment_id, node_id)
        except ExperimentNodeNotFoundError as error:
            raise HTTPException(status_code=404, detail="experiment node not found") from error

    @app.get(
        "/experiments/{experiment_id}/compare",
        response_model=ExperimentComparison,
        summary="Compare two molecular objects or measurements",
    )
    def compare_experiment_nodes(
        experiment_id: str,
        left: str = Query(min_length=1),
        right: str = Query(min_length=1),
        x_concordia_experiment_token: str | None = Header(default=None),
    ) -> ExperimentComparison:
        authorize_experiment(experiment_id, x_concordia_experiment_token)
        try:
            return experiment_store.compare(experiment_id, left, right)
        except ExperimentNodeNotFoundError as error:
            raise HTTPException(status_code=404, detail="comparison node not found") from error

    @app.post(
        "/experiments/{experiment_id}/operations/evo2/generate",
        response_model=ExperimentEvo2GenerateResponse,
        summary="Generate DNA with Evo2 and record complete experiment lineage",
    )
    def generate_evo2_in_experiment(
        experiment_id: str,
        payload: ExperimentEvo2GenerateRequest,
        request: Request,
        x_concordia_experiment_token: str | None = Header(default=None),
    ) -> ExperimentEvo2GenerateResponse:
        authorize_experiment(experiment_id, x_concordia_experiment_token)
        try:
            parent_payload = experiment_store.payload(experiment_id, payload.parent_node_id)
        except ExperimentNodeNotFoundError as error:
            raise HTTPException(status_code=404, detail="parent node not found") from error
        normalized = "".join(payload.sequence.upper().split())
        if (
            parent_payload.get("payload_type") != "dna"
            or parent_payload.get("sequence") != normalized
        ):
            raise HTTPException(
                status_code=409,
                detail="submitted sequence must exactly match the selected DNA parent",
            )
        sequence = GenomicSequence(
            sequence_id=f"experiment:{experiment_id}:{payload.parent_node_id}",
            sequence=normalized,
            strand="+",
        )
        try:
            result = generation_gateway.generate(
                client_id=_client_ip(request, trust_proxy_headers=trust_proxy_headers),
                sequence=sequence,
                num_tokens=payload.num_tokens,
                temperature=payload.temperature,
                top_k=payload.top_k,
                top_p=payload.top_p,
                random_seed=payload.random_seed,
            )
        except RateLimitExceededError:
            raise
        except RuntimeError as error:
            status = 503 if "NVIDIA_API_KEY" in str(error) else 502
            raise HTTPException(status_code=status, detail=str(error)) from error
        run_node, output_node = experiment_store.record_model_operation(
            experiment_id,
            parent_node_id=payload.parent_node_id,
            branch=payload.branch,
            run_label="Evo2 generation",
            run_payload=ModelRunPayload(
                model=result.model_id,
                model_version=result.model_id,
                parameters={
                    "num_tokens": payload.num_tokens,
                    "temperature": payload.temperature,
                    "top_k": payload.top_k,
                    "top_p": payload.top_p,
                },
                seed=payload.random_seed,
                execution_mode=result.execution_mode,
            ),
            output_label="Evo2 generated DNA",
            output_kind=ExperimentNodeKind.DNA_SEQUENCE,
            output_payload=DnaPayload(sequence=result.generated_sequence),
            operation=ExperimentOperation.GENERATE,
            evidence_artifact_digests=(
                result.request_artifact_digest,
                result.response_artifact_digest,
            ),
            scientific_use_allowed=False,
        )
        return ExperimentEvo2GenerateResponse(
            result=result, run_node=run_node, output_node=output_node
        )

    @app.post(
        "/experiments/{experiment_id}/operations/boltz/predict",
        response_model=ExperimentBoltzPredictResponse,
        summary="Predict a structure with Boltz-2 and record complete experiment lineage",
    )
    def predict_boltz_in_experiment(
        experiment_id: str,
        payload: ExperimentBoltzPredictRequest,
        request: Request,
        x_concordia_experiment_token: str | None = Header(default=None),
    ) -> ExperimentBoltzPredictResponse:
        authorize_experiment(experiment_id, x_concordia_experiment_token)
        try:
            parent_payload = experiment_store.payload(experiment_id, payload.parent_node_id)
        except ExperimentNodeNotFoundError as error:
            raise HTTPException(status_code=404, detail="parent node not found") from error
        normalized = "".join(payload.sequence.upper().split())
        if (
            parent_payload.get("payload_type") != "protein"
            or parent_payload.get("sequence") != normalized
        ):
            raise HTTPException(
                status_code=409,
                detail="submitted sequence must exactly match the selected protein parent",
            )
        try:
            result = boltz_gateway.predict(
                client_id=_client_ip(request, trust_proxy_headers=trust_proxy_headers),
                sequence=normalized,
            )
        except RateLimitExceededError:
            raise
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        except RuntimeError as error:
            status = 503 if "NVIDIA_API_KEY" in str(error) else 502
            raise HTTPException(status_code=status, detail=str(error)) from error
        run_node, output_node = experiment_store.record_model_operation(
            experiment_id,
            parent_node_id=payload.parent_node_id,
            branch=payload.branch,
            run_label="Boltz-2 structure prediction",
            run_payload=ModelRunPayload(
                model=result.model_id,
                model_version=result.model_id,
                parameters={"msa_method": "single_sequence_self_reference"},
                execution_mode=result.execution_mode,
            ),
            output_label="Boltz-2 predicted structure",
            output_kind=ExperimentNodeKind.STRUCTURE,
            output_payload=StructurePayload(
                format="mmcif" if result.structure_format.lower() == "mmcif" else "pdb",
                structure_text=result.structure_text,
            ),
            operation=ExperimentOperation.PREDICT_STRUCTURE,
            evidence_artifact_digests=(
                result.request_artifact_digest,
                result.response_artifact_digest,
            ),
            scientific_use_allowed=False,
        )
        return ExperimentBoltzPredictResponse(
            result=result, run_node=run_node, output_node=output_node
        )

    @app.post(
        "/v1/structure-claims/verify",
        summary="Verify a predicted interface against deterministic rules",
        description=(
            "Applies the structure rule pack to measured signals and returns a status "
            "with its reasons. No language model is involved and no threshold is "
            "learned: a claim needs independent evidence families and a passing "
            "counterfactual, or it is reported as unverifiable. Nothing is stored and "
            "no external model is called, so this endpoint spends nothing. Supply "
            "measurements from scripts/structure_measurements.py or your own tooling; "
            "agreement measured across samples of one model is deliberately too weak "
            "to carry a claim on its own."
        ),
    )
    def verify_structure_claim(payload: StructureClaimVerifyRequest) -> dict[str, object]:
        try:
            scope = StructureScope(
                complex_id=payload.complex_id,
                receptor_chains=payload.receptor_chains,
                ligand_chains=payload.ligand_chains,
                model_checkpoint=payload.model,
                settings_digest=hashlib.sha256(
                    json.dumps(payload.settings, sort_keys=True, separators=(",", ":")).encode()
                ).hexdigest(),
                assay=payload.assay,
            )
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        result = verify_measurements(
            payload.measurements,
            scope,
            claim_text=payload.claim_text,
            include_reference=payload.include_reference,
        )
        _, findings = plausibility(payload.measurements)
        return {
            "schema_version": 1,
            "rule_pack": RULE_PACK_VERSION,
            "status": result.status.value,
            "reasons": list(result.reasons),
            "supporting_families": [family.value for family in result.supporting_families],
            "contradicting_families": [family.value for family in result.contradicting_families],
            "physical_findings": list(findings),
            "checks": [
                {
                    "evidence_id": check.evidence_id,
                    "family": check.family.value,
                    "method": check.method,
                    "assessment": check.assessment,
                    "valid": check.valid,
                    "reasons": list(check.reasons),
                }
                for check in result.checks
            ],
            "settings_digest": scope.settings_digest,
            "scientific_use_allowed": result.scientific_use_allowed,
            "limitation": result.limitation,
        }

    @app.post(
        "/v1/structure-claims/baseline",
        summary="Benchmark the independent geometry-only structure control",
        description=(
            "Evaluates a fixed physical-plausibility rule against retrospective "
            "external labels. The labels are benchmark outcomes, never evidence for "
            "a claim. Both positive and negative cases are required, and the returned "
            "report is always ineligible for scientific or prospective use."
        ),
    )
    def benchmark_structure_baseline(payload: StructureBaselineRequest) -> dict[str, object]:
        try:
            report = run_structure_baseline(payload.cases)
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        return report.model_dump(mode="json")

    @app.get("/.well-known/concordia-tools.json", include_in_schema=False)
    @app.get("/api/tools", include_in_schema=False)
    def tool_manifest():
        return _tool_manifest("postgres" if database_url else "ephemeral_sqlite")

    @app.get("/api/frameworks", summary="List scientific frameworks and evidence boundaries")
    def frameworks():
        return {
            "schema_version": 1,
            "frameworks": [framework.model_dump(mode="json") for framework in framework_catalog()],
        }

    @app.get("/api/tools/openapi.json", include_in_schema=False)
    def tool_openapi():
        schema = deepcopy(app.openapi())
        schema["info"] = {
            "title": "Concordia read-only evidence tools",
            "version": "1.0.0",
            "description": (
                "GET-only inspection of a saved fixture-backed evidence workspace. "
                "No user sequence, model inference, sandbox execution, or scientific finding "
                "is exposed."
            ),
        }
        schema["paths"] = {path: schema["paths"][path] for path in TOOL_PATHS}
        schema["servers"] = [{"url": "/"}]
        schema["externalDocs"] = {
            "description": "Privacy notice",
            "url": "https://srikarjy025-concordia-colony.hf.space/privacy",
        }
        return schema

    if Path(frontend).is_dir():
        app.mount("/", StaticFiles(directory=frontend, html=True), name="workspace")
    return app
