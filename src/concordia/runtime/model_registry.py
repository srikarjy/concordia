"""Pinned local-model inventory and memory-loading policy."""

from __future__ import annotations

import gc
import platform
import resource
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from typing import Any

MODEL_REGISTRY: tuple[dict[str, Any], ...] = (
    {
        "name": "ThermoMPNN",
        "revision": "370f76ec62bd929f7425e311d8df04a0d094990f",
        "license": "MIT",
        "loading": "always_resident_local_cpu",
    },
    {
        "name": "PIPPack",
        "revision": "9aea0a201ced4b7fcaeee7619ece6d45fdc754ae",
        "license": "MIT",
        "loading": "artifact_export_only",
    },
    {
        "name": "ESM-2 650M",
        "revision": "08e4846e537177426273712802403f7ba8261b6c",
        "license": "MIT",
        "loading": "on_demand_then_freed",
    },
    {
        "name": "Qwen3 1.7B",
        "revision": "3d0b790534fe4b79525fc3692950408dca41171676ed7e21db57af5c65ef6ab6",
        "license": "Apache-2.0",
        "loading": "always_resident_local_ollama",
    },
    {
        "name": "OpenFold3 NIM",
        "revision": "1.0.0",
        "license": "NVIDIA Open Model License; Apache-2.0 underlying code",
        "loading": "hosted_on_demand",
        "commercial_use": True,
        "redistribution_notice": (
            "Licensed by NVIDIA Corporation under the NVIDIA Open Model License"
        ),
        "service_terms": "NVIDIA API Trial Terms of Service",
        "status": "live_smoke_test_passed; not used by the stability loop",
    },
    {
        "name": "Evo2 40B NIM",
        "revision": "arc/evo2-40b hosted catalog revision",
        "license": "NVIDIA Open Model License",
        "loading": "hosted_on_demand",
        "commercial_use": True,
        "service_terms": "NVIDIA API Trial Service Terms of Use",
        "status": "live_smoke_test_passed",
    },
    {
        "name": "MSA Search NIM",
        "revision": "colabfold/msa-search hosted catalog revision",
        "license": "MIT",
        "loading": "hosted_on_demand",
        "commercial_use": True,
        "service_terms": "NVIDIA API Trial Service Terms of Use",
        "status": "live_smoke_test_passed",
    },
    {
        "name": "ProteinMPNN NIM",
        "revision": "ipd/proteinmpnn hosted catalog revision",
        "license": "NVIDIA Community Model License; MIT additional information",
        "loading": "hosted_on_demand",
        "commercial_use": True,
        "service_terms": "NVIDIA API Trial Service Terms of Use",
        "status": "live_smoke_test_passed_3_of_3",
    },
    {
        "name": "RFdiffusion NIM",
        "revision": "ipd/rfdiffusion hosted catalog revision",
        "license": "NVIDIA Community Model License; BSD additional information",
        "loading": "hosted_on_demand",
        "commercial_use": True,
        "service_terms": "NVIDIA API Trial Service Terms of Use",
        "status": "live_smoke_test_passed",
    },
    {
        "name": "Boltz-2 NIM",
        "revision": "Boltz2 2.2.1 hosted catalog revision",
        "license": "NVIDIA Community Model License; MIT additional information",
        "loading": "hosted_on_demand",
        "commercial_use": True,
        "service_terms": "NVIDIA API Trial Service Terms of Use",
        "status": "live_smoke_test_passed",
    },
    {
        "name": "GenMol NIM",
        "revision": "NV-GenMol-89M-v2",
        "license": "NVIDIA Open Model License",
        "loading": "hosted_on_demand",
        "commercial_use": True,
        "service_terms": "NVIDIA API Trial Service Terms of Use",
        "status": "live_smoke_test_passed",
    },
    {
        "name": "MolMIM NIM",
        "revision": "nvidia/molmim hosted catalog revision",
        "license": "NVIDIA Community Model License",
        "loading": "hosted_on_demand",
        "commercial_use": "catalog indicates hosted use; verify deployment terms",
        "service_terms": "NVIDIA API Trial Service Terms of Use",
        "status": "live_smoke_test_passed",
    },
)


def resident_memory_mb() -> float:
    """Return this process's peak resident memory without exposing model data."""
    value = float(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
    if platform.system() == "Darwin":
        return value / (1024 * 1024)
    return value / 1024


def model_registry_report() -> dict[str, Any]:
    return {
        "models": [dict(item) for item in MODEL_REGISTRY],
        "memory": {
            "steady_state_process_max_rss_mb": round(resident_memory_mb(), 2),
            "measured_at": datetime.now(UTC).isoformat(),
            "method": "resource.getrusage(RUSAGE_SELF).ru_maxrss",
            "note": "Measurement is for the serving process; model loading is policy-pinned above.",
        },
    }


@contextmanager
def esm2_on_demand(checkpoint: str = "facebook/esm2_t33_650M_UR50D") -> Iterator[Any]:
    """Load ESM-2 for one extraction scope and release it before returning."""
    import torch
    from transformers import AutoModel, AutoTokenizer

    tokenizer = AutoTokenizer.from_pretrained(checkpoint)
    model = AutoModel.from_pretrained(checkpoint).eval()
    try:
        yield tokenizer, model
    finally:
        del model, tokenizer
        gc.collect()
        if torch.backends.mps.is_available():
            torch.mps.empty_cache()


__all__ = ["MODEL_REGISTRY", "esm2_on_demand", "model_registry_report", "resident_memory_mb"]
