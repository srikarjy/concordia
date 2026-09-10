from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from concordia.virtual_cell.cellxgene import H5adSummary
from concordia.virtual_cell.state_release import (
    StateDatasetSchema,
    StateReleaseFile,
    StateReleaseFileRole,
    StateReleaseSelection,
    StateReleaseVerifier,
    StateTermsAcceptance,
)

ROOT = Path(__file__).resolve().parents[2]


class FixtureInspector:
    def __init__(self, summary: H5adSummary):
        self.summary = summary
        self.calls: list[tuple[Path, str, str]] = []

    def inspect(
        self,
        path: Path,
        *,
        perturbation_key: str,
        cell_context_key: str,
    ) -> H5adSummary:
        self.calls.append((path, perturbation_key, cell_context_key))
        return self.summary


def digest(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def release(tmp_path: Path) -> tuple[Path, StateReleaseSelection, H5adSummary]:
    root = tmp_path / "release"
    root.mkdir()
    files: list[StateReleaseFile] = []
    for role in StateReleaseFileRole:
        suffix = ".h5ad" if role is StateReleaseFileRole.DATASET else ".bin"
        relative = f"selected/{role.value}{suffix}"
        payload = f"fixed-{role.value}".encode()
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(payload)
        files.append(
            StateReleaseFile(
                role=role,
                path=relative,
                byte_size=len(payload),
                sha256=digest(payload),
                media_type=(
                    "application/x-hdf5"
                    if role is StateReleaseFileRole.DATASET
                    else "application/octet-stream"
                ),
            )
        )
    summary = H5adSummary(
        cell_count=8,
        gene_count=3,
        gene_order_digest=digest(b"genes"),
        obs_schema_digest=digest(b"obs"),
        perturbation_counts={"GENE1": 5, "non-targeting": 3},
        cell_context_values=("k562",),
        h5ad_schema_version="unknown",
        title="fixture",
    )
    selection = StateReleaseSelection(
        repository_id="arcinstitute/ST-HVG-Replogle",
        repository_url="https://huggingface.co/arcinstitute/ST-HVG-Replogle",
        revision="a" * 40,
        selected_on="2026-09-10",
        terms=StateTermsAcceptance(accepted_on="2026-09-10"),
        files=tuple(files),
        dataset=StateDatasetSchema(
            cell_count=8,
            gene_count=3,
            gene_order_digest=summary.gene_order_digest,
            observation_schema_digest=summary.obs_schema_digest,
            cell_context_column="cell_line",
            cell_context_value="k562",
            perturbation_column="gene",
            control_label="non-targeting",
            control_count=3,
        ),
    )
    return root, selection, summary


def test_state_release_verifies_bytes_and_h5ad_without_running_model(tmp_path: Path) -> None:
    root, selection, summary = release(tmp_path)
    inspector = FixtureInspector(summary)

    result = StateReleaseVerifier(inspector).verify(root, selection)

    assert result.release_verified
    assert result.model_terms_accepted
    assert result.use_scope == "NON_COMMERCIAL"
    assert not result.commercial_use_allowed
    assert result.execution_status == "NOT_RUN"
    assert not result.scientific_use_allowed
    assert result.dataset.control_count == 3
    assert inspector.calls == [
        (root / selection.file_for(StateReleaseFileRole.DATASET).path, "gene", "cell_line")
    ]


def test_state_release_rejects_missing_file(tmp_path: Path) -> None:
    root, selection, summary = release(tmp_path)
    (root / selection.file_for(StateReleaseFileRole.CHECKPOINT).path).unlink()

    with pytest.raises(ValueError, match="missing"):
        StateReleaseVerifier(FixtureInspector(summary)).verify(root, selection)


def test_state_release_rejects_hash_mismatch(tmp_path: Path) -> None:
    root, selection, summary = release(tmp_path)
    path = root / selection.file_for(StateReleaseFileRole.CHECKPOINT).path
    path.write_bytes(b"x" * path.stat().st_size)

    with pytest.raises(ValueError, match="hash mismatch"):
        StateReleaseVerifier(FixtureInspector(summary)).verify(root, selection)


def test_state_release_rejects_size_mismatch(tmp_path: Path) -> None:
    root, selection, summary = release(tmp_path)
    path = root / selection.file_for(StateReleaseFileRole.CONFIG).path
    path.write_bytes(path.read_bytes() + b"x")

    with pytest.raises(ValueError, match="size mismatch"):
        StateReleaseVerifier(FixtureInspector(summary)).verify(root, selection)


def test_state_release_rejects_symlink_escape(tmp_path: Path) -> None:
    root, selection, summary = release(tmp_path)
    expected = selection.file_for(StateReleaseFileRole.CHECKPOINT)
    path = root / expected.path
    payload = path.read_bytes()
    path.unlink()
    outside = tmp_path / "outside.ckpt"
    outside.write_bytes(payload)
    path.symlink_to(outside)

    with pytest.raises(ValueError, match="symlink"):
        StateReleaseVerifier(FixtureInspector(summary)).verify(root, selection)


def test_state_release_rejects_path_traversal() -> None:
    with pytest.raises(ValidationError, match="canonical and relative"):
        StateReleaseFile(
            role=StateReleaseFileRole.CHECKPOINT,
            path="../best.ckpt",
            byte_size=1,
            sha256="a" * 64,
            media_type="application/octet-stream",
        )


@pytest.mark.parametrize(
    ("summary_update", "message"),
    [
        ({"cell_count": 9}, "shape"),
        ({"gene_order_digest": "f" * 64}, "gene-order"),
        ({"obs_schema_digest": "e" * 64}, "observation-schema"),
        ({"cell_context_values": ("other",)}, "cell context"),
        ({"perturbation_counts": {"GENE1": 8}}, "control population"),
    ],
)
def test_state_release_rejects_h5ad_mismatch(
    tmp_path: Path,
    summary_update: dict[str, object],
    message: str,
) -> None:
    root, selection, summary = release(tmp_path)
    mismatched = summary.model_copy(update=summary_update)

    with pytest.raises(ValueError, match=message):
        StateReleaseVerifier(FixtureInspector(mismatched)).verify(root, selection)


def test_zerogpu_probe_record_is_not_an_evo2_execution() -> None:
    record = json.loads(
        (ROOT / "reports/evo2-zerogpu-hardware-probe.json").read_text(encoding="utf-8")
    )

    assert record["candidate_environment"]
    assert not record["evo2_installed"]
    assert not record["forward_pass_executed"]
    assert record["execution_status"] == "NOT_RUN"
    assert not record["scientific_use_allowed"]
