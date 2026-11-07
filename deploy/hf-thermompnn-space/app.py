"""CPU-only HTTP adapter for the frozen measured-stability workflow."""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Annotated, Any

from fastapi import Body, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, ConfigDict, Field

from concordia.stability.measured import MeasuredStabilityEngine
from concordia.stability.request import TypedStabilityRequest, run_typed_request


class ScoreRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    domain: str = "1IGV"
    mutations: list[str] = Field(min_length=1, max_length=100)


class ScoreResponse(BaseModel):
    """The backend report, preserving refusal trigger evidence verbatim."""

    model_config = ConfigDict(extra="allow")

    manifest_digest: str
    domain_id: str
    property: str
    ranker: str
    candidates: list[dict[str, Any]]
    refusals: list[dict[str, Any]]


class DomainMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid")

    domain_id: str
    length: int
    manifest_digest: str
    protected_residues: list[dict[str, Any]]
    t2_policy: dict[str, Any]


app = FastAPI(title="Concordia measured stability", version="1")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        origin.strip()
        for origin in os.environ.get("CONCORDIA_ALLOWED_ORIGINS", "https://concordia.srikarjy.site").split(",")
        if origin.strip()
    ],
    allow_methods=["GET", "POST"],
    allow_headers=["content-type"],
)
_engine: MeasuredStabilityEngine | None = None
_state_root = Path(os.environ.get("CONCORDIA_STATE_ROOT", "/app/.concordia/thermompnn"))


@app.get("/")
def root() -> dict[str, Any]:
    """Describe the public API without triggering model loading."""

    return {
        "service": "Concordia measured stability",
        "status": "ok",
        "domain": "1IGV",
        "endpoints": ["/health", "/domain/1IGV", "/score", "/docs"],
        "note": "CPU-only ThermoMPNN wrapper; no hosted NVIDIA calls",
    }


def _get_engine() -> MeasuredStabilityEngine:
    global _engine
    if _engine is None:
        _engine = MeasuredStabilityEngine()
    return _engine


def _request_from_body(body: ScoreRequest | list[str]) -> TypedStabilityRequest:
    if isinstance(body, list):
        return TypedStabilityRequest.from_cli("1IGV", ",".join(body))
    return TypedStabilityRequest.from_cli(body.domain, ",".join(body.mutations))


@app.get("/health")
def health() -> dict[str, Any]:
    return {"status": "ok", "model_loaded": _engine is not None}


@app.get("/domain/{domain}", response_model=DomainMetadata)
def domain_metadata(domain: str) -> DomainMetadata:
    engine = _get_engine()
    selected = str(engine.manifest["selection"]["selected_domain_id"])
    if domain not in {selected, selected.removesuffix(".pdb")}:
        raise HTTPException(status_code=422, detail="only frozen domain 1IGV is available")
    policy = dict(engine.t2_recalibration["conditional_policy"])
    policy["explanation"] = (
        "T2 is calibrated for novel positions only; known-position variants cannot "
        "trigger T2 and are governed by T1."
    )
    return DomainMetadata(
        domain_id=selected,
        length=int(engine.manifest["selection"]["length"]),
        manifest_digest=engine.manifest_digest,
        protected_residues=list(engine.manifest["selection"]["hard_protected_residues"]),
        t2_policy=policy,
    )


@app.post("/score", response_model=ScoreResponse)
def score(body: Annotated[ScoreRequest | list[str], Body(...)]) -> ScoreResponse:
    try:
        request = _request_from_body(body)
        report = run_typed_request(request, state_root=_state_root, engine=_get_engine())
    except (ValueError, KeyError) as exc:
        match = re.search(r"position (\d+) is outside the manifest mutable range", str(exc))
        if match is not None:
            position = int(match.group(1))
            raise HTTPException(
                status_code=422,
                detail={
                    "refused": True,
                    "triggers": [
                        {
                            "code": "OUT_OF_RANGE",
                            "position": position,
                            "evidence": "manifest mutable range 1-74",
                        }
                    ],
                },
            ) from exc
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return ScoreResponse.model_validate(report)
