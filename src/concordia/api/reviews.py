"""Loopback-only routes for the local variant review workbench."""

from __future__ import annotations

import ipaddress
import json
from collections.abc import Callable
from importlib.resources import files
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response

from concordia.review.workflow import (
    ConflictError,
    DecisionInput,
    EvidenceInput,
    InputError,
    ReviewInput,
    ReviewStore,
    add_evidence,
    comparison_flags,
    csv_export,
    export_bundle,
    html_report,
    initial_review,
    set_decision,
)


def example_payload() -> Any:
    """Resolve the packaged example, with a source-checkout fallback for development."""
    packaged = files("concordia").joinpath("data/variant-review.json")
    if packaged.is_file():
        return json.loads(packaged.read_text(encoding="utf-8"))
    source = Path(__file__).resolve().parents[3] / "data/examples/variant-review.json"
    if source.is_file():
        return json.loads(source.read_text(encoding="utf-8"))
    raise HTTPException(503, "The bundled review example is missing; reinstall Concordia.")


def require_local(request: Request) -> None:
    try:
        peer_local = bool(request.client and ipaddress.ip_address(request.client.host).is_loopback)
    except ValueError:
        peer_local = False
    if not peer_local or request.url.hostname not in {"localhost", "127.0.0.1", "::1"}:
        raise HTTPException(403, "This review workspace is available only on localhost.")
    origin = request.headers.get("origin")
    if origin:
        parsed = urlsplit(origin)
        if parsed.scheme not in {"http", "https"} or parsed.netloc != request.url.netloc:
            raise HTTPException(403, "Cross-origin access to local reviews is not allowed.")


def review_router(root: Path) -> APIRouter:
    router = APIRouter(prefix="/api/reviews", dependencies=[Depends(require_local)])
    store = ReviewStore(root)

    def run(action: Callable[[], Any]) -> Any:
        try:
            return action()
        except InputError as exc:
            raise HTTPException(422, detail=exc.errors) from exc
        except ConflictError as exc:
            raise HTTPException(409, detail=str(exc)) from exc
        except KeyError as exc:
            raise HTTPException(404, detail="Review or revision not found.") from exc

    def display(review: dict[str, Any]) -> dict[str, Any]:
        return {
            "review": review,
            "flags": comparison_flags(review),
            "history": store.history(review["review_id"]),
        }

    @router.get("")
    def list_reviews() -> list[dict[str, Any]]:
        return store.list_reviews()

    @router.get("/example")
    def example() -> Any:
        return example_payload()

    @router.post("/preview")
    def preview(body: ReviewInput) -> Any:
        def action() -> Any:
            report = initial_review(body)
            return {
                "candidates": report["candidates"],
                "flags": comparison_flags(report),
                "predictions": report["predictions"],
            }

        return run(action)

    @router.post("")
    def create(body: ReviewInput) -> Any:
        return run(
            lambda: display(store.save(initial_review(body), 0, "Created from validated inputs"))
        )

    @router.get("/{review_id}")
    def load(review_id: str, revision: int | None = Query(default=None, ge=1)) -> Any:
        return run(lambda: display(store.load(review_id, revision)))

    @router.post("/{review_id}/decisions")
    def decision(review_id: str, body: DecisionInput) -> Any:
        def action() -> Any:
            review = store.load(review_id)
            set_decision(review, body)
            return display(
                store.save(
                    review,
                    body.expected_revision,
                    f"Decision: {body.candidate_id} → {body.decision}",
                )
            )

        return run(action)

    @router.post("/{review_id}/evidence")
    def evidence(review_id: str, body: EvidenceInput) -> Any:
        def action() -> Any:
            review = store.load(review_id)
            add_evidence(review, body)
            return display(
                store.save(review, body.expected_revision, f"Imported {body.kind}: {body.label}")
            )

        return run(action)

    @router.get("/{review_id}/export/{format}")
    def export(
        review_id: str, format: str, revision: int | None = Query(default=None, ge=1)
    ) -> Response:
        def action() -> Response:
            review = store.load(review_id, revision)
            stem = f"concordia-review-{review['review_id'][:8]}-r{review['revision']}"
            if format == "zip":
                history = [store.load(review_id, n) for n in range(1, review["revision"] + 1)]
                content, media, suffix = export_bundle(review, history), "application/zip", "zip"
            elif format in {"selected", "decisions"}:
                content, media, suffix = (
                    csv_export(review, format == "selected").encode(),
                    "text/csv",
                    "csv",
                )
                stem += "-" + format
            elif format == "html":
                content, media, suffix = html_report(review).encode(), "text/html", "html"
            else:
                raise HTTPException(404, "Unknown export format")
            return Response(
                content,
                media_type=media,
                headers={
                    "Content-Disposition": f'attachment; filename="{stem}.{suffix}"',
                    "Cache-Control": "no-store",
                },
            )

        return run(action)

    return router
