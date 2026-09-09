"""Local-first HTTP control plane."""

from __future__ import annotations

import uuid
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict

from concordia.events.sqlite import (
    IdempotencyConflictError,
    RunNotFoundError,
)
from concordia.runtime.contracts import ArtifactReference, EventPage, ReplayResult, RunRecord
from concordia.runtime.service import CreateRunRequest, RunService


class ErrorBody(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    code: str
    message: str
    request_id: str


def create_app(state_root: str | Path = Path(".concordia")) -> FastAPI:
    service = RunService.local(state_root)
    app = FastAPI(title="Concordia Colony", version="0.1.0")
    app.state.run_service = service

    @app.middleware("http")
    async def request_id_middleware(request: Request, call_next):  # type: ignore[no-untyped-def]
        request_id = request.headers.get("X-Request-ID", str(uuid.uuid4()))
        request.state.request_id = request_id
        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        return response

    @app.exception_handler(RunNotFoundError)
    async def not_found(request: Request, error: RunNotFoundError) -> JSONResponse:
        body = ErrorBody(
            code="RUN_NOT_FOUND",
            message=f"run {error.args[0]} was not found",
            request_id=request.state.request_id,
        )
        return JSONResponse(status_code=404, content=body.model_dump(mode="json"))

    @app.exception_handler(IdempotencyConflictError)
    async def idempotency_conflict(
        request: Request, error: IdempotencyConflictError
    ) -> JSONResponse:
        body = ErrorBody(
            code="IDEMPOTENCY_CONFLICT",
            message=str(error),
            request_id=request.state.request_id,
        )
        return JSONResponse(status_code=409, content=body.model_dump(mode="json"))

    @app.post("/runs", response_model=RunRecord)
    def create_run(payload: CreateRunRequest) -> RunRecord:
        return service.create_and_execute(payload)

    @app.get("/runs/{run_id}", response_model=RunRecord)
    def get_run(run_id: str) -> RunRecord:
        return service.get_run(run_id)

    @app.post("/runs/{run_id}/replay", response_model=ReplayResult)
    def replay_run(run_id: str) -> ReplayResult:
        return service.replay(run_id)

    @app.get("/runs/{run_id}/events", response_model=EventPage)
    def get_events(
        run_id: str,
        cursor: int = Query(default=0, ge=0),
        limit: int = Query(default=100, ge=1, le=500),
    ) -> EventPage:
        return service.ledger.events(run_id, after=cursor, limit=limit)

    @app.get("/runs/{run_id}/artifacts", response_model=list[ArtifactReference])
    def get_artifacts(run_id: str) -> tuple[ArtifactReference, ...]:
        return service.artifact_references(run_id)

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/ready")
    def ready() -> dict[str, str]:
        try:
            service.ledger.ping()
        except Exception as error:
            raise HTTPException(status_code=503, detail="event ledger unavailable") from error
        return {"status": "ready"}

    return app


app = create_app()
