"""Freeze a corrected, metadata-first Tsuboyama Rule 2 manifest."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import random
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import numpy as np
from Bio.Align import PairwiseAligner

from concordia.stability.contracts import canonical_json, freeze_manifest

ALLOWED_FEATURES = {"Active site", "Binding site", "Metal binding", "Disulfide bond"}
CHAIN_RANGE = re.compile(r"=([0-9]+)-([0-9]+)")
HOLDOUT_SIZE = 10
RANDOM_FOLD_POSITION_COVERAGE_MIN = 0.90


@dataclass(frozen=True)
class Candidate:
    domain_id: str
    sequence: str
    length: int
    single_substitution_count: int
    structure_path: str


@dataclass(frozen=True)
class ProtectedResidue:
    local_position: int
    local_residue: str
    uniprot_position: int
    uniprot_residue: str
    feature_type: str
    accession: str


@dataclass(frozen=True)
class Alignment:
    accession: str
    start: int
    derived_offset: int
    matched_length: int
    identity: float
    full_sequence_length: int
    mismatch_positions: tuple[int, ...] = ()
    indels: bool = False


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_candidates(path: Path) -> list[Candidate]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    return sorted(
        [
            Candidate(
                domain_id=str(row["domain_id"]),
                sequence=str(row["sequence"]),
                length=len(str(row["sequence"])),
                single_substitution_count=int(row["single_substitution_count"]),
                structure_path=str(row["structure_path"]),
            )
            for row in raw
        ],
        key=lambda row: row.domain_id,
    )


def read_uniprot_results(cache_dir: Path) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for path in sorted(cache_dir.glob("batch_*.json")):
        results.extend(json.loads(path.read_text(encoding="utf-8")).get("results", []))
    return results


def _chain_ranges(reference: dict[str, Any]) -> list[tuple[int, int]]:
    ranges: list[tuple[int, int]] = []
    for property_row in reference.get("properties", []):
        if property_row.get("key") == "Chains":
            ranges.extend(
                (int(match.group(1)), int(match.group(2)))
                for match in CHAIN_RANGE.finditer(str(property_row.get("value", "")))
            )
    return ranges


def _align(candidate: Candidate, accession: str, sequence: str) -> Alignment:
    if len(sequence) < candidate.length:
        raise ValueError(f"alignment for {candidate.domain_id}/{accession} is too short")
    windows: list[tuple[float, int, tuple[int, ...]]] = []
    for index in range(len(sequence) - candidate.length + 1):
        window = sequence[index : index + candidate.length]
        mismatches = tuple(
            position + 1
            for position, (left, right) in enumerate(
                zip(candidate.sequence, window, strict=True)
            )
            if left != right
        )
        windows.append(
            ((candidate.length - len(mismatches)) / candidate.length, index + 1, mismatches)
        )
    best_identity = max(item[0] for item in windows)
    best = [item for item in windows if item[0] == best_identity]
    if len(best) != 1:
        raise ValueError(f"alignment for {candidate.domain_id}/{accession} is ambiguous")
    _, start, mismatches = best[0]

    aligner = PairwiseAligner()
    aligner.mode = "local"
    aligner.match_score = 2
    aligner.mismatch_score = -1
    aligner.open_gap_score = -5
    aligner.extend_gap_score = -1
    local = aligner.align(candidate.sequence, sequence)[0]
    aligned_target, aligned_reference = local.aligned
    indels = not (
        len(aligned_target) == 1
        and aligned_target[0][0] == 0
        and aligned_target[0][1] == candidate.length
        and aligned_reference[0][1] - aligned_reference[0][0] == candidate.length
    )
    return Alignment(
        accession,
        start,
        start - 1,
        candidate.length,
        best_identity,
        len(sequence),
        mismatches,
        indels,
    )


def _has_feature_in_reference(
    result: dict[str, Any], references: list[dict[str, Any]]
) -> bool:
    ranges = [item for reference in references for item in _chain_ranges(reference)]
    for feature in result.get("features", []):
        if str(feature.get("type", "")) not in ALLOWED_FEATURES:
            continue
        location = feature.get("location", {})
        start = location.get("start", {}).get("value")
        end = location.get("end", {}).get("value")
        if isinstance(start, int) and isinstance(end, int):
            if any(start <= high and end >= low for low, high in ranges):
                return True
    return False


def candidate_annotations(
    candidate: Candidate, results: list[dict[str, Any]]
) -> tuple[list[Alignment], list[ProtectedResidue]]:
    pdb_id = candidate.domain_id.removesuffix(".pdb")
    alignments: dict[tuple[str, int], Alignment] = {}
    protected: dict[tuple[int, str, str], ProtectedResidue] = {}
    for result in results:
        accession = str(result.get("primaryAccession", ""))
        sequence = str(result.get("sequence", {}).get("value", ""))
        if not accession or not sequence:
            continue
        references = [
            ref
            for ref in result.get("uniProtKBCrossReferences", [])
            if ref.get("database") == "PDB" and ref.get("id") == pdb_id
        ]
        if not references:
            continue
        alignment = _align(candidate, accession, sequence)
        alignments[(accession, alignment.start)] = alignment
        for feature in result.get("features", []):
            feature_type = str(feature.get("type", ""))
            if feature_type not in ALLOWED_FEATURES:
                continue
            location = feature.get("location", {})
            start = location.get("start", {}).get("value")
            end = location.get("end", {}).get("value")
            if not isinstance(start, int) or not isinstance(end, int):
                continue
            local_start = start - alignment.start + 1
            local_end = end - alignment.start + 1
            if not (1 <= local_start <= candidate.length and local_end <= candidate.length):
                continue
            local_residue = candidate.sequence[local_start - 1]
            uniprot_residue = sequence[start - 1]
            if local_residue != uniprot_residue:
                raise ValueError(f"protected residue identity mismatch for {candidate.domain_id}")
            if any(abs(local_start - mismatch) <= 1 for mismatch in alignment.mismatch_positions):
                raise ValueError(
                    f"alignment mismatch is adjacent to protected residue for {candidate.domain_id}"
                )
            item = ProtectedResidue(
                local_start, local_residue, start, uniprot_residue, feature_type, accession
            )
            protected[(item.local_position, item.feature_type, item.accession)] = item
    return sorted(alignments.values(), key=lambda item: (item.accession, item.start)), sorted(
        protected.values(), key=lambda item: (item.local_position, item.feature_type)
    )


def read_variant_rows(path: Path, domain_id: str) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    with path.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            if row.get("domain_id") != domain_id:
                continue
            parsed: dict[str, object] = dict(row)
            parsed["position"] = int(str(row["position"]))
            rows.append(parsed)
    if not rows:
        raise ValueError(f"no normalized rows for {domain_id}")
    return rows


def validate_rows(rows: list[dict[str, object]], sequence: str) -> None:
    wild_types = [row for row in rows if row.get("is_wild_type") == "True"]
    if len(wild_types) != 1:
        raise ValueError("wild-type row is not present exactly once")
    if wild_types[0].get("sequence") != sequence:
        raise ValueError("wild-type sequence does not match candidate sequence")
    wild_type_value = float(str(wild_types[0]["ddg_kcal_higher_is_more_stable"]))
    if not math.isfinite(wild_type_value) or abs(wild_type_value) > 1e-9:
        raise ValueError("wild-type ddG is not anchored at zero")
    for row in rows:
        for field in ("delta_g_kcal_mol", "ddg_kcal_higher_is_more_stable"):
            value = float(str(row[field]))
            if not math.isfinite(value):
                raise ValueError(f"non-finite value in {field}")


def _position_folds(positions: list[int]) -> dict[str, list[int]]:
    return {
        str(fold): sorted(
            positions[index]
            for index in range(len(positions))
            if (index * 5) // len(positions) == fold
        )
        for fold in range(5)
    }


def _variants_by_position(
    rows: list[dict[str, object]], position_folds: dict[str, list[int]]
) -> dict[str, list[str]]:
    return {
        fold: sorted(
            str(row["variant_id"])
            for row in rows
            if row.get("is_wild_type") != "True"
            and int(str(row["position"])) in fold_positions
        )
        for fold, fold_positions in position_folds.items()
    }


def _random_row_folds(
    rows: list[dict[str, object]], seed: int
) -> tuple[dict[str, list[int]], dict[str, list[str]]]:
    shuffled = rows[:]
    random.Random(seed).shuffle(shuffled)
    row_folds: dict[str, list[dict[str, object]]] = {str(fold): [] for fold in range(5)}
    for index, row in enumerate(shuffled):
        row_folds[str(index % 5)].append(row)
    positions = {
        fold: sorted({int(str(row["position"])) for row in fold_rows})
        for fold, fold_rows in row_folds.items()
    }
    variants = {
        fold: sorted(str(row["variant_id"]) for row in fold_rows)
        for fold, fold_rows in row_folds.items()
    }
    return positions, variants


def build_splits(
    rows: list[dict[str, object]],
    seed: int,
    mutable_positions: list[int],
    wild_type_variant_id: str,
) -> dict[str, Any]:
    holdout = sorted(random.Random(seed).sample(mutable_positions, HOLDOUT_SIZE))
    holdout_set = set(holdout)
    remaining = [position for position in mutable_positions if position not in holdout_set]
    modulo = {str(fold): [p for p in remaining if p % 5 == fold] for fold in range(5)}
    contiguous = _position_folds(remaining)
    remaining_set = set(remaining)
    remaining_rows = [
        row
        for row in rows
        if row.get("is_wild_type") != "True"
        and int(str(row["position"])) in remaining_set
    ]
    random_positions, random_variants = _random_row_folds(remaining_rows, seed)
    non_holdout_position_count = len(remaining)
    random_position_coverage = {
        str(fold): len(random_positions[str(fold)]) / non_holdout_position_count
        for fold in range(5)
    }
    if any(
        coverage < RANDOM_FOLD_POSITION_COVERAGE_MIN
        for coverage in random_position_coverage.values()
    ):
        raise ValueError(
            "random fold does not span at least 90% of non-holdout mutable positions"
        )
    modulo_variants = _variants_by_position(remaining_rows, modulo)
    contiguous_variants = _variants_by_position(remaining_rows, contiguous)
    schemes: dict[str, Any] = {
        "modulo_5": {"positions": modulo, "variants": modulo_variants},
        "contiguous_5": {"positions": contiguous, "variants": contiguous_variants},
        "random_5": {"positions": random_positions, "variants": random_variants},
    }
    for scheme in schemes.values():
        if any(
            wild_type_variant_id in values for values in scheme["variants"].values()
        ):
            raise ValueError("wild-type row appears in a fold")
        training_positions = {
            position
            for positions in scheme["positions"].values()
            for position in positions
        }
        if holdout_set.intersection(training_positions):
            raise ValueError("holdout position appears in a training fold")
    return {
        "primary": "position_modulo_5_on_remaining_positions",
        "diagnostic": ["position_contiguous_5_on_remaining_positions", "random_rows_5"],
        "seed": seed,
        "holdout": {
            "positions": holdout,
            "size": len(holdout),
            "draw": "random.sample",
            "seed": seed,
        },
        "random_row_fold_guard": {
            "previous_rule": {
                "description": "each random fold spans more than 60 mutable positions",
                "minimum_distinct_positions": 61,
            },
            "current_rule": {
                "description": (
                    "each random fold spans at least 90% of non-holdout "
                    "mutable positions"
                ),
                "minimum_position_coverage": RANDOM_FOLD_POSITION_COVERAGE_MIN,
            },
            "reason": (
                "The absolute threshold was calibrated on 1IGV and rejected a "
                "correct row-random split for 2AMI; relative coverage preserves "
                "the order-of-magnitude detector for position-based defects."
            ),
            "changed_before_label_distribution_inspection": True,
            "motivation": {
                "1IGV": {"non_holdout_positions": 64, "coverage": "62-64/64"},
                "2AMI": {"non_holdout_positions": 62, "coverage": "59-62/62"},
                "position_based_failure": {"coverage": "about 13/62"},
            },
            "observed_fold_counts": {
                fold: {
                    "distinct_positions": len(random_positions[fold]),
                    "non_holdout_position_count": non_holdout_position_count,
                    "coverage": random_position_coverage[fold],
                }
                for fold in sorted(random_positions)
            },
        },
        **schemes,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--candidates", type=Path, required=True)
    parser.add_argument("--uniprot-cache", type=Path, required=True)
    parser.add_argument("--variant-table", type=Path, required=True)
    parser.add_argument("--raw-zenodo-file", type=Path, required=True)
    parser.add_argument("--alphafold-zip", type=Path, required=True)
    parser.add_argument("--previous-manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--seed", type=int, default=1729)
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError("new manifest path already exists; refusing to overwrite")

    candidates = read_candidates(args.candidates)
    results = read_uniprot_results(args.uniprot_cache)
    annotations: list[dict[str, Any]] = []
    selected: Candidate | None = None
    selected_alignment: Alignment | None = None
    selected_protected: list[ProtectedResidue] = []
    for candidate in candidates:
        alignments, protected = candidate_annotations(candidate, results)
        eligible = bool(protected) and all(
            alignment.identity >= 0.90 and not alignment.indels
            for alignment in alignments
        )
        annotations.append(
            {
                "domain_id": candidate.domain_id,
                "rule2_eligible": eligible,
                "alignments": [asdict(item) for item in alignments],
                "protected_residues": [asdict(item) for item in protected],
            }
        )
        if selected is None and eligible:
            selected = candidate
            selected_alignment = alignments[0]
            selected_protected = protected
            break
    if selected is None or selected_alignment is None:
        raise ValueError("no candidate passes residue-mapped Rule 2")

    rows = read_variant_rows(args.variant_table, selected.domain_id)
    validate_rows(rows, selected.sequence)
    mutable_positions = sorted(
        {int(str(row["position"])) for row in rows if row.get("is_wild_type") != "True"}
    )
    if mutable_positions != list(range(1, selected.length + 1)):
        raise ValueError("mutable positions are not exactly 1..domain_length")
    if canonical_json({"value": np.float64(1.0)}) != canonical_json({"value": 1.0}):
        raise ValueError("numpy scalar canonicalization self-check failed")
    wild_type_variant_id = str(
        next(row for row in rows if row.get("is_wild_type") == "True")["variant_id"]
    )
    splits = build_splits(rows, args.seed, mutable_positions, wild_type_variant_id)
    ordered_rows = sorted(rows, key=lambda row: (int(str(row["position"])), str(row["variant_id"])))
    row_payload = {"domain_id": selected.domain_id, "rows": ordered_rows}
    payload: dict[str, Any] = {
        "kind": "concordia_tsuboyama_stability_manifest",
        "predecessor": {
            "path": str(args.previous_manifest),
            "defects": [
                "UniProt offset was hardcoded as +4 instead of derived +5",
                "random_5 assigned positions rather than variant rows",
                "wild-type position 0 was included in folds",
                "holdout was hardcoded to modulo fold 4 and overlapped contiguous training",
            ],
            "replacement_reason": (
                "New write-once manifest correcting all four diagnostics; "
                "predecessor retained unchanged."
            ),
        },
        "source": {
            "dataset": "Tsuboyama_2023_megascale",
            "zenodo_record": "7992926",
            "version": "v2_230420",
            "concept_doi": "10.5281/zenodo.7992926",
            "license": "CC-BY-4.0",
            "citation": "Tsuboyama et al., Nature 620:434-444 (2023)",
            "published_md5": "f7e8c553efee734cf161ee6f2b0a09cf",
            "local_sha256": sha256_file(args.raw_zenodo_file),
            "alphafold_bundle_sha256": sha256_file(args.alphafold_zip),
            "normalization_command": (
                ".venv/bin/python scripts/normalize_tsuboyama.py --variants "
                "data/raw/tsuboyama_v2_230420/"
                "Tsuboyama2023_Dataset2_Dataset3_20230416.csv --quality "
                "data/raw/tsuboyama_v2_230420/Single_DMS_list.csv --structures "
                "data/raw/tsuboyama_v2_230420/structures/AlphaFold_model_PDBs "
                "--output data/processed/tsuboyama_v2_230420_normalized.csv"
            ),
            "normalized_table_sha256": sha256_file(args.variant_table),
        },
        "rule_change": {
            "selected_rule": "Rule 2",
            "definition": (
                "UniProt ACT_SITE, BINDING, METAL, or DISULFID annotation "
                "on an aligned domain residue"
            ),
            "superseded_rule": "Rule 1: disulfide only",
            "justification": (
                "Disulfides are near-absent in this cDNA-display assay; RSA "
                "protection returns every candidate and remains soft protection only."
            ),
            "census_counts": {
                "three_way_candidates": 184,
                "disulfide_domains": 2,
                "disulfide_passing_three_way": 0,
                "rule2_record_level_candidates": 47,
                "rule2_residue_mapped_candidates": 3,
                "rsa_passing_candidates": 184,
            },
            "changed_before_label_distribution_inspection": True,
            "alignment_predicate": {
                "contiguous_gap_free": True,
                "unique_best_window": True,
                "zero_internal_indels": True,
                "minimum_identity": 0.90,
                "protected_residue_letter_match": True,
                "no_mismatch_within_plus_or_minus_one_of_protected": True,
                "requires_at_least_one_residue_mapped_feature": True,
            },
            "deviations": [
                {
                    "original_criterion": "Rule 1: disulfide-only hard protection",
                    "trigger": "2 of 983 domains had a disulfide; none passed the other criteria",
                    "new_criterion": "Rule 2: UniProt ACT_SITE, BINDING, METAL, or DISULFID",
                    "rationale": "The assay largely excludes disulfide-containing domains",
                    "timestamp": "2026-10-17",
                    "not_observed": "No label or ddG distribution for the selected domain",
                },
                {
                    "original_criterion": "Each random fold spans more than 60 mutable positions",
                    "trigger": "2AMI row-random folds covered 59-62 of 62 non-holdout positions",
                    "new_criterion": (
                        "Each random fold covers at least 90% of non-holdout positions"
                    ),
                    "rationale": (
                        "Relative coverage detects position-based defects across domain sizes"
                    ),
                    "timestamp": "2026-10-17",
                    "not_observed": "No label or ddG distribution for 2AMI",
                },
                {
                    "original_criterion": "Exact contiguous UniProt identity of 1.0",
                    "trigger": (
                        "2ROT best window identity was 0.667 with 23 mismatches and an insertion"
                    ),
                    "new_criterion": (
                        "Unique gap-free window, identity >=0.90, no indels, "
                        "protected-letter and adjacency checks"
                    ),
                    "rationale": (
                        "Engineered DMS constructs can differ from UniProt while "
                        "remaining identifiable"
                    ),
                    "timestamp": "2026-10-17",
                    "not_observed": "No label or ddG distribution for any affected candidate",
                },
            ],
        },
        "selection": {
            "ordered_candidates": [candidate.domain_id for candidate in candidates],
            "selection_evaluation": annotations,
            "selected_domain_id": selected.domain_id,
            "length": selected.length,
            "mutable_position_count": len(mutable_positions),
            "variant_count_after_filtering": len(rows),
            "structure_source": selected.structure_path,
            "alignment": asdict(selected_alignment),
            "hard_protected_residues": [asdict(item) for item in selected_protected],
            "soft_protection": {"rule": "RSA < 0.15", "action": "flag_and_penalize_never_refuse"},
        },
        "filters": {
            "raw_corr_min": 0.80,
            "dg_corr_min": 0.80,
            "frac_na_max": 0.10,
            "minimum_single_substitutions": 1000,
            "length_range": [50, 80],
            "requires_bundled_alphafold_structure": True,
        },
        "uniprot": {
            "release": "2026_03",
            "release_date": "2026-09-02",
            "queried_at": "2026-10-17",
            "cache": str(args.uniprot_cache),
        },
        "label_contract": {
            "field": "ddg_kcal_higher_is_more_stable",
            "definition": "deltaG_mut - deltaG_wt",
            "sign_convention": "higher_ddG_is_more_stable",
            "wild_type_anchor": 0.0,
        },
        "filtered_variant_table_sha256": hashlib.sha256(
            canonical_json(row_payload).encode()
        ).hexdigest(),
        "filtered_variant_row_count": len(rows),
        "split": splits,
        "status": "frozen_before_label_distribution_inspection",
        "scientific_use_allowed": False,
    }
    manifest = freeze_manifest(payload, args.output)
    print(
        json.dumps(
            {
                "selected_domain_id": selected.domain_id,
                "length": selected.length,
                "mutable_position_count": len(mutable_positions),
                "variant_count": len(rows),
                "alignment": asdict(selected_alignment),
                "protected_residues": [asdict(item) for item in selected_protected],
                "holdout": splits["holdout"],
                "manifest_digest": manifest.manifest_digest,
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
