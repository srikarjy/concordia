"""Build the metadata-only Rule 2 alignment and leakage census."""

from __future__ import annotations

import argparse
import json
import pickle
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from Bio.Align import PairwiseAligner
from freeze_tsuboyama_rule2_manifest import read_candidates, read_uniprot_results

ALLOWED_FEATURES = {"Active site", "Binding site", "Metal binding", "Disulfide bond"}


def _chain_ranges(references: list[dict[str, Any]]) -> list[tuple[int, int]]:
    ranges: list[tuple[int, int]] = []
    for reference in references:
        for item in reference.get("properties", []):
            if item.get("key") == "Chains":
                ranges.extend(
                    (int(left), int(right))
                    for left, right in re.findall(r"=([0-9]+)-([0-9]+)", str(item.get("value")))
                )
    return ranges


def _alignment(sequence: str, candidate: str) -> dict[str, Any]:
    windows: list[tuple[float, int, list[int]]] = []
    for index in range(len(sequence) - len(candidate) + 1):
        window = sequence[index : index + len(candidate)]
        mismatches = [
            position + 1
            for position, (left, right) in enumerate(zip(candidate, window, strict=True))
            if left != right
        ]
        windows.append(((len(candidate) - len(mismatches)) / len(candidate), index + 1, mismatches))
    if not windows:
        return {"identity": 0.0, "mismatch_positions": [], "unique": False, "indels": True}
    top = max(item[0] for item in windows)
    winners = [item for item in windows if item[0] == top]
    _, start, mismatches = winners[0]
    aligner = PairwiseAligner()
    aligner.mode = "local"
    aligner.match_score = 2
    aligner.mismatch_score = -1
    aligner.open_gap_score = -5
    aligner.extend_gap_score = -1
    aligned = aligner.align(candidate, sequence)[0]
    target, reference = aligned.aligned
    indels = not (
        len(target) == 1
        and target[0][0] == 0
        and target[0][1] == len(candidate)
        and reference[0][1] - reference[0][0] == len(candidate)
    )
    return {
        "identity": top,
        "start": start,
        "mismatch_positions": mismatches,
        "mismatch_count": len(mismatches),
        "unique": len(winners) == 1,
        "indels": indels,
    }


def _record_for(accession: str, records: list[dict[str, Any]]) -> dict[str, Any] | None:
    return next((record for record in records if record.get("primaryAccession") == accession), None)


def _domain_row(
    candidate: Any, annotation: dict[str, Any], records: list[dict[str, Any]]
) -> dict[str, Any]:
    accession = str(annotation["accessions"][0])
    record = _record_for(accession, records)
    if record is None:
        return {"domain_id": candidate.domain_id, "accession": accession, "status": "NO_RECORD"}
    sequence = str(record["sequence"]["value"])
    evidence = _alignment(sequence, candidate.sequence)
    references = [
        item
        for item in record.get("uniProtKBCrossReferences", [])
        if item.get("database") == "PDB"
        and item.get("id") == candidate.domain_id.removesuffix(".pdb")
    ]
    ranges = _chain_ranges(references)
    protected: list[dict[str, Any]] = []
    for feature in record.get("features", []):
        if feature.get("type") not in ALLOWED_FEATURES:
            continue
        position = feature.get("location", {}).get("start", {}).get("value")
        if not isinstance(position, int) or not any(
            low <= position <= high for low, high in ranges
        ):
            continue
        local = position - int(evidence.get("start", 1)) + 1
        if 1 <= local <= candidate.length:
            protected.append(
                {
                    "local_position": local,
                    "local_residue": candidate.sequence[local - 1],
                    "uniprot_position": position,
                    "uniprot_residue": sequence[position - 1],
                    "feature_type": feature.get("type"),
                }
            )
    letters_match = all(item["local_residue"] == item["uniprot_residue"] for item in protected)
    nearest = None
    if protected and evidence.get("mismatch_positions"):
        nearest = min(
            min(
                abs(item["local_position"] - mismatch)
                for mismatch in evidence["mismatch_positions"]
            )
            for item in protected
        )
    elif protected:
        nearest = None
    new_pass = bool(
        evidence.get("unique")
        and evidence.get("identity", 0.0) >= 0.90
        and not evidence.get("indels")
        and protected
        and letters_match
        and (nearest is None or nearest > 1)
    )
    old_pass = bool(
        evidence.get("unique")
        and evidence.get("identity", 0.0) == 1.0
        and not evidence.get("indels")
        and protected
        and letters_match
    )
    return {
        "domain_id": candidate.domain_id,
        "length": candidate.length,
        "variants": candidate.single_substitution_count,
        "accession": accession,
        "identity": evidence.get("identity"),
        "mismatch_positions": evidence.get("mismatch_positions", []),
        "mismatch_count": evidence.get("mismatch_count", 0),
        "indels": evidence.get("indels"),
        "alignment_unique": evidence.get("unique"),
        "protected_residue_letters_match": letters_match if protected else None,
        "nearest_mismatch_distance_to_protected": nearest,
        "mapped_protected_residues": protected,
        "old_guard": "PASS" if old_pass else "FAIL",
        "new_guard": "PASS" if new_pass else "FAIL",
        "new_guard_clauses": (
            ["pass"]
            if new_pass
            else [
                clause
                for clause, failed in (
                    ("unique best window", not evidence.get("unique")),
                    ("identity < 0.90", evidence.get("identity", 0.0) < 0.90),
                    ("internal indel", bool(evidence.get("indels"))),
                    ("no residue-mapped hard-protection feature", not protected),
                    ("protected-residue letter mismatch", not letters_match),
                    (
                        "mismatch adjacent to protected residue",
                        nearest is not None and nearest <= 1,
                    ),
                )
                if failed
            ]
        ),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--candidates", type=Path, required=True)
    parser.add_argument("--annotations", type=Path, required=True)
    parser.add_argument("--cache", type=Path, required=True)
    parser.add_argument("--splits", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    candidates = {item.domain_id: item for item in read_candidates(args.candidates)}
    annotations = json.loads(args.annotations.read_text())
    records = read_uniprot_results(args.cache)
    splits = pickle.loads(args.splits.read_bytes())
    categories = {
        domain: next(
            (
                name
                for name in ("train", "val", "test")
                if domain in {str(x) for x in splits[name]}
            ),
            "absent",
        )
        for domain in candidates
    }
    rule2 = [
        domain
        for domain, value in annotations.items()
        if any(feature in ALLOWED_FEATURES for feature in value.get("features", []))
    ]
    table = []
    for domain in sorted(rule2):
        row = _domain_row(candidates[domain + ".pdb"], annotations[domain], records)
        row["thermompnn_split"] = categories.get(domain + ".pdb", "unavailable")
        table.append(row)
    target_ids = [
        "1BK2.pdb", "1IGV.pdb", "2ROT.pdb", "3NGP.pdb", "5ECA.pdb",
        "5FW9.pdb", "5FWB.pdb", "6IPY.pdb", "1TUC.pdb", "2KXD.pdb",
        "3DKM.pdb",
    ]
    target = [row for row in table if row["domain_id"] in target_ids]
    output = {
        "created_at": datetime.now(UTC).isoformat(),
        "predicate": {
            "unique_best_window": True,
            "identity_minimum": 0.90,
            "zero_internal_indels": True,
            "protected_letter_match": True,
            "no_mismatch_within_plus_or_minus_one": True,
            "requires_mapped_protection": True,
        },
        "rule2_domains": table,
        "eleven_candidate_verdicts": target,
        "counts": {
            name: sum(row["thermompnn_split"] == name for row in table)
            for name in ("train", "val", "test", "absent")
        },
    }
    args.output.write_text(json.dumps(output, indent=2, sort_keys=True) + "\n")
    print(
        json.dumps(
            {
                "rule2_domains": len(table),
                "target_candidates": len(target),
                "output": str(args.output),
            }
        )
    )


if __name__ == "__main__":
    main()
