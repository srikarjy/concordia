"""Validated review inputs, versioned local storage, and portable evidence exports.

Imported predictions are never promoted to validated biology. Decisions belong
explicitly to the researcher; no cross-assay score or automatic shortlist exists.
"""

from __future__ import annotations

import csv
import hashlib
import html
import io
import json
import re
import sqlite3
import uuid
import zipfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from concordia.campaigns.assay import parse_assay_csv
from concordia.storage.content import ContentAddressedStore

AA = set("ACDEFGHIKLMNPQRSTVWY")
MAX_ROWS = 1000
BOUNDARY = (
    "Human-reviewed evidence record. Imported predictions and measurements retain their "
    "source labels; authenticity and biological utility are not independently verified. "
    "Selection is a researcher decision, not a validated model recommendation."
)


class InputError(ValueError):
    def __init__(self, errors: list[str]):
        self.errors = errors
        super().__init__("; ".join(errors))


class ConflictError(ValueError):
    pass


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class ReviewInput(StrictModel):
    title: str = Field(min_length=1, max_length=200)
    objective: str = Field(min_length=1, max_length=2000)
    reference_sequence: str = Field(min_length=20, max_length=20_000)
    candidates_csv: str = Field(min_length=1, max_length=1_000_000)
    predictions_csv: str = Field(default="", max_length=1_000_000)
    protected_positions: list[int] = Field(default_factory=list, max_length=3000)
    constraint_note: str = Field(default="", max_length=2000)


class DecisionInput(StrictModel):
    expected_revision: int = Field(ge=1)
    candidate_id: str
    decision: Literal["selected", "excluded", "deferred"]
    reason: str = Field(min_length=1, max_length=2000)
    override_reason: str = Field(default="", max_length=2000)


class EvidenceInput(StrictModel):
    expected_revision: int = Field(ge=1)
    kind: Literal["predictions", "assay"]
    csv_text: str = Field(min_length=1, max_length=1_000_000)
    label: str = Field(min_length=1, max_length=200)
    context: str = Field(default="", max_length=2000)


def digest(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    ).hexdigest()


def normalize_reference(value: str) -> str:
    lines = value.strip().splitlines()
    if any(line.startswith(">") for line in lines):
        if not lines[0].startswith(">") or sum(line.startswith(">") for line in lines) != 1:
            raise InputError(["Reference: provide exactly one FASTA record."])
        lines = lines[1:]
    sequence = "".join("".join(lines).split()).upper()
    if not 20 <= len(sequence) <= 3000 or set(sequence) - AA:
        raise InputError(
            ["Reference: use 20–3000 standard amino acids; no gaps or unknown residues."]
        )
    return sequence


def read_csv(text: str, required: set[str]) -> list[dict[str, str]]:
    if len(text.encode()) > 1_000_000:
        raise InputError(["CSV exceeds 1 MB."])
    try:
        reader = csv.DictReader(io.StringIO(text.lstrip("\ufeff")), strict=True)
        columns = reader.fieldnames or []
        if len(columns) != len(set(columns)) or set(columns) != required:
            raise InputError([f"CSV columns must be exactly: {', '.join(sorted(required))}."])
        rows = []
        for number, row in enumerate(reader, 2):
            if None in row or any(value is None for value in row.values()):
                raise InputError([f"Row {number}: wrong number of columns."])
            rows.append({key: value.strip() for key, value in row.items()})
            if len(rows) > MAX_ROWS:
                raise InputError([f"CSV exceeds {MAX_ROWS} rows."])
    except csv.Error as exc:
        raise InputError([f"Malformed CSV: {exc}"]) from exc
    if not rows:
        raise InputError(["CSV contains no records."])
    return rows


def parse_candidates(text: str, reference: str, protected: list[int]) -> list[dict[str, Any]]:
    rows = read_csv(text, {"candidate_id", "mutations"})
    errors: list[str] = []
    candidates: list[dict[str, Any]] = []
    ids: set[str] = set()
    sequences: set[str] = set()
    for number, row in enumerate(rows, 2):
        cid, mutation = row["candidate_id"], row["mutations"].upper()
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}", cid) or cid in ids:
            errors.append(f"Row {number}: candidate_id must be unique, 1–64 letters/digits/._-.")
        ids.add(cid)
        sequence = list(reference)
        positions: list[int] = []
        valid = True
        for token in mutation.split(":"):
            match = re.fullmatch(
                r"([ACDEFGHIKLMNPQRSTVWY])([1-9][0-9]*)([ACDEFGHIKLMNPQRSTVWY])", token
            )
            if match is None:
                errors.append(
                    f"Row {number}: invalid substitution '{token}'; use A13Q or A13Q:K6Q."
                )
                valid = False
                continue
            original, p, target = match.groups()
            position = int(p)
            if position > len(reference) or reference[position - 1] != original:
                errors.append(
                    f"Row {number}: {token} does not match the reference at position {position}."
                )
                valid = False
            elif original == target or position in positions:
                errors.append(f"Row {number}: repeated position or unchanged residue in {token}.")
                valid = False
            else:
                sequence[position - 1] = target
            positions.append(position)
        if not valid:
            continue
        mutant = "".join(sequence)
        if mutant in sequences:
            errors.append(f"Row {number}: duplicate mutant sequence, even if its ID differs.")
        sequences.add(mutant)
        candidates.append(
            {
                "candidate_id": cid,
                "mutations": mutation,
                "sequence": mutant,
                "sequence_sha256": hashlib.sha256(mutant.encode()).hexdigest(),
                "positions": positions,
                "protected_hits": sorted(set(positions) & set(protected)),
                "decision": "unreviewed",
                "reason": "",
                "override_reason": "",
            }
        )
    if errors:
        raise InputError(errors[:50])
    return candidates


def parse_predictions(
    text: str, candidate_ids: set[str], existing: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    rows = read_csv(text, {"candidate_id", "source", "metric", "value", "unit", "direction"})
    errors = []
    keys = {(r["candidate_id"], r["source"], r["metric"]) for r in existing}
    semantics = {r["metric"]: (r["unit"], r["direction"]) for r in existing}
    output = []
    for number, row in enumerate(rows, 2):
        key = (row["candidate_id"], row["source"], row["metric"])
        if row["candidate_id"] not in candidate_ids:
            errors.append(f"Row {number}: unknown candidate_id {row['candidate_id']}.")
        if key in keys:
            errors.append(
                f"Row {number}: duplicate candidate/source/metric. Use a new source version."
            )
        keys.add(key)
        if any(not row[k] or len(row[k]) > 200 for k in ("source", "metric", "unit")):
            errors.append(
                f"Row {number}: source, metric and unit must be supplied (maximum 200 characters)."
            )
        if row["direction"] not in {"higher", "lower"}:
            errors.append(f"Row {number}: direction must be higher or lower.")
        semantic = (row["unit"], row["direction"])
        if row["metric"] in semantics and semantics[row["metric"]] != semantic:
            errors.append(
                f"Row {number}: incompatible units/direction for {row['metric']}; normalize explicitly or use a different metric."
            )
        semantics[row["metric"]] = semantic
        try:
            value = float(row["value"])
            if not __import__("math").isfinite(value):
                raise ValueError
        except ValueError:
            errors.append(f"Row {number}: prediction must be a finite number.")
            value = 0.0
        output.append({**row, "value": value})
    if errors:
        raise InputError(errors[:50])
    return output


def initial_review(body: ReviewInput) -> dict[str, Any]:
    reference = normalize_reference(body.reference_sequence)
    if not body.title.strip() or not body.objective.strip():
        raise InputError(["Title and objective cannot be blank."])
    if any(p < 1 or p > len(reference) for p in body.protected_positions):
        raise InputError(["Protected positions must use 1-based reference sequence numbering."])
    if body.protected_positions and not body.constraint_note.strip():
        raise InputError(["Explain the source or rationale for the protected positions."])
    candidates = parse_candidates(body.candidates_csv, reference, body.protected_positions)
    predictions = (
        parse_predictions(body.predictions_csv, {c["candidate_id"] for c in candidates}, [])
        if body.predictions_csv.strip()
        else []
    )
    return {
        "schema_version": 1,
        "review_id": uuid.uuid4().hex,
        "title": body.title.strip(),
        "objective": body.objective.strip(),
        "reference_sequence": reference,
        "reference_sha256": hashlib.sha256(reference.encode()).hexdigest(),
        "protected_positions": sorted(set(body.protected_positions)),
        "constraint_note": body.constraint_note,
        "candidates": candidates,
        "predictions": predictions,
        "assays": [],
        "inputs": [
            {
                "kind": "candidates",
                "label": "Original candidate import",
                "text": body.candidates_csv,
                "sha256": hashlib.sha256(body.candidates_csv.encode()).hexdigest(),
            }
        ]
        + (
            [
                {
                    "kind": "predictions",
                    "label": "Original prediction import",
                    "text": body.predictions_csv,
                    "sha256": hashlib.sha256(body.predictions_csv.encode()).hexdigest(),
                }
            ]
            if predictions
            else []
        ),
        "boundary": BOUNDARY,
        "scientific_use_allowed": False,
    }


def add_evidence(review: dict[str, Any], body: EvidenceInput) -> None:
    ids = {c["candidate_id"] for c in review["candidates"]}
    file_hash = hashlib.sha256(body.csv_text.encode()).hexdigest()
    if any(i["sha256"] == file_hash for i in review["inputs"]):
        raise InputError(["This exact file has already been imported."])
    if body.kind == "predictions":
        review["predictions"].extend(parse_predictions(body.csv_text, ids, review["predictions"]))
    else:
        if not body.context.strip():
            raise InputError(["Record assay conditions/context; use 'not stated' if unavailable."])
        # Check shape/size first, then reuse the campaign parser for status/value semantics.
        rows = read_csv(
            body.csv_text,
            {"candidate_id", "metric", "value", "unit", "method", "status", "replicate"},
        )
        parsed = parse_assay_csv(body.csv_text)
        errors = [f"Row {e.row}: {e.message}" for e in parsed.errors]
        for number, row in enumerate(rows, 2):
            if row["candidate_id"] not in ids:
                errors.append(f"Row {number}: unknown candidate_id {row['candidate_id']}.")
            if not row["unit"] or not row["method"]:
                errors.append(
                    f"Row {number}: provide unit and method; use 'not stated' if unavailable."
                )
            if row["status"] in {"invalid", "failed_expression", "planned"} and row["value"]:
                errors.append(
                    f"Row {number}: {row['status']} must not contain a numeric measurement."
                )
        if any(a["label"] == body.label for a in review["assays"]):
            errors.append("Assay label already exists; use a distinct batch or condition label.")
        if errors:
            raise InputError(errors[:50])
        review["assays"].append(
            {
                "label": body.label,
                "context": body.context,
                "input_sha256": file_hash,
                "decision_revision": review["revision"],
                "decisions_at_import": {
                    c["candidate_id"]: c["decision"] for c in review["candidates"]
                },
                "rows": [row.model_dump(mode="json") for row in parsed.rows],
            }
        )
    review["inputs"].append(
        {
            "kind": body.kind,
            "label": body.label,
            "context": body.context,
            "text": body.csv_text,
            "sha256": file_hash,
        }
    )


def set_decision(review: dict[str, Any], body: DecisionInput) -> None:
    candidate = next(
        (c for c in review["candidates"] if c["candidate_id"] == body.candidate_id), None
    )
    if candidate is None:
        raise InputError(["Unknown candidate."])
    if not body.reason.strip():
        raise InputError(["Record a reason for this decision."])
    if (
        candidate["protected_hits"]
        and body.decision == "selected"
        and not body.override_reason.strip()
    ):
        raise InputError(
            ["Selecting a protected-position variant requires an explicit override reason."]
        )
    candidate.update(
        decision=body.decision,
        reason=body.reason.strip(),
        override_reason=body.override_reason.strip(),
    )


def comparison_flags(review: dict[str, Any]) -> dict[str, list[str]]:
    flags: dict[str, list[str]] = {}
    for c in review["candidates"]:
        cid = c["candidate_id"]
        values = []
        if c["protected_hits"]:
            values.append("Protected position: " + ", ".join(map(str, c["protected_hits"])))
        if len(c["positions"]) > 1:
            values.append(
                "Multi-mutant: single-mutation evidence does not establish combination effects"
            )
        if not any(p["candidate_id"] == cid for p in review["predictions"]):
            values.append("No imported prediction")
        if not any(
            r["candidate_id"] == cid and r["status"] == "measured"
            for a in review["assays"]
            for r in a["rows"]
        ):
            values.append("No measured assay result")
        flags[cid] = values
    # Compare orderings only on the exact common candidate cohort and same metric.
    for metric in {p["metric"] for p in review["predictions"]}:
        groups: dict[str, dict[str, float]] = {}
        direction = "higher"
        for p in review["predictions"]:
            if p["metric"] == metric:
                groups.setdefault(p["source"], {})[p["candidate_id"]] = p["value"]
                direction = p["direction"]
        if len(groups) < 2:
            continue
        common = set.intersection(*(set(g) for g in groups.values()))
        if len(common) < 2:
            continue
        for cid in common:
            ranks = []
            for group in groups.values():
                value = group[cid]
                better = sum(
                    (group[k] > value if direction == "higher" else group[k] < value)
                    for k in common
                )
                ties = sum(group[k] == value for k in common) - 1
                ranks.append((better + ties / 2) / (len(common) - 1))
            if max(ranks) - min(ranks) >= 0.5:
                flags[cid].append(
                    f"Source ordering differs: {metric} (rank span ≥50% on {len(common)} shared candidates; heuristic)"
                )
    return flags


class ReviewStore:
    def __init__(self, root: Path):
        root.mkdir(parents=True, exist_ok=True)
        self.db = root / "reviews.sqlite3"
        self.artifacts = ContentAddressedStore(root / "artifacts")
        with self.connect() as db:
            db.execute(
                "CREATE TABLE IF NOT EXISTS revisions (review_id TEXT, revision INTEGER, digest TEXT, title TEXT, updated_at TEXT, PRIMARY KEY (review_id, revision))"
            )

    def connect(self) -> sqlite3.Connection:
        db = sqlite3.connect(self.db, timeout=15)
        db.row_factory = sqlite3.Row
        return db

    def list_reviews(self) -> list[dict[str, Any]]:
        with self.connect() as db:
            return [
                dict(row)
                for row in db.execute(
                    "SELECT review_id, MAX(revision) AS revision, title, MAX(updated_at) AS updated_at FROM revisions GROUP BY review_id ORDER BY updated_at DESC"
                )
            ]

    def load(self, review_id: str, revision: int | None = None) -> dict[str, Any]:
        with self.connect() as db:
            if revision is None:
                row = db.execute(
                    "SELECT digest FROM revisions WHERE review_id=? ORDER BY revision DESC LIMIT 1",
                    (review_id,),
                ).fetchone()
            else:
                row = db.execute(
                    "SELECT digest FROM revisions WHERE review_id=? AND revision=?",
                    (review_id, revision),
                ).fetchone()
        if row is None:
            raise KeyError("Review or revision not found")
        return {
            **json.loads(self.artifacts.get_bytes(row["digest"])),
            "artifact_digest": row["digest"],
        }

    def history(self, review_id: str) -> list[dict[str, Any]]:
        with self.connect() as db:
            return [
                dict(row)
                for row in db.execute(
                    "SELECT revision, digest, updated_at FROM revisions WHERE review_id=? ORDER BY revision DESC",
                    (review_id,),
                )
            ]

    def save(self, review: dict[str, Any], expected: int, action: str) -> dict[str, Any]:
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            last = db.execute(
                "SELECT revision, digest FROM revisions WHERE review_id=? ORDER BY revision DESC LIMIT 1",
                (review["review_id"],),
            ).fetchone()
            if (last["revision"] if last else 0) != expected:
                raise ConflictError(
                    "Review changed in another tab. Reload the review before saving."
                )
            payload = {
                **review,
                "revision": expected + 1,
                "previous_digest": last["digest"] if last else None,
                "updated_at": datetime.now(UTC).isoformat(),
                "action": action,
            }
            payload.pop("artifact_digest", None)
            artifact = self.artifacts.put_json(payload)
            db.execute(
                "INSERT INTO revisions VALUES (?, ?, ?, ?, ?)",
                (
                    review["review_id"],
                    expected + 1,
                    artifact,
                    review["title"],
                    payload["updated_at"],
                ),
            )
        return {**payload, "artifact_digest": artifact}


def csv_export(review: dict[str, Any], selected_only: bool = False) -> str:
    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow(
        [
            "candidate_id",
            "mutations",
            "sequence",
            "decision",
            "reason",
            "override_reason",
            "flags",
            "review_revision",
        ]
    )
    flags = comparison_flags(review)
    for c in review["candidates"]:
        if selected_only and c["decision"] != "selected":
            continue
        values = [
            c["candidate_id"],
            c["mutations"],
            c["sequence"],
            c["decision"],
            c["reason"],
            c["override_reason"],
            "; ".join(flags[c["candidate_id"]]),
            str(review["revision"]),
        ]
        writer.writerow(
            ["'" + v if v.lstrip().startswith(("=", "+", "-", "@")) else v for v in values]
        )
    return out.getvalue()


def html_report(review: dict[str, Any]) -> str:
    e = lambda value: html.escape(str(value))  # noqa: E731
    flags = comparison_flags(review)
    rows = []
    for c in review["candidates"]:
        evidence = [
            f"{p['source']} · {p['metric']}: {p['value']} {p['unit']} ({p['direction']} preferred)"
            for p in review["predictions"]
            if p["candidate_id"] == c["candidate_id"]
        ]
        evidence += [
            f"Assay {a['label']} · {r['metric']}: {r['status']}, {r['value']} {r['unit']}; replicate {r['replicate']}; method {r['method']}; context {a['context']}"
            for a in review["assays"]
            for r in a["rows"]
            if r["candidate_id"] == c["candidate_id"]
        ]
        rows.append(
            "<tr>"
            + "".join(
                "<td>" + e(v) + "</td>"
                for v in [
                    c["candidate_id"],
                    c["mutations"],
                    c["decision"],
                    c["reason"],
                    c["override_reason"],
                    "; ".join(flags[c["candidate_id"]]),
                    "\n".join(evidence),
                ]
            )
            + "</tr>"
        )
    inputs = "".join(
        f"<li>{e(i['label'])} ({e(i['kind'])}): <code>{e(i['sha256'])}</code></li>"
        for i in review["inputs"]
    )
    return f"""<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width"><title>{e(review["title"])} · Concordia</title>
<style>body{{font:15px system-ui;margin:40px;color:#172d2b}}table{{border-collapse:collapse;width:100%}}td,th{{border:1px solid #c4d3d1;padding:10px;text-align:left;vertical-align:top;white-space:pre-wrap}}code{{overflow-wrap:anywhere}}.note{{background:#edf4f2;padding:16px}}@media print{{body{{margin:10px;font-size:10px}}}}</style>
<h1>{e(review["title"])}</h1><p>{e(review["objective"])}</p><p class="note">{e(BOUNDARY)}</p>
<p>Review {e(review["review_id"])} · revision {review["revision"]} · {e(review["updated_at"])}</p>
<p>Protected positions: {e(review["protected_positions"])}. Rationale: {e(review["constraint_note"])}</p>
<p>Reference SHA-256: <code>{e(review["reference_sha256"])}</code></p>
<table><thead><tr><th>Candidate</th><th>Mutations</th><th>Decision</th><th>Reason</th><th>Override</th><th>Flags</th><th>Evidence</th></tr></thead><tbody>{"".join(rows)}</tbody></table>
<h2>Input provenance</h2><ul>{inputs}</ul><p>Snapshot SHA-256: <code>{e(review["artifact_digest"])}</code></p>
<p>Hashes detect changes to recorded content; they do not authenticate the input author or validate biological claims. Full inputs and earlier decisions are in the companion review bundle.</p></html>"""


def export_bundle(review: dict[str, Any], history: list[dict[str, Any]]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("report.html", html_report(review))
        archive.writestr("selected-candidates.csv", csv_export(review, True))
        archive.writestr("all-decisions.csv", csv_export(review))
        archive.writestr("review.json", json.dumps(review, indent=2, allow_nan=False))
        archive.writestr("history.json", json.dumps(history, indent=2, allow_nan=False))
        archive.writestr("reference.fasta", ">reference\n" + review["reference_sequence"] + "\n")
        for index, item in enumerate(review["inputs"]):
            archive.writestr(f"inputs/{index + 1:03d}-{item['kind']}.csv", item["text"])
        archive.writestr(
            "verify.py",
            '''"""Run: python3 verify.py from the extracted bundle. Uses only the standard library."""
import hashlib, json
from pathlib import Path
root = Path(__file__).resolve().parent
snapshots = json.loads((root / "history.json").read_text())
latest = json.loads((root / "review.json").read_text())
previous = None
for item in snapshots:
    payload = dict(item)
    recorded = payload.pop("artifact_digest")
    actual = hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()
    assert actual == recorded, "Snapshot hash mismatch"
    assert payload["previous_digest"] == previous, "Revision chain mismatch"
    previous = recorded
assert snapshots[-1] == latest, "Latest snapshot mismatch"
for index, item in enumerate(latest["inputs"]):
    raw = (root / f"inputs/{index + 1:03d}-{item['kind']}.csv").read_bytes()
    assert hashlib.sha256(raw).hexdigest() == item["sha256"], "Input hash mismatch"
print("Recorded snapshots and input hashes verified. Not biological validation or external attestation.")
''',
        )
        archive.writestr(
            "README.txt",
            "Open report.html to review decisions. selected-candidates.csv is the human shortlist.\nreview.json and history.json preserve full inputs, evidence and decision revisions.\nRun python3 verify.py to verify snapshot hashes, links and raw input files.\nNo hosted service or model is called. This bundle contains your sequences and evidence; review before sharing.\n",
        )
    return buffer.getvalue()
