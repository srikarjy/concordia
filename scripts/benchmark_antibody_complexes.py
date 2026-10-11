"""Post-cutoff antibody-antigen benchmark for the hosted Boltz-2 integration.

Reads a pre-registered selection file, predicts each complex through a Concordia
workspace's /nvidia/boltz/complex endpoint, scores the prediction against the
experimental structure, and writes a report that includes every failure.

Run (needs biopython and numpy, which are not project dependencies):

    uv run --no-project --with biopython --with numpy \
        python scripts/benchmark_antibody_complexes.py SELECTION.json WORKDIR \
        --base-url https://srikarjy025-concordia-colony.hf.space

The run is resumable: finished complexes in WORKDIR are skipped. When the
endpoint's per-client limit is hit, the script waits for Retry-After instead of
working around it.

Success criterion, fixed before any result was seen:
    antigen CA RMSD in the antibody frame <= 5 A  AND  interface recall >= 0.5
"""

from __future__ import annotations

import argparse
import json
import time
import urllib.error
import urllib.request
from pathlib import Path

import numpy as np
from Bio import Align
from Bio.PDB import MMCIFParser
from Bio.PDB.Polypeptide import index_to_one, three_to_index

RMSD_MAX = 5.0
RECALL_MIN = 0.5
CONTACT_ANGSTROM = 8.0


def _post(url: str, body: dict, timeout: int = 480) -> tuple[int, dict, dict]:
    request = urllib.request.Request(
        url, data=json.dumps(body).encode(), headers={"content-type": "application/json"}
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.status, json.load(response), dict(response.headers)
    except urllib.error.HTTPError as error:
        raw = error.read() or b"{}"
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            payload = {"detail": raw[:300].decode(errors="replace")}
        return error.code, payload, dict(error.headers)


def _ca_residues(model) -> dict[str, list]:
    return {
        chain.id: [r for r in chain if r.id[0] == " " and "CA" in r] for chain in model
    }


def _one_letter(residues) -> str:
    out = ""
    for residue in residues:
        try:
            out += index_to_one(three_to_index(residue.get_resname()))
        except Exception:  # noqa: BLE001 - unknown residue becomes X
            out += "X"
    return out


def _aligner() -> Align.PairwiseAligner:
    aligner = Align.PairwiseAligner()
    aligner.mode = "global"
    aligner.match_score, aligner.mismatch_score = 2, -1
    aligner.open_gap_score, aligner.extend_gap_score = -3, -0.5
    return aligner


def _matched(aligner, predicted: list, observed: list) -> tuple[list, list]:
    alignment = aligner.align(_one_letter(predicted), _one_letter(observed))[0]
    left, right = [], []
    for (s1, e1), (s2, e2) in zip(*alignment.aligned, strict=True):
        for i, j in zip(range(s1, e1), range(s2, e2), strict=True):
            left.append(predicted[i])
            right.append(observed[j])
    return left, right


def _coords(residues) -> np.ndarray:
    return np.array([r["CA"].coord for r in residues])


def _kabsch(p: np.ndarray, q: np.ndarray):
    pc, qc = p.mean(0), q.mean(0)
    u, _, vt = np.linalg.svd((p - pc).T @ (q - qc))
    d = np.sign(np.linalg.det(vt.T @ u.T))
    return vt.T @ np.diag([1, 1, d]) @ u.T, pc, qc


def _rmsd(p: np.ndarray, q: np.ndarray) -> float:
    return float(np.sqrt(((p - q) ** 2).sum(1).mean()))


def score(pred_cif: Path, crystal_cif: Path, auth_chains: dict[str, str]) -> dict:
    parser = MMCIFParser(QUIET=True)
    predicted = _ca_residues(parser.get_structure("p", str(pred_cif))[0])
    observed = _ca_residues(parser.get_structure("x", str(crystal_cif))[0])
    # Boltz relabels output chains A, B, C in input order (H, L, antigen).
    predicted = {"H": predicted["A"], "L": predicted["B"], "A": predicted["C"]}
    aligner = _aligner()
    pairs = {k: _matched(aligner, predicted[k], observed[auth_chains[k]]) for k in "HLA"}
    result: dict = {"aligned_residues": {k: len(v[0]) for k, v in pairs.items()}}
    for key, (a, b) in pairs.items():
        rot, pc, qc = _kabsch(_coords(a), _coords(b))
        result[f"{key}_rmsd_ca"] = round(_rmsd((_coords(a) - pc) @ rot.T + qc, _coords(b)), 2)
    p_ab = np.vstack([_coords(pairs["H"][0]), _coords(pairs["L"][0])])
    q_ab = np.vstack([_coords(pairs["H"][1]), _coords(pairs["L"][1])])
    rot, pc, qc = _kabsch(p_ab, q_ab)
    result["antibody_rmsd_ca"] = round(_rmsd((p_ab - pc) @ rot.T + qc, q_ab), 2)
    antigen = (_coords(pairs["A"][0]) - pc) @ rot.T + qc
    result["antigen_rmsd_in_antibody_frame_ca"] = round(_rmsd(antigen, _coords(pairs["A"][1])), 2)

    def contacts(which: int) -> set:
        found = set()
        for chain in "HL":
            for i, ra in enumerate(pairs[chain][which]):
                for j, rb in enumerate(pairs["A"][which]):
                    if np.linalg.norm(ra["CA"].coord - rb["CA"].coord) < CONTACT_ANGSTROM:
                        found.add((chain, i, j))
        return found

    crystal, model = contacts(1), contacts(0)
    hits = len(crystal & model)
    result["interface_pairs_crystal"] = len(crystal)
    result["interface_pairs_predicted"] = len(model)
    result["interface_precision"] = round(hits / max(1, len(model)), 3)
    result["interface_recall"] = round(hits / max(1, len(crystal)), 3)
    return result


def verdict(scores: dict) -> str:
    ok = (
        scores["antigen_rmsd_in_antibody_frame_ca"] <= RMSD_MAX
        and scores["interface_recall"] >= RECALL_MIN
    )
    return "success" if ok else "failure"


def run(selection_path: Path, workdir: Path, base_url: str) -> dict:
    selection = json.loads(selection_path.read_text())
    workdir.mkdir(parents=True, exist_ok=True)
    rows = []
    for entry in selection["complexes"]:
        pdb = entry["pdb_id"]
        done = workdir / f"{pdb}.result.json"
        if done.exists():
            rows.append(json.loads(done.read_text()))
            print(f"{pdb}: cached ({rows[-1]['verdict']})", flush=True)
            continue
        crystal = workdir / f"{pdb}.crystal.cif"
        if not crystal.exists():
            with urllib.request.urlopen(f"https://files.rcsb.org/download/{pdb}.cif") as r:
                crystal.write_bytes(r.read())
        body = {
            "polymers": [
                {"id": key, "molecule_type": "protein", "sequence": entry["sequences"][key]}
                for key in ("H", "L", "A")
            ]
        }
        row = {k: entry[k] for k in ("pdb_id", "released", "method", "resolution", "antigen_desc")}
        row["lengths"] = {k: len(v) for k, v in entry["sequences"].items()}
        while True:
            started = time.time()
            status, payload, headers = _post(base_url + "/nvidia/boltz/complex", body)
            if status == 429:
                wait = int(headers.get("Retry-After", payload.get("retry_after", 3600))) + 30
                print(f"{pdb}: rate limited, waiting {wait}s", flush=True)
                time.sleep(wait)
                continue
            break
        row["http_status"] = status
        row["wall_seconds"] = round(time.time() - started, 1)
        if status == 200:
            pred = workdir / f"{pdb}.pred.cif"
            pred.write_text(payload["structure_text"])
            row["model_confidence"] = payload["confidence_scores"][0] if payload["confidence_scores"] else None
            row["input_payload_hash"] = payload["input_payload_hash"]
            row["response_artifact_digest"] = payload["response_artifact_digest"]
            try:
                row["scores"] = score(pred, crystal, entry["auth_chains"])
                row["verdict"] = verdict(row["scores"])
            except Exception as error:  # noqa: BLE001 - scoring failure is reported, not hidden
                row["verdict"] = "scoring_error"
                row["error"] = f"{type(error).__name__}: {error}"[:300]
        else:
            row["verdict"] = "prediction_error"
            row["error"] = str(payload.get("detail", payload))[:300]
        done.write_text(json.dumps(row))
        rows.append(row)
        print(f"{pdb}: {row['verdict']}", flush=True)
    wins = sum(r["verdict"] == "success" for r in rows)
    return {
        "selection_rule": selection["selection_rule"],
        "success_criterion": {
            "antigen_rmsd_in_antibody_frame_ca_max": RMSD_MAX,
            "interface_recall_min": RECALL_MIN,
            "fixed_before_results": True,
        },
        "results": rows,
        "summary": {"n": len(rows), "success": wins, "failure": len(rows) - wins},
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("selection", type=Path)
    parser.add_argument("workdir", type=Path)
    parser.add_argument("--base-url", default="https://srikarjy025-concordia-colony.hf.space")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    report = run(args.selection, args.workdir, args.base_url.rstrip("/"))
    out = args.output or args.workdir / "report.json"
    out.write_text(json.dumps(report, indent=2))
    print(json.dumps(report["summary"]))


if __name__ == "__main__":
    main()
