"""Bounded live discovery probe for NVIDIA's documented healthcare NIM catalog.

This script never writes credentials or response bodies. It records only route,
status, latency, parsed-response state, retry-after, and a redacted first error.
It intentionally does not probe Vista3D without a genuine medical image input.
"""

from __future__ import annotations

import argparse
import json
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from concordia.runtime.secrets import nvidia_api_key

SEQUENCE = "SPEELKGIFEKYAAKEGDPNQLSKEELKLLLQTEFPSLLKGPSTLDELFEELDKNGDGEVSFEEFQVLVKKISQ"
DNA = "ATGGAGCTGCTGACCGACGAGTACCTGCGTAACTGGTACGACCTGAACTACGAGGACCTG"
ASPIRIN = "CC(=O)Oc1ccccc1C(=O)O"
PDB_PATH = Path("data/raw/tsuboyama_v2_230420/structures/AlphaFold_model_PDBs/1IGV.pdb")


def _boltz_polymer() -> dict[str, Any]:
    return {
        "id": "A",
        "molecule_type": "protein",
        "sequence": SEQUENCE,
        "msa": {
            "uniref90": {
                "a3m": {"alignment": f">seq1\n{SEQUENCE}", "format": "a3m"}
            }
        },
    }


def _routes() -> list[dict[str, Any]]:
    pdb = PDB_PATH.read_text(encoding="utf-8")
    return [
        {
            "name": "Evo2 generate",
            "endpoint": "https://health.api.nvidia.com/v1/biology/arc/evo2-40b/generate",
            "payload": {
                "sequence": DNA,
                "num_tokens": 4,
                "temperature": 0.7,
                "top_k": 3,
                "top_p": 0.0,
                "random_seed": 1729,
            },
        },
        {
            "name": "Evo2 forward",
            "endpoint": "https://health.api.nvidia.com/v1/biology/arc/evo2-7b/forward",
            "payload": {"sequence": DNA, "output_layers": ["output_layer"]},
        },
        {
            "name": "MSA Search",
            "endpoint": "https://health.api.nvidia.com/v1/biology/colabfold/msa-search/predict",
            "payload": {
                "sequence": SEQUENCE,
                "databases": ["Uniref30_2302"],
                "output_alignment_formats": ["a3m"],
            },
        },
        {
            "name": "AlphaFold2",
            "endpoint": "https://health.api.nvidia.com/v1/protein-structure/alphafold2/predict-structure-from-sequence",
            "payload": {"sequence": SEQUENCE},
        },
        {
            "name": "AlphaFold2 Multimer",
            "endpoint": "https://health.api.nvidia.com/v1/protein-structure/alphafold2/multimer/predict-structure-from-sequences",
            "payload": {"sequences": [SEQUENCE, "MKTAYIAKQRQISFVKSHFSRQLEERLGLIEVQ"]},
        },
        {
            "name": "ProteinMPNN",
            "endpoint": "https://health.api.nvidia.com/v1/biology/ipd/proteinmpnn/predict",
            "payload": {
                "input_pdb": pdb,
                "num_seq_per_target": 1,
                "sampling_temp": [0.1],
                "ca_only": False,
                "use_soluble_model": False,
                "random_seed": 1729,
            },
            "retries": 3,
        },
        {
            "name": "RFdiffusion",
            "endpoint": "https://health.api.nvidia.com/v1/biology/ipd/rfdiffusion/generate",
            "payload": {
                "input_pdb": pdb,
                "contigs": "A1-74/0 50-70",
                "diffusion_steps": 1,
                "random_seed": 1729,
            },
        },
        {
            "name": "Boltz-2",
            "endpoint": "https://health.api.nvidia.com/v1/biology/mit/boltz2/predict",
            "payload": {
                "polymers": [_boltz_polymer()],
                "diffusion_samples": 1,
                "sampling_steps": 20,
            },
        },
        {
            "name": "DiffDock",
            "endpoint": "https://health.api.nvidia.com/v1/molecular-docking/diffdock/generate",
            "payload": {
                "protein": pdb,
                "ligand": ASPIRIN,
                "ligand_file_type": "smiles",
                "num_poses": 1,
                "time_divisions": 1,
                "steps": 1,
                "save_trajectory": False,
                "skip_gen_conformer": False,
                "is_staged": False,
            },
        },
        {
            "name": "GenMol",
            "endpoint": "https://health.api.nvidia.com/v1/biology/nvidia/genmol/generate",
            "payload": {
                "smiles": ASPIRIN,
                "num_molecules": 1,
                "temperature": 1,
                "noise": 1,
                "step_size": 1,
                "scoring": "QED",
                "unique": True,
            },
        },
        {
            "name": "MolMIM",
            "endpoint": "https://health.api.nvidia.com/v1/biology/nvidia/molmim/generate",
            "payload": {
                "algorithm": "none",
                "smi": ASPIRIN,
                "num_molecules": 1,
                "iterations": 1,
                "property_name": "QED",
                "particles": 2,
                "minimize": False,
                "min_similarity": 0.7,
                "scaled_radius": 1,
            },
        },
        {
            "name": "Vista3D",
            "endpoint": "https://health.api.nvidia.com/v1/biology/nvidia/vista3d/infer",
            "payload": None,
            "untested_reason": (
                "requires a genuine medical image asset; no protein-compatible payload exists"
            ),
        },
        {
            "name": "OpenFold2",
            "endpoint": "https://health.api.nvidia.com/v1/biology/openfold/openfold2/predict-structure-from-msa-and-template",
            "payload": {"sequence": SEQUENCE, "input_id": "1IGV"},
        },
        {
            "name": "OpenFold3",
            "endpoint": "https://health.api.nvidia.com/v1/biology/openfold/openfold3/predict",
            "payload": {
                "request_id": "concordia-catalog-1igv",
                "inputs": [
                    {
                        "input_id": "1IGV",
                        "molecules": [
                            {
                                "type": "protein",
                                "id": "A",
                                "sequence": SEQUENCE,
                                "msa": {
                                    "main_db": {
                                        "csv": {
                                            "alignment": f"key,sequence\\n-1,{SEQUENCE}",
                                            "format": "csv",
                                        }
                                    }
                                },
                            }
                        ],
                        "output_format": "pdb",
                    }
                ],
            },
        },
    ]


def _classify(status: int | None, configured: bool = True) -> str:
    if not configured:
        return "unconfigured"
    if status == 200:
        return "healthy"
    if status == 429:
        return "rate_limited"
    if status is None:
        return "unavailable"
    return "unavailable"


def _probe(route: dict[str, Any], key: str) -> list[dict[str, Any]]:
    if route.get("payload") is None:
        return [
            {
                "route": route["name"],
                "endpoint": route["endpoint"],
                "state": "untested",
                "reason": route["untested_reason"],
            }
        ]
    results: list[dict[str, Any]] = []
    for attempt in range(int(route.get("retries", 1))):
        request = urllib.request.Request(
            route["endpoint"],
            data=json.dumps(route["payload"]).encode(),
            headers={
                "Authorization": f"Bearer {key}",
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
            method="POST",
        )
        started = time.perf_counter()
        status: int | None = None
        retry_after: str | None = None
        raw = b""
        try:
            with urllib.request.urlopen(request, timeout=180) as response:
                status = response.status
                retry_after = response.headers.get("Retry-After")
                raw = response.read()
        except urllib.error.HTTPError as error:
            status = error.code
            retry_after = error.headers.get("Retry-After")
            raw = error.read()
        except (urllib.error.URLError, TimeoutError) as error:
            raw = str(error).encode()
        latency = time.perf_counter() - started
        try:
            parsed = json.loads(raw)
            parsed_ok = isinstance(parsed, dict | list)
            first_error = parsed.get("error") if isinstance(parsed, dict) else None
        except (json.JSONDecodeError, UnicodeDecodeError):
            parsed_ok = False
            first_error = raw[:300].decode("utf-8", "replace")
        results.append(
            {
                "route": route["name"],
                "endpoint": route["endpoint"],
                "attempt": attempt + 1,
                "status": status,
                "latency_seconds": round(latency, 3),
                "parsed": parsed_ok,
                "first_error": str(first_error)[:300] if first_error else None,
                "retry_after": retry_after,
                "state": _classify(status),
            }
        )
        if attempt + 1 == int(route.get("retries", 1)):
            break
        time.sleep(2)
    return results


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--only", help="probe one catalog route by display name")
    args = parser.parse_args()
    key = nvidia_api_key(Path("."))
    if not key:
        raise SystemExit("NVIDIA_API_KEY is not configured")
    results: list[dict[str, Any]] = []
    routes = _routes()
    if args.only:
        routes = [route for route in routes if route["name"] == args.only]
    for route in routes:
        results.extend(_probe(route, key))
        if route is not routes[-1]:
            time.sleep(1)
    print(
        json.dumps(
            {
                "catalog_source": "NVIDIA Healthcare APIs",
                "credential_present": True,
                "results": results,
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
