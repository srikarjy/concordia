"""Cached uncertainty helpers must work without the optional ESM runtime."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def test_cached_evaluation_does_not_import_model_dependencies() -> None:
    root = Path(__file__).resolve().parents[2]
    script = """
import importlib.abc
import sys
class NoModelRuntime(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split('.')[0] in {'torch', 'transformers'}:
            raise ImportError('optional model dependency imported: ' + fullname)
sys.meta_path.insert(0, NoModelRuntime())
sys.path.insert(0, 'scripts')
import evaluate_tsuboyama_uncertainty
import evaluate_tsuboyama_predictor
assert evaluate_tsuboyama_predictor.mutate('ACD', 2, 'V') == 'AVD'
"""
    subprocess.run([sys.executable, "-c", script], cwd=root, check=True)
