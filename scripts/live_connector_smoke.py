"""Make one bounded live connector call per hosted integration.

The report contains status, latency, schema validation, and exception type/message
only. Credentials and response bodies are deliberately never printed or stored.
"""

from __future__ import annotations

import json
import os
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from concordia.genomics.boltz_nvidia import (
    BoltzComplexRequest,
    BoltzPolymer,
    NvidiaHostedBoltzRunner,
)
from concordia.genomics.evo2_attribution import ZeroGpuEvo2AttributionRunner
from concordia.genomics.evo2_nvidia import NvidiaHostedEvo2GenerationRunner, NvidiaHostedEvo2Runner
from concordia.genomics.evo2_protocol import Evo2ScoringSemantics
from concordia.genomics.openfold2_nvidia import NvidiaHostedOpenFold2Runner
from concordia.genomics.proteinmpnn_nvidia import (
    NvidiaHostedProteinMpnnRunner,
    ProteinMpnnRequest,
)
from concordia.genomics.rfdiffusion_nvidia import NvidiaHostedRFdiffusionRunner, RFdiffusionRequest
from concordia.genomics.schema import GenomicSequence
from concordia.runtime.secrets import nvidia_api_key
from concordia.storage.content import ContentAddressedStore

ROOT = Path(__file__).resolve().parents[1]
EVO2_CHECKPOINT = (
    "arcinstitute/evo2_7b@bda0089f92582d5baabf0f22d9fc85f3588f6b58/evo2_7b.pt"
)
SEQUENCE = "MKTAYIAKQRQISFVKSHFSRQLEERLGLIEVQAPILSR"
SYNTHETIC_PDB = (
    "ATOM      1  N   ALA A   1       0.000   0.000   0.000  1.00 20.00           N  \n"
    "ATOM      2  CA  ALA A   1       1.458   0.000   0.000  1.00 20.00           C  \n"
    "ATOM      3  C   ALA A   1       2.058   1.410   0.000  1.00 20.00           C  \n"
    "ATOM      4  O   ALA A   1       1.300   2.420   0.000  1.00 20.00           O  \n"
    "TER\nEND\n"
)
RF_PDB_PATH = ROOT / "data/raw/tsuboyama_v2_230420/structures/AlphaFold_model_PDBs/1IGV.pdb"


def _call(name: str, fn: Callable[[], Any]) -> dict[str, Any]:
    started = time.perf_counter()
    try:
        result = fn()
        return {
            "route": name,
            "status": "completed",
            "latency_seconds": round(time.perf_counter() - started, 3),
            "parsed": True,
            "result_schema": type(result).__name__,
        }
    except Exception as error:  # noqa: BLE001 - smoke report records first failure
        return {
            "route": name,
            "status": "failed",
            "latency_seconds": round(time.perf_counter() - started, 3),
            "parsed": False,
            "first_failure": f"{type(error).__name__}: {error}",
        }


def main() -> None:
    key = nvidia_api_key(ROOT)
    if not key:
        raise SystemExit("NVIDIA credential is not configured")
    store = ContentAddressedStore(Path("/tmp/concordia-live-connector-artifacts"))
    reports: list[dict[str, Any]] = []
    generation = NvidiaHostedEvo2GenerationRunner(store, api_key=key, timeout_seconds=30)
    reports.append(
        _call(
            "evo2_generate",
            lambda: generation.generate(
                GenomicSequence(sequence_id="smoke", sequence="ACGT", strand="+")
            ),
        )
    )
    forward = NvidiaHostedEvo2Runner(store)
    reports.append(
        _call(
            "evo2_forward",
            lambda: forward.score(
                GenomicSequence(sequence_id="smoke", sequence="ACGT", strand="+"),
                checkpoint=EVO2_CHECKPOINT,
                target=forward.target,
            ),
        )
    )
    scoring = Evo2ScoringSemantics(
        target="mean_next_base_log_likelihood",
        tokenizer="CharLevelTokenizer-vocab-512",
        retained_score_artifacts=(
            "token_ids",
            "target_token_log_probabilities_float32",
            "sum_log_likelihood_float64",
            "mean_log_likelihood_float64",
        ),
    )
    space = os.environ.get("CONCORDIA_EVO2_FORWARD_SPACE_URL")
    if space:
        attribution = ZeroGpuEvo2AttributionRunner(store, space_url=space, scoring=scoring)
        reports.append(
            _call(
                "evo2_attribute",
                lambda: attribution.attribute(
                    GenomicSequence(sequence_id="smoke", sequence="A" * 8192, strand="+"),
                    checkpoint=EVO2_CHECKPOINT,
                    target="mean_next_base_log_likelihood",
                ),
            )
        )
    else:
        reports.append(
            {
                "route": "evo2_attribute",
                "status": "unavailable",
                "latency_seconds": 0.0,
                "parsed": False,
                "first_failure": "CONCORDIA_EVO2_FORWARD_SPACE_URL is unset",
            }
        )
    openfold = NvidiaHostedOpenFold2Runner(store, api_key=key, timeout_seconds=30)
    reports.append(_call("openfold2_predict", lambda: openfold.predict(SEQUENCE)))
    boltz = NvidiaHostedBoltzRunner(store, api_key=key, timeout_seconds=60)
    reports.append(_call("boltz_predict", lambda: boltz.predict(SEQUENCE, sampling_steps=10)))
    complex_request = BoltzComplexRequest(
        polymers=(BoltzPolymer(id="A", sequence=SEQUENCE), BoltzPolymer(id="B", sequence="ACDE")),
        sampling_steps=10,
    )
    complex_report = _call("boltz_complex", lambda: boltz.predict_complex(complex_request))
    reports.append(complex_report)
    if complex_report["status"] == "failed":
        time.sleep(2.0)
        retry = _call("boltz_complex_retry", lambda: boltz.predict_complex(complex_request))
        retry["retry_of"] = "boltz_complex"
        reports.append(retry)
    mpnn = NvidiaHostedProteinMpnnRunner(store, api_key=key, timeout_seconds=30)
    reports.append(
        _call(
            "proteinmpnn",
            lambda: mpnn.design(
                ProteinMpnnRequest(input_pdb=SYNTHETIC_PDB, num_sequences=1)
            ),
        )
    )
    rfdiffusion = NvidiaHostedRFdiffusionRunner(store, api_key=key, timeout_seconds=30)
    reports.append(
        _call(
            "rfdiffusion",
            lambda: rfdiffusion.generate(
                RFdiffusionRequest(
                    target_pdb=RF_PDB_PATH.read_text(encoding="utf-8"),
                    contigs="A1-74/0 50-100",
                    diffusion_steps=1,
                )
            ),
        )
    )
    print(json.dumps({"routes": reports}, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
