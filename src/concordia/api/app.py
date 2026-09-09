"""Local-first HTTP control plane."""

from __future__ import annotations

import asyncio
import json
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from pathlib import Path

from fastapi import FastAPI, Header, HTTPException, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, ConfigDict

from concordia.events.sqlite import (
    ConcurrencyError,
    IdempotencyConflictError,
    RunNotFoundError,
)
from concordia.runtime.contracts import ArtifactReference, EventPage, ReplayResult, RunRecord
from concordia.runtime.service import ArtifactExecutionError, CreateRunRequest, RunService
from concordia.runtime.state_machine import TERMINAL_STATES, IllegalTransitionError
from concordia.scheduling.jobs import LeaseConflictError


class ErrorBody(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    code: str
    message: str
    request_id: str


def create_app(
    state_root: str | Path = Path(".concordia"), *, sse_poll_seconds: float = 0.25
) -> FastAPI:
    service = RunService.local(state_root)
    app = FastAPI(title="Concordia Colony", version="0.1.0")
    app.state.run_service = service

    @app.middleware("http")
    async def request_id_middleware(
        request: Request, call_next: Callable[[Request], Awaitable[JSONResponse]]
    ):
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

    @app.exception_handler(IllegalTransitionError)
    @app.exception_handler(LeaseConflictError)
    @app.exception_handler(ConcurrencyError)
    async def state_conflict(request: Request, error: Exception) -> JSONResponse:
        body = ErrorBody(
            code="RUN_STATE_CONFLICT",
            message=str(error),
            request_id=request.state.request_id,
        )
        return JSONResponse(status_code=409, content=body.model_dump(mode="json"))

    @app.exception_handler(ArtifactExecutionError)
    async def artifact_error(
        request: Request, error: ArtifactExecutionError
    ) -> JSONResponse:
        body = ErrorBody(
            code="ARTIFACT_INTEGRITY_ERROR",
            message=str(error),
            request_id=request.state.request_id,
        )
        return JSONResponse(status_code=409, content=body.model_dump(mode="json"))

    @app.exception_handler(RequestValidationError)
    async def validation_error(
        request: Request, error: RequestValidationError
    ) -> JSONResponse:
        body = ErrorBody(
            code="VALIDATION_ERROR",
            message="request validation failed",
            request_id=request.state.request_id,
        )
        return JSONResponse(status_code=422, content=body.model_dump(mode="json"))

    @app.exception_handler(HTTPException)
    async def http_error(request: Request, error: HTTPException) -> JSONResponse:
        body = ErrorBody(
            code="INVALID_REQUEST" if error.status_code < 500 else "SERVICE_UNAVAILABLE",
            message=str(error.detail),
            request_id=request.state.request_id,
        )
        return JSONResponse(status_code=error.status_code, content=body.model_dump(mode="json"))

    @app.post("/runs", response_model=RunRecord)
    def create_run(payload: CreateRunRequest) -> RunRecord:
        return service.create_scheduled(payload)

    @app.get("/runs/{run_id}", response_model=RunRecord)
    def get_run(run_id: str) -> RunRecord:
        return service.get_run(run_id)

    @app.post("/runs/{run_id}/replay", response_model=ReplayResult)
    def replay_run(run_id: str) -> ReplayResult:
        return service.replay(run_id)

    @app.post("/runs/{run_id}/cancel", response_model=RunRecord)
    def cancel_run(run_id: str) -> RunRecord:
        return service.cancel(run_id)

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

    @app.get("/runs/{run_id}/stream")
    async def stream_events(
        run_id: str,
        request: Request,
        last_event_id: str | None = Header(default=None, alias="Last-Event-ID"),
    ) -> StreamingResponse:
        try:
            after = int(last_event_id) if last_event_id else 0
        except ValueError as error:
            raise HTTPException(
                status_code=400, detail="Last-Event-ID must be an integer"
            ) from error
        service.get_run(run_id)

        async def event_source() -> AsyncIterator[str]:
            cursor = after
            while True:
                page = service.ledger.events(run_id, after=cursor, limit=100)
                if page.items:
                    for event in page.items:
                        cursor = event.sequence_number
                        data = json.dumps(event.model_dump(mode="json"), separators=(",", ":"))
                        yield f"id: {cursor}\nevent: {event.event_type}\ndata: {data}\n\n"
                record = service.get_run(run_id)
                if (
                    record.current_status in TERMINAL_STATES
                    and cursor >= record.last_sequence_number
                ):
                    return
                if await request.is_disconnected():
                    return
                if not page.items:
                    yield ": heartbeat\n\n"
                await asyncio.sleep(sse_poll_seconds)

        return StreamingResponse(event_source(), media_type="text/event-stream")

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
