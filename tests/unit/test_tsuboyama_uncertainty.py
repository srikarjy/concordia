from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[2] / "scripts"))

from evaluate_tsuboyama_baselines import Variant
from evaluate_tsuboyama_uncertainty import compute_holdout_refusal_rate


def test_holdout_refusal_rate_uses_existing_refusal_gate() -> None:
    variants = [
        Variant("seen", 4, "A", 0.0),
        Variant("unseen", 9, "V", 0.0),
    ]

    rate, counts = compute_holdout_refusal_rate(variants, {4})

    assert rate == 0.5
    assert counts == {"refused": 1, "evaluated": 2}
