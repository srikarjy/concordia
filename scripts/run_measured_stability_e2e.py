"""Run one auditable local-Qwen -> stability -> hosted-Boltz trace.

This script deliberately uses the already-frozen and cached stability artifacts.
It does not load ESM-2, access the holdout, or recompute any predictive metric.
"""

from __future__ import annotations

import json
import re
import resource
import time
import uuid
from pathlib import Path
from typing import Any, Literal

import httpx
from pydantic import BaseModel, ConfigDict

from concordia.events.sqlite import SQLiteEventLedger
from concordia.genomics.boltz_nvidia import NvidiaHostedBoltzRunner
from concordia.runtime.model_registry import MODEL_REGISTRY
from concordia.runtime.secrets import nvidia_api_key
from concordia.stability.measured import MeasuredCandidate, MeasuredStabilityEngine
from concordia.stability.nl_schema import (
    EXTRACTION_SYSTEM_PROMPT,
    extraction_schema,
    validate_extraction_response,
)
from concordia.storage.content import ContentAddressedStore

ROOT = Path(__file__).resolve().parents[1]
RUN_ROOT = ROOT / ".concordia" / "e2e-measured-stability"
OLLAMA_HOST = "http://127.0.0.1:11434"
OLLAMA_MODEL = "qwen3:1.7b"
UTTERANCE = (
    "Rank the frozen measured stability candidates, preserve all constraint refusals, "
    "and inspect only the top accepted candidate with the hosted protein structure tool."
)
CANDIDATE_IDS = (
    "1IGV.pdb_Q21E",
    "1IGV.pdb_D53E",
    "1IGV.pdb_K6Q",
    "1IGV.pdb_L52Y",
    "1E0L.pdb_T9Q:N23Q",
)


class TypedRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    intent: Literal[
        "stability_prediction",
        "structure_prediction",
        "constraint_inspection",
        "general_review",
    ]
    target: dict[str, Any]
    specificity: Literal["actionable", "underspecified"]
    utterance: str


def _sequence_from_pdb() -> str:
    from Bio.PDB import PDBParser  # type: ignore[attr-defined]

    pdb = ROOT / "data/raw/tsuboyama_v2_230420/structures/AlphaFold_model_PDBs/1IGV.pdb"
    structure = PDBParser(QUIET=True).get_structure(  # type: ignore[no-untyped-call]
        "1IGV", str(pdb)
    )[0]
    mapping = {
        "ALA": "A", "ARG": "R", "ASN": "N", "ASP": "D", "CYS": "C",
        "GLN": "Q", "GLU": "E", "GLY": "G", "HIS": "H", "ILE": "I",
        "LEU": "L", "LYS": "K", "MET": "M", "PHE": "F", "PRO": "P",
        "SER": "S", "THR": "T", "TRP": "W", "TYR": "Y", "VAL": "V",
    }
    return "".join(mapping[residue.resname] for residue in next(structure.get_chains()))


def _ollama_call(schema: dict[str, Any]) -> tuple[dict[str, Any], str, float, str]:
    started = time.perf_counter()
    payload = {
        "model": OLLAMA_MODEL,
        "stream": False,
        "think": False,
        "format": schema,
        "options": {"temperature": 0, "seed": 42, "num_predict": 128},
        "messages": [
            {
                "role": "system",
                "content": EXTRACTION_SYSTEM_PROMPT,
            },
            {"role": "user", "content": UTTERANCE},
        ],
    }
    response = httpx.post(f"{OLLAMA_HOST}/api/chat", json=payload, timeout=120.0)
    response.raise_for_status()
    outer = response.json()
    raw = str(outer.get("message", {}).get("content", ""))
    parsed = json.loads(raw)
    elapsed = time.perf_counter() - started
    return parsed, raw, elapsed, str(outer.get("model", OLLAMA_MODEL))


def _append(
    ledger: SQLiteEventLedger,
    run_id: str,
    sequence: int,
    event_type: str,
    payload: dict[str, Any],
) -> int:
    ledger.append(run_id, event_type, payload, expected_sequence=sequence)
    return sequence + 1


def _number_tokens(text: str) -> set[str]:
    return set(re.findall(r"(?<![A-Za-z])[0-9]+(?:\.[0-9]+)?", text))


def _rss_mb() -> float:
    value = float(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
    return value / (1024.0 * 1024.0) if __import__("sys").platform == "darwin" else value / 1024.0


def main() -> None:
    started = time.perf_counter()
    RUN_ROOT.mkdir(parents=True, exist_ok=True)
    ledger = SQLiteEventLedger(RUN_ROOT / "events.sqlite3")
    artifacts = ContentAddressedStore(RUN_ROOT / "artifacts")
    run_id = f"e2e-{uuid.uuid4().hex}"
    request_payload = {
        "utterance": UTTERANCE,
        "manifest": "ecaa921917627178638397955def230d9bc1563cc4122ac27a099e6f618f25d7",
    }
    ledger.create_run(
        run_id=run_id,
        idempotency_key=run_id,
        command_digest=__import__("hashlib")
        .sha256(json.dumps(request_payload, sort_keys=True).encode())
        .hexdigest(),
        payload=request_payload,
        event_id=f"{run_id}:created",
    )
    sequence = 1
    stages: dict[str, float] = {}
    rss: dict[str, float] = {"before": _rss_mb()}
    schema = extraction_schema()
    raw_response, raw_json, qwen_elapsed, qwen_model = _ollama_call(schema)
    validate_extraction_response(raw_response, schema, range(1, 75), utterance=UTTERANCE)
    typed = TypedRequest.model_validate({**raw_response, "utterance": UTTERANCE})
    stages["ollama_qwen"] = qwen_elapsed
    rss["after_ollama"] = _rss_mb()
    typed_json = typed.model_dump(mode="json")
    qwen_artifact = artifacts.put_json(
        {"raw_response": raw_json, "typed_request": typed_json}
    )
    sequence = _append(
        ledger, run_id, sequence, "QWEN_PARSED",
        {
            "utterance": UTTERANCE,
            "raw_qwen_json": raw_response,
            "typed_request": typed_json,
            "artifact_digest": qwen_artifact,
        },
    )

    local_started = time.perf_counter()
    engine = MeasuredStabilityEngine()
    candidates = []
    for variant_id in CANDIDATE_IDS:
        if variant_id == "1E0L.pdb_T9Q:N23Q":
            candidates.append(MeasuredCandidate(variant_id, 9, "Q", 2))
        elif (row := engine.rows.get(variant_id)) is not None:
            candidates.append(
                MeasuredCandidate(row.variant_id, row.position, row.mutant, row.mutation_count)
            )
    stability_report = engine.rank(candidates)
    stages["local_constraints_scoring_ranking"] = time.perf_counter() - local_started
    rss["after_local"] = _rss_mb()
    stability_artifact = artifacts.put_json(stability_report)
    sequence = _append(
        ledger, run_id, sequence, "STABILITY_RANKED",
        {
            "ranker": stability_report["ranker"],
            "report_artifact_digest": stability_artifact,
            "holdout_used": False,
        },
    )
    ranked = stability_report["candidates"]
    top = ranked[0]
    if top["refusal"]["refused"]:
        raise RuntimeError("top candidate was refused; hosted step must not run")

    hosted_started = time.perf_counter()
    key = nvidia_api_key(ROOT)
    if not key:
        raise RuntimeError("NVIDIA_API_KEY is required for the hosted step")
    boltz = NvidiaHostedBoltzRunner(artifacts, api_key=key, timeout_seconds=120)
    hosted_result = boltz.predict(_sequence_from_pdb(), sampling_steps=10)
    stages["hosted_boltz"] = time.perf_counter() - hosted_started
    hosted_payload = hosted_result.model_dump(mode="json")
    hosted_artifact = artifacts.put_json(hosted_payload)
    sequence = _append(
        ledger, run_id, sequence, "NVIDIA_HOSTED_CALLED",
        {
            "route": "boltz_monomer",
            "status_code": 200,
            "parsed": True,
            "artifact_digest": hosted_artifact,
            "response_artifact_digest": hosted_result.response_artifact_digest,
        },
    )

    selected = {
        "variant_id": top["candidate"]["variant_id"],
        "intent": raw_response["intent"],
        "specificity": raw_response["specificity"],
        "score": f"{top['mean_prediction_ddg_kcal_higher_is_more_stable']:.4f}",
        "sigma": f"{top['ensemble_sigma']:.4f}",
        "hosted_status": "parsed",
    }
    prose = (
        "Measured stability review for {variant_id}: intent {intent}, specificity {specificity}, "
        "score {score}, sigma {sigma}, hosted status {hosted_status}."
    ).format(**selected)
    allowed_numbers = {token for value in selected.values() for token in _number_tokens(str(value))}
    assert _number_tokens(prose) <= allowed_numbers
    rendered_artifact = artifacts.put_json({"prose": prose, "slots": selected})
    sequence = _append(
        ledger, run_id, sequence, "RECOMMENDATION_RENDERED",
        {"prose": prose, "slot_keys": sorted(selected), "artifact_digest": rendered_artifact},
    )
    trace = {
        "run_id": run_id,
        "utterance": UTTERANCE,
        "qwen": {
            "model": qwen_model,
            "raw_json": raw_response,
            "typed_request": typed_json,
            "artifact_digest": qwen_artifact,
        },
        "stability": {"artifact_digest": stability_artifact, "report": stability_report},
        "hosted": {
            "route": "boltz_monomer",
            "status_code": 200,
            "parsed": True,
            "artifact_digest": hosted_artifact,
            "response_artifact_digest": hosted_result.response_artifact_digest,
        },
        "rendered": {"prose": prose, "artifact_digest": rendered_artifact},
        "models": [dict(item) for item in MODEL_REGISTRY],
        "manifest_digest": engine.manifest_digest,
        "holdout_used": False,
        "wall_clock_seconds": time.perf_counter() - started,
        "stages_seconds": stages,
        "memory": {
            "process_peak_rss_mb": _rss_mb(),
            "rss_samples_mb": rss,
            "ollama_process_measured_separately": True,
            "esm2_loaded": False,
        },
        "scientific_use_allowed": False,
    }
    trace_artifact = artifacts.put_json(trace)
    _append(
        ledger,
        run_id,
        sequence,
        "TRACE_COMPLETED",
        {"final_artifact_digest": trace_artifact, "holdout_used": False},
    )
    print(
        json.dumps(
            {
                "trace": trace,
                "trace_artifact": trace_artifact,
                "ledger": [
                    event.model_dump(mode="json") for event in ledger.all_events(run_id)
                ],
                "chain": ledger.verify_chain(run_id).model_dump(mode="json"),
            },
            indent=2,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
