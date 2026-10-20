"""Authenticated structure inspection following the existing stability service.

This explicit inspection action does not change the automatic refold gate or use
structure confidence as stability evidence. NVIDIA credentials stay on this server.
"""

from __future__ import annotations

import hashlib
import hmac
import re
import threading
import uuid
from pathlib import Path
from typing import Annotated, Any, Literal

import httpx
from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, ConfigDict, Field

from concordia.events.sqlite import SQLiteEventLedger
from concordia.genomics.boltz_gateway import BoltzGateway
from concordia.genomics.rate_limiting import RateLimitExceededError
from concordia.storage.content import ContentAddressedStore

SCOPE = (
    "Explicit computational structure inspection. Boltz-2 confidence is not stability "
    "evidence and does not change the ThermoMPNN + one-hot ranking. The self-reference "
    "MSA is a single sequence. No claim of folding, stability, expression or function."
)


class StructureInspectionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    domain: Literal["1IGV"] = "1IGV"
    mutations: list[str] = Field(min_length=1, max_length=100)
    selected_mutation: str = Field(min_length=3, max_length=16)


def create_structure_workflow_app(
    *,
    state_root: Path,
    sequence: str,
    manifest_digest: str,
    access_token_sha256: str,
    gateway: BoltzGateway,
    scoring_url: str,
    scoring_transport: httpx.BaseTransport | None = None,
) -> FastAPI:
    app = FastAPI(title="Concordia structure inspection", docs_url=None, redoc_url=None)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["https://concordia.srikarjy.site"],
        allow_methods=["POST", "GET"],
        allow_headers=["authorization", "content-type"],
    )
    state_root.mkdir(parents=True, exist_ok=True)
    store = ContentAddressedStore(state_root / "artifacts")
    ledger = SQLiteEventLedger(state_root / "events.sqlite3")
    lock = threading.Lock()

    def authorize(authorization: Annotated[str | None, Header()] = None) -> None:
        if not re.fullmatch(r"[a-f0-9]{64}", access_token_sha256):
            raise HTTPException(503, "Structure inspection access is not configured")
        bearer = (authorization or "").removeprefix("Bearer ")
        actual = hashlib.sha256(bearer.encode()).hexdigest()
        if (
            not authorization
            or not authorization.startswith("Bearer ")
            or not hmac.compare_digest(actual, access_token_sha256)
        ):
            raise HTTPException(401, "A structure inspection access token is required")

    def record(body: StructureInspectionRequest, result: dict[str, Any]) -> dict[str, Any]:
        result["scope_statement"] = SCOPE
        digest = store.put_json(result)
        request_digest = store.put_json(body.model_dump(mode="json"))
        run_id = f"structure-inspection-{uuid.uuid4().hex}"
        ledger.create_run(
            run_id=run_id,
            idempotency_key=run_id,
            command_digest=request_digest,
            payload={"request_artifact_digest": request_digest},
            event_id=f"{run_id}:request",
        )
        ledger.append(
            run_id,
            "STRUCTURE_INSPECTION_RESULT",
            {"artifact_digest": digest, "status": result["status"]},
            expected_sequence=1,
            event_id=f"{run_id}:result",
        )
        return {
            **result,
            "artifact_digest": digest,
            "run_id": run_id,
            "ledger_intact": ledger.verify_chain(run_id).intact,
        }

    @app.get("/health")
    def health() -> dict[str, Any]:
        return {"status": "ok", "authentication_required": True, "live_provider_probe": False}

    @app.post("/structure", dependencies=[Depends(authorize)])
    def inspect_structure(body: StructureInspectionRequest) -> dict[str, Any]:
        if body.selected_mutation not in body.mutations:
            raise HTTPException(422, "Selected mutation must be in the scored candidate set")
        # Check transcribed positions before either service is contacted. Scope
        # refusals, including multi-mutants, still come from the stability engine.
        for candidate in body.mutations:
            for token in candidate.split(":"):
                match = re.fullmatch(
                    r"([ACDEFGHIKLMNPQRSTVWY])(\d+)([ACDEFGHIKLMNPQRSTVWY])", token
                )
                if not match:
                    raise HTTPException(422, "Invalid mutation notation")
                position = int(match[2])
                if not 1 <= position <= len(sequence):
                    raise HTTPException(
                        422,
                        {
                            "refused": True,
                            "triggers": [
                                {
                                    "code": "OUT_OF_RANGE",
                                    "position": position,
                                    "evidence": {"min": 1, "max": len(sequence)},
                                }
                            ],
                        },
                    )
                if sequence[position - 1] != match[1]:
                    raise HTTPException(
                        422, "Wild-type residue does not match the frozen structure"
                    )
        if not lock.acquire(blocking=False):
            raise HTTPException(409, "Another structure inspection is running; wait for its result")
        try:
            try:
                with httpx.Client(timeout=180, transport=scoring_transport) as client:
                    response = client.post(
                        scoring_url,
                        json={
                            "domain": body.domain,
                            "mutations": body.mutations,
                        },
                    )
                response.raise_for_status()
                report = response.json()
                if report["manifest_digest"] != manifest_digest:
                    raise ValueError("Manifest mismatch")
                if not isinstance(report["candidates"], list) or not isinstance(
                    report["refusals"], list
                ):
                    raise ValueError("Invalid report")
            except (httpx.HTTPError, KeyError, ValueError, TypeError) as exc:
                raise HTTPException(
                    502, "Stability service did not return a valid frozen report"
                ) from exc
            selected_id = f"1IGV.pdb_{body.selected_mutation}"
            accepted = any(
                row.get("candidate", {}).get("variant_id") == selected_id
                for row in report["candidates"]
            )
            refused = [row for row in report["refusals"] if row.get("variant_id") == selected_id]
            base = {
                "stability": report,
                "selected_mutation": body.selected_mutation,
                "provider": "NVIDIA",
                "model": "mit/boltz2",
            }
            if refused or not accepted or ":" in body.selected_mutation:
                if not refused:
                    count = len(body.selected_mutation.split(":"))
                    refused = [
                        {
                            "variant_id": selected_id,
                            "refused": True,
                            "triggers": [
                                {
                                    "code": "T3_MULTI_MUTANT_SINGLE_MODEL"
                                    if count > 1
                                    else "CANDIDATE_NOT_ACCEPTED",
                                    "evidence": {"mutation_count": count},
                                }
                            ],
                        }
                    ]
                return record(
                    body,
                    {
                        **base,
                        "status": "refused",
                        "structure": None,
                        "refusals": refused,
                        "hosted_call_made": False,
                    },
                )
            match = re.fullmatch(r"([A-Z])(\d+)([A-Z])", body.selected_mutation)
            assert match is not None
            index = int(match[2]) - 1
            mutant_sequence = sequence[:index] + match[3] + sequence[index + 1 :]
            try:
                result = gateway.predict(client_id="authenticated-owner", sequence=mutant_sequence)
            except RateLimitExceededError as exc:
                return record(
                    body,
                    {
                        **base,
                        "status": "rate_limited",
                        "structure": None,
                        "message": "Structure quota reached; scoring remains available",
                        "retry_after_seconds": exc.retry_after_seconds,
                    },
                )
            except (RuntimeError, httpx.HTTPError) as exc:
                limited = "HTTP 429" in str(exc)
                return record(
                    body,
                    {
                        **base,
                        "status": "rate_limited" if limited else "unavailable",
                        "structure": None,
                        "message": "NVIDIA structure call did not complete; no automatic retry",
                    },
                )
            return record(
                body, {**base, "status": "completed", "structure": result.model_dump(mode="json")}
            )
        finally:
            lock.release()

    return app
