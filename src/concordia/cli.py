"""`concordia infer <image>` — run ConceptCLIP against a set of candidate
concepts and print the ranked scores (plus a saved heatmap for the top
concept, if the intrinsic Grad-CAM succeeds)."""

from __future__ import annotations

import sys

import click
import numpy as np
from PIL import Image


@click.group()
def main() -> None:
    pass


@main.command()
@click.argument("image_path", type=click.Path(exists=True, dir_okay=False))
@click.option(
    "--concept",
    "concepts",
    multiple=True,
    required=True,
    help="Candidate concept label. Repeat for multiple, e.g. "
    "--concept melanoma --concept nevus --concept seborrheic_keratosis",
)
@click.option("--top-k", default=3, show_default=True)
@click.option(
    "--heatmap-out",
    type=click.Path(dir_okay=False),
    default=None,
    help="If set, save the top concept's heatmap as a .npy array here.",
)
def infer(image_path: str, concepts: tuple[str, ...], top_k: int, heatmap_out: str | None) -> None:
    """Run zero-shot concept scoring on IMAGE_PATH."""
    from concordia.engine import ConceptClipEngine

    click.echo(f"Loading {ConceptClipEngine.__module__}.ConceptClipEngine ...", err=True)
    try:
        engine = ConceptClipEngine()
    except Exception as exc:  # noqa: BLE001
        click.echo(
            f"Failed to load ConceptCLIP: {exc}\n"
            "This model is gated on Hugging Face — confirm you've accepted "
            "the license at https://hf.co/JerrryNie/ConceptCLIP and set "
            "HF_TOKEN in your environment.",
            err=True,
        )
        sys.exit(1)

    image = Image.open(image_path).convert("RGB")

    if heatmap_out:
        pred = engine.predict_with_heatmaps(image, list(concepts), top_k=top_k, heatmap_top_n=1)
    else:
        pred = engine.predict(image, list(concepts), top_k=top_k)

    for rank, s in enumerate(pred.scores, start=1):
        click.echo(f"{rank}. {s.concept}: {s.score:.4f}")

    if heatmap_out:
        top = pred.top_concepts[0]
        heatmap = pred.heatmaps.get(top)
        if heatmap is not None:
            np.save(heatmap_out, heatmap)
            click.echo(f"Saved heatmap for '{top}' to {heatmap_out}", err=True)
        else:
            click.echo(f"Heatmap unavailable: {pred.heatmap_error}", err=True)


if __name__ == "__main__":
    main()
