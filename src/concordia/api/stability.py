"""Local HTTP adapter for the frozen stability benchmark; no provider calls."""

from __future__ import annotations

from pathlib import Path
from threading import Lock
from typing import TYPE_CHECKING, Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field

if TYPE_CHECKING:
    # Imported lazily: the hosted Space image omits the scientific stack.
    from concordia.stability.measured import MeasuredStabilityEngine


class LocalScoreRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    domain: str = "1IGV"
    mutations: list[str] = Field(min_length=1, max_length=100)


def stability_router(state_root: Path) -> APIRouter:
    router = APIRouter(prefix="/api/stability")
    engine: MeasuredStabilityEngine | None = None
    lock = Lock()

    @router.post("/score")
    def score(body: LocalScoreRequest) -> dict[str, Any]:
        nonlocal engine
        from concordia.stability.measured import MeasuredStabilityEngine
        from concordia.stability.request import TypedStabilityRequest, run_typed_request

        try:
            request = TypedStabilityRequest.from_cli(body.domain, ",".join(body.mutations))
            with lock:
                if engine is None:
                    engine = MeasuredStabilityEngine()
                return run_typed_request(request, state_root=state_root, engine=engine)
        except FileNotFoundError as exc:
            raise HTTPException(
                status_code=503,
                detail=(
                    "Local stability artifacts are unavailable. "
                    "Start the server from the repository root."
                ),
            ) from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    return router
