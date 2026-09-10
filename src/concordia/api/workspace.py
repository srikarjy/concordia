"""Read-only demonstration API and static scientific workspace host."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Awaitable, Callable
from copy import deepcopy
from pathlib import Path

from fastapi import FastAPI, Header, HTTPException, Query, Request
from fastapi.responses import Response, StreamingResponse
from fastapi.staticfiles import StaticFiles

from concordia.reporting.workspace import build_workspace

TOOL_PATHS = (
    "/api/workspace",
    "/api/artifacts",
    "/api/artifacts/{digest}",
    "/api/graph",
    "/api/events",
    "/api/report",
)


def _tool_manifest() -> dict[str, object]:
    return {
        "schema_version": 1,
        "name": "concordia-read-only-evidence-tools",
        "mode": "read_only_fixture",
        "openapi_url": "/api/tools/openapi.json",
        "privacy_policy_url": (
            "https://srikarjy025-concordia-colony.hf.space/privacy"
        ),
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
    }


def create_workspace_app(
    state_root: str | Path = ".concordia/workspace",
    frontend: str | Path = "frontend/dist",
) -> FastAPI:
    data = build_workspace(state_root)
    app = FastAPI(
        title="Concordia scientific workspace",
        description="Read-only access to a saved fixture-backed evidence workspace.",
        version="1.1.0",
    )

    @app.middleware("http")
    async def public_security_headers(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        return response

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
                    "This read-only demonstration does not provide accounts, set application "
                    "cookies, accept user sequences, or request API credentials.",
                    "",
                    "The application does not intentionally persist request parameters. Its "
                    "hosting provider may process standard connection and access-log metadata "
                    "under the provider's own privacy terms.",
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

    @app.get("/.well-known/concordia-tools.json", include_in_schema=False)
    @app.get("/api/tools", include_in_schema=False)
    def tool_manifest():
        return _tool_manifest()

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
