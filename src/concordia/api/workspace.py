"""Read-only demonstration API and static scientific workspace host."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

from fastapi import FastAPI, Header, HTTPException, Query
from fastapi.responses import Response, StreamingResponse
from fastapi.staticfiles import StaticFiles

from concordia.reporting.workspace import build_workspace


def create_workspace_app(
    state_root: str | Path = ".concordia/workspace",
    frontend: str | Path = "frontend/dist",
) -> FastAPI:
    data = build_workspace(state_root)
    app = FastAPI(title="Concordia scientific workspace", version="1.0.0")

    @app.get("/health")
    def health():
        return {"status": "ok", "mode": "read_only_fixture", "schema_version": 1}

    @app.get("/ready")
    def ready():
        return {"status": "ready", "snapshot_digest": data["snapshot_digest"]}

    @app.get("/api/workspace")
    def workspace():
        return {key: value for key, value in data.items() if key != "artifacts"}

    @app.get("/api/artifacts")
    def artifacts():
        return [
            {"digest": digest, "media_type": "application/json", "schema_version": 1}
            for digest in data["artifacts"]
        ]

    @app.get("/api/artifacts/{digest}")
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

    @app.get("/api/graph")
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

    @app.get("/api/events")
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

    @app.get("/api/report")
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

    if Path(frontend).is_dir():
        app.mount("/", StaticFiles(directory=frontend, html=True), name="workspace")
    return app
