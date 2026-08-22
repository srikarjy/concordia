"""Smoke test for the ConceptCLIP engine.

Skips automatically when the gated model isn't reachable (no HF_TOKEN, no
license acceptance, or no network) rather than failing CI on an
environment precondition outside the code's control.
"""

import os

import pytest
from PIL import Image

pytestmark = pytest.mark.skipif(
    not os.environ.get("HF_TOKEN"),
    reason="ConceptCLIP is gated; set HF_TOKEN to run this test",
)


@pytest.fixture(scope="module")
def engine():
    from concordia.engine import ConceptClipEngine

    try:
        return ConceptClipEngine()
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"ConceptCLIP unavailable: {exc}")


def test_predict_returns_ranked_scores(engine):
    image = Image.new("RGB", (224, 224), color=(128, 96, 96))
    pred = engine.predict(image, ["melanoma", "nevus", "seborrheic keratosis"], top_k=2)

    assert len(pred.scores) == 2
    assert pred.scores[0].score >= pred.scores[1].score
    assert all(0.0 <= s.score <= 1.0 for s in pred.scores)


def test_predict_rejects_empty_concepts(engine):
    image = Image.new("RGB", (224, 224))
    with pytest.raises(ValueError):
        engine.predict(image, [])
