"""Execute a measured-data CPU baseline and real local HTTP review workflow.

Inputs: Zenodo 7992926 Figure 1 table and RCSB 1PGA FASTA. No hosted inference.
Decisions are scripted demonstrations, never researcher or biological validation.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import html
import io
import json
import re
import subprocess
import sys
import tempfile
import time
import urllib.request
import zipfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import httpx
import numpy as np
import sklearn
from scipy.stats import spearmanr
from sklearn.linear_model import Ridge

from concordia.review.workflow import export_bundle

ROOT = Path(__file__).resolve().parents[1]
DATA_URL = "https://zenodo.org/records/7992926/files/Data_tables_for_figs.zip?download=1"
FASTA_URL = "https://www.rcsb.org/fasta/entry/1PGA/display"
DATA_SHA = "69f6d5a68ba961759879ab60b3f168b8fad1bce0b0b810ac490fe85001515890"
FASTA_SHA = "a56ce69e9e80a566367b6b4b3a01a263d61e9b5c58dd55e9eb8e49a50bd6b561"
MEMBER = "Data_tables_for_figs/dG_extdG_data_Fig1.csv"
AA = "ACDEFGHIKLMNPQRSTVWY"


def csv_text(header: list[str], rows: list[list[Any]]) -> str:
    stream = io.StringIO()
    writer = csv.writer(stream)
    writer.writerow(header)
    writer.writerows(rows)
    return stream.getvalue()


def checked_input(path: Path, url: str, digest: str, fetch: bool) -> bytes:
    if fetch:
        with urllib.request.urlopen(url, timeout=120) as response:
            raw = response.read(30_000_001)
        if len(raw) > 30_000_000:
            raise ValueError("Public input exceeded 30 MB bound")
        if hashlib.sha256(raw).hexdigest() != digest:
            raise ValueError(f"Downloaded input changed: {url}")
        path.write_bytes(raw)
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != digest:
        raise ValueError(f"Input checksum mismatch: {path.name}")
    return raw


def measured_rows(raw: bytes, reference: str) -> list[dict[str, Any]]:
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        table = archive.read(MEMBER).decode()
    rows = []
    for row in csv.DictReader(io.StringIO(table)):
        if row["PDB_ID"] != "1PGA":
            continue
        match = re.fullmatch(r"1PGA.pdb_([A-Z])(\d+)([A-Z])", row["name"])
        if match is None:
            raise ValueError("Unexpected 1PGA mutation identity")
        wt, pos_text, alt = match.groups()
        pos = int(pos_text)
        if not 1 <= pos <= len(reference) or reference[pos - 1] != wt or wt == alt:
            raise ValueError("Mutation does not map to RCSB reference")
        sequence = reference[:pos - 1] + alt + reference[pos:]
        # The experimental construct has eight-residue flanks on both ends.
        if row["aa_seq"] != "SAGGSAGG" + sequence + "SAGGSAGG":
            raise ValueError("Experimental construct differs beyond the named mutation")
        value = float(row["deltaG"])
        if not np.isfinite(value):
            raise ValueError("Nonfinite experimental value")
        rows.append({"id": f"{wt}{pos}{alt}", "position": pos, "sequence": sequence,
                     "value": value, "pubmed_id": row["Pubmed_ID"]})
    if len(rows) != 930 or len({r["sequence"] for r in rows}) != len(rows):
        raise ValueError("Expected 930 unique measured single mutants")
    return sorted(rows, key=lambda row: row["id"])


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fetch", action="store_true", help="Download both pinned public inputs")
    parser.add_argument("--base-url", default="http://127.0.0.1:7860")
    args = parser.parse_args()
    if urlsplit(args.base_url).hostname not in {"127.0.0.1", "localhost"}:
        parser.error("The workflow must run against a local server")
    started = time.perf_counter()
    cache = ROOT / ".concordia/public-data-run"
    cache.mkdir(parents=True, exist_ok=True)
    raw = checked_input(cache / "Data_tables_for_figs.zip", DATA_URL, DATA_SHA, args.fetch)
    fasta = checked_input(cache / "1PGA.fasta", FASTA_URL, FASTA_SHA, args.fetch)
    reference = "".join(line for line in fasta.decode().splitlines() if not line.startswith(">"))
    rows = measured_rows(raw, reference)
    train = [r for r in rows if r["position"] % 5 != 0]
    test = [r for r in rows if r["position"] % 5 == 0]
    # Fixed split/alpha, no tuning on evaluation labels. One protein only.
    def features(items: list[dict[str, Any]]) -> np.ndarray[Any, Any]:
        return np.array([[r["sequence"].count(aa) for aa in AA] for r in items], dtype=float)

    model = Ridge(alpha=1.0, solver="svd").fit(features(train), [r["value"] for r in train])
    predictions = model.predict(features(test))
    baseline = float(np.mean([r["value"] for r in train]))
    review_id = hashlib.sha256(
        f"{DATA_SHA}:{FASTA_SHA}:ridge-aa-counts-alpha-1-posmod5-review-top-middle-low-v2".encode()
    ).hexdigest()[:32]
    # Keep the interactive queue legible; evaluate metrics on the full held-out set.
    ordered = sorted(range(len(test)), key=lambda i: (-predictions[i], test[i]["id"]))
    example_indexes = [ordered[0], ordered[len(test) // 2], ordered[-1]]
    review_rows = [test[i] for i in example_indexes]
    review_predictions = [predictions[i] for i in example_indexes]
    training_record = {
        "model": "CPU amino-acid-count Ridge", "alpha": 1.0, "solver": "svd",
        "feature_order": AA, "coefficients": model.coef_.tolist(),
        "intercept": float(model.intercept_), "train_mean": baseline,
        "train_ids": [r["id"] for r in train], "test_ids": [r["id"] for r in test],
        "split": "hold out every mutation position divisible by 5; no tuning",
        "target": "Published deltaG, kcal/mol, higher is more stable; NOT delta-delta-G",
        "source_url": DATA_URL, "source_sha256": DATA_SHA, "member": MEMBER,
        "reference_url": FASTA_URL, "reference_sha256": FASTA_SHA,
        "mapping": "RCSB 56-residue core; exactly SAGGSAGG flanks removed from each construct",
        "scientific_use_allowed": False,
        "software": {"python": sys.version.split()[0], "numpy": np.__version__,
                     "scikit_learn": sklearn.__version__},
    }
    with httpx.Client(base_url=args.base_url, timeout=30) as client:
        def api(method: str, path: str, body: Any = None) -> Any:
            response = client.request(method, path, json=body)
            response.raise_for_status()
            return response.json()

        payload = {
            "title": "1PGA · freshly executed measured-data baseline review",
            "objective": "Retrospective software demonstration using public measured stability. "
                         "CPU Ridge predictions on held-out positions; scripted decisions, "
                         "not a prospective experiment or validated recommendation. This "
                         "small review shows top, middle, and bottom predicted examples; "
                         "metrics below cover all 185 held-out variants.",
            "reference_sequence": reference,
            "candidates_csv": csv_text(["candidate_id", "mutations"],
                                       [[r["id"], r["id"]] for r in review_rows]),
            "predictions_csv": csv_text(
                ["candidate_id", "source", "metric", "value", "unit", "direction"],
                [[r["id"], "Fresh CPU Ridge", "folding_deltaG", float(value),
                  "kcal/mol", "higher"]
                 for r, value in zip(review_rows, review_predictions, strict=True)]),
        }
        # Select/defer/exclude based only on predicted order, before assay import.
        examples = list(zip(range(3), ["selected", "deferred", "excluded"], strict=True))
        path = f"/api/reviews/{review_id}"
        existing = client.get(path)
        created = existing.status_code == 404
        if created:
            review = api("POST", f"/api/reviews?review_id={review_id}", payload)["review"]
            for index, decision in examples:
                review = api("POST", path + "/decisions", {
                    "expected_revision": review["revision"],
                    "candidate_id": review_rows[index]["id"],
                    "decision": decision, "reason": "Scripted workflow demonstration based "
                    "only on predicted order; not a researcher recommendation.",
                })["review"]
        elif existing.is_success:
            review = existing.json()["review"]
            expected_candidates = [r["id"] for r in review_rows]
            if (review["title"] != payload["title"]
                    or review["reference_sha256"] != hashlib.sha256(reference.encode()).hexdigest()
                    or [c["candidate_id"] for c in review["candidates"]] != expected_candidates
                    or len(review["assays"]) != 1 or review["revision"] != 5):
                raise ValueError("Stable demo review exists but differs; refusing to overwrite it")
        else:
            existing.raise_for_status()
        before = {c["candidate_id"]: c["decision"] for c in review["candidates"]}
        assay = csv_text(["candidate_id", "metric", "value", "unit", "method", "status",
                          "replicate"], [[r["id"], "folding_deltaG", r["value"], "kcal/mol",
                                          "Tsuboyama proteolysis-derived estimate", "measured", 1]
                                         for r in review_rows])
        if created:
            review = api("POST", path + "/evidence", {
                "expected_revision": review["revision"], "kind": "assay", "csv_text": assay,
                "label": "Published Figure 1 measurements",
                "context": f"Tsuboyama v2_230420 {MEMBER}; archive SHA256 {DATA_SHA}. "
                           "Retrospective estimates, not independent wet-lab replicates.",
            })["review"]
        if review["assays"][0]["decisions_at_import"] != before:
            raise ValueError("Pre-import decisions were not preserved")
        history = [api("GET", path + f"?revision={n}")["review"]
                   for n in range(1, review["revision"] + 1)]
        response = client.get(path + "/export/zip")
        response.raise_for_status()
        with tempfile.TemporaryDirectory() as temporary:
            with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
                archive.extractall(temporary)
            subprocess.run([sys.executable, "-I", "verify.py"], cwd=temporary, check=True)

    y = np.array([r["value"] for r in test])
    report = {
        "status": "executed", "created_at": datetime.now(UTC).isoformat(),
        "dataset_rows": len(rows), "train_rows": len(train), "test_rows": len(test),
        "train_positions": sorted({r["position"] for r in train}),
        "test_positions": sorted({r["position"] for r in test}),
        "ridge_rmse": float(np.sqrt(np.mean((predictions - y) ** 2))),
        "mean_baseline_rmse": float(np.sqrt(np.mean((baseline - y) ** 2))),
        "ridge_mae": float(np.mean(np.abs(predictions - y))),
        "ridge_spearman": float(spearmanr(predictions, y).statistic),
        "review_revision": review["revision"], "decisions_preserved": True,
        "scripted_decisions": {review_rows[i]["id"]: decision for i, decision in examples},
        "interactive_review_candidate_ids": [r["id"] for r in review_rows],
        "interactive_review_count": len(review_rows),
        "elapsed_seconds": time.perf_counter() - started,
        "limitations": ["One retrospective protein and one fixed position split; no tuning.",
                        "No independent protein holdout, uncertainty or biological validation.",
                        "Published absolute folding deltaG; no new experimental measurements.",
                        "Fresh small baseline only; ThermoMPNN and attribution remain unexecuted."],
        "scientific_use_allowed": False, "training": training_record,
    }
    output = ROOT / "frontend/public/public-data-review"
    output.mkdir(parents=True, exist_ok=True)
    report_bytes = json.dumps(report, indent=2, allow_nan=False).encode()
    dataset = csv_text(["candidate_id", "sequence", "position", "deltaG_kcal_mol", "split"],
                       [[r["id"], r["sequence"], r["position"], r["value"],
                         "test" if r["position"] % 5 == 0 else "train"] for r in rows]).encode()
    bundle = export_bundle(review, history, diagnostic_artifacts={
        "execution.json": report_bytes, "measured-dataset.csv": dataset,
        "source-reference.fasta": fasta,
    })
    (output / "bundle.zip").write_bytes(bundle)
    (output / "execution.json").write_bytes(report_bytes)
    (output / "measured-dataset.csv").write_bytes(dataset)
    (output / "bundle.zip.sha256").write_text(hashlib.sha256(bundle).hexdigest() + "\n")
    with tempfile.TemporaryDirectory() as temporary:
        with zipfile.ZipFile(io.BytesIO(bundle)) as archive:
            archive.extractall(temporary)
            (output / "review.html").write_bytes(archive.read("report.html"))
        subprocess.run([sys.executable, "-I", "verify.py"], cwd=temporary, check=True)
    summary = {k: v for k, v in report.items() if k != "training"}
    (output / "index.html").write_text(
        '<!doctype html><html lang="en"><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        '<title>Concordia · measured 1PGA workflow</title>'
        '<style>body{font:17px system-ui;max-width:900px;margin:40px auto;padding:20px;'
        'color:#173b35}pre{white-space:pre-wrap;background:#edf4f2;padding:20px}'
        'a{color:#145e50}td,th{padding:14px;border-bottom:1px solid #c4d3d1;text-align:left}'
        'table{width:100%;border-collapse:collapse}h1{line-height:1.15}</style>'
        '<main><a href="/review">Back to review demo</a>'
        '<h1>Real-data local execution: protein G (1PGA)</h1>'
        '<p>930 published measured variants; fresh CPU baseline; position-held-out evaluation; '
        'scripted decisions preserved before assay import. Research software demonstration.</p>'
        '<p><a href="https://zenodo.org/records/7992926">Tsuboyama source data</a> · '
        '<a href="https://www.rcsb.org/structure/1PGA">RCSB reference</a></p>'
        '<p><a href="review.html">Review decisions and assays</a> · '
        '<a href="bundle.zip">Download verified bundle</a> · '
        '<a href="execution.json">Execution and model record</a></p>'
        '<h2>Held-out results</h2><p>745 training variants · 185 test variants · '
        '11 test positions absent from training. Lower RMSE is better.</p>'
        '<table><thead><tr><th>Model</th><th>RMSE (kcal/mol)</th><th>Rank correlation</th>'
        '</tr></thead><tbody>'
        f'<tr><td>Fresh CPU Ridge</td><td>{report["ridge_rmse"]:.3f}</td>'
        f'<td>{report["ridge_spearman"]:.3f}</td></tr>'
        f'<tr><td>Training-mean baseline</td><td>{report["mean_baseline_rmse"]:.3f}</td>'
        '<td>Undefined (constant predictions)</td></tr></tbody></table>'
        '<h2>What happened</h2><ol><li>Downloaded and checksum-verified the published data; '
        'mapped all mutations to the RCSB reference.</li><li>Trained and scored locally with '
        'a fixed position split.</li><li>Recorded illustrative select/defer/exclude decisions, '
        'then imported the measured outcomes and verified the export.</li></ol>'
        '<h2>Limits</h2><p>One retrospective protein, one fixed split, no uncertainty estimate. '
        'These results do not establish performance on other proteins or biological utility. '
        'Decisions are scripted demonstrations. ThermoMPNN and attribution were not run.</p>'
        '<details><summary>Full execution summary</summary><pre>'
        + html.escape(json.dumps(summary, indent=2)) + '</pre></details></main></html>'
    )
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
