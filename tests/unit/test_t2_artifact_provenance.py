"""T2 regressions: artifact identity, immutable serving, and evidence provenance.

Every fixture here is an artificial software label. None of these bytes are
scientific results, and none of these tests download a model or read the frozen
1IGV assets.
"""

from __future__ import annotations

import hashlib
import inspect
import json
from pathlib import Path
from typing import Any

import pytest

from concordia.runtime import esm_checkpoint
from concordia.runtime.model_registry import MODEL_REGISTRY
from concordia.stability import assets
from concordia.stability.measured import MeasuredStabilityEngine
from concordia.storage.content import ContentAddressedStore
from concordia.verification.cross import (
    ClaimRequest,
    ProvenanceArtifact,
    StructureScope,
    verify_claim,
)
from concordia.verification.structure_rules import (
    StructureMeasurements,
    evidence_records,
    verify_measurements,
)

FIXTURE_DIGEST = "0" * 64
FIXTURE_SCOPE = StructureScope(
    complex_id="test-complex",
    receptor_chains=("H", "L"),
    ligand_chains=("A",),
    model_checkpoint="test-only",
    settings_digest=FIXTURE_DIGEST,
    assay="predicted_interface",
)
FIXTURE_CLEAN = StructureMeasurements(
    clash_count=0, variable_domain_fraction=1.0, buried_surface_area=1700
)


# --- 1. Declared checkpoint revisions are enforced in the real loader call ---


def _fake_snapshot(tmp_path: Path, *, weights: bytes, name: str) -> Path:
    snapshot = tmp_path / name
    snapshot.mkdir(parents=True)
    for member in esm_checkpoint.ESM2_FILES:
        (snapshot / member).write_bytes(weights if member == "model.safetensors" else b"{}")
    return snapshot


def test_registry_revision_matches_the_enforced_loader_pin() -> None:
    entry = next(model for model in MODEL_REGISTRY if model["name"] == "ESM-2 650M")
    assert entry["revision"] == esm_checkpoint.ESM2_REVISION


def test_snapshot_fetch_pins_the_declared_revision(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The loader must request the commit explicitly, not a mutable branch ref."""
    weights = b"fixture-weights"
    recorded: dict[str, Any] = {}

    def fake_download(**kwargs: Any) -> str:
        recorded.update(kwargs)
        return str(_fake_snapshot(tmp_path, weights=weights, name=esm_checkpoint.ESM2_REVISION))

    monkeypatch.setattr("huggingface_hub.snapshot_download", fake_download)
    monkeypatch.setattr(
        esm_checkpoint, "ESM2_SAFETENSORS_SHA256", hashlib.sha256(weights).hexdigest()
    )
    snapshot, digests = esm_checkpoint.verified_esm2_snapshot()

    assert recorded["revision"] == esm_checkpoint.ESM2_REVISION
    assert recorded["repo_id"] == esm_checkpoint.ESM2_REPO
    assert set(recorded["allow_patterns"]) == set(esm_checkpoint.ESM2_FILES)
    assert snapshot.name == esm_checkpoint.ESM2_REVISION
    assert digests["model.safetensors"] == hashlib.sha256(weights).hexdigest()


def test_snapshot_resolved_outside_the_declared_revision_is_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An omitted or wrong revision resolves elsewhere; that must not load."""
    monkeypatch.setattr(
        "huggingface_hub.snapshot_download",
        lambda **_: str(_fake_snapshot(tmp_path, weights=b"x", name="main")),
    )
    with pytest.raises(ValueError, match="approved commit"):
        esm_checkpoint.verified_esm2_snapshot()


def test_weight_digest_mismatch_is_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "huggingface_hub.snapshot_download",
        lambda **_: str(
            _fake_snapshot(tmp_path, weights=b"substituted", name=esm_checkpoint.ESM2_REVISION)
        ),
    )
    with pytest.raises(ValueError, match="approved SHA-256"):
        esm_checkpoint.verified_esm2_snapshot()


# --- 2. Trusted digests are validated before unsafe deserialization ---


def _fixture_manifest(root: Path, monkeypatch: pytest.MonkeyPatch, files: dict[str, bytes]) -> None:
    """Install a small synthetic manifest so digest logic is exercised cheaply."""
    payload = {
        "schema_version": 1,
        "kind": "concordia_frozen_1igv_serving_assets",
        "domain": "FIXTURE.pdb",
        "files": {
            name: {"sha256": hashlib.sha256(body).hexdigest(), "size_bytes": len(body)}
            for name, body in files.items()
        },
    }
    raw = json.dumps(payload, sort_keys=True).encode()
    path = root / assets.ASSET_MANIFEST_NAME
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(raw)
    monkeypatch.setattr(assets, "TRUSTED_MANIFEST_SHA256", hashlib.sha256(raw).hexdigest())


def test_repository_manifest_matches_the_pinned_digest() -> None:
    """The checked-in manifest is the one the code trusts; no file hashing needed."""
    manifest = assets.load_trusted_manifest(assets.resolve_asset_root())
    assert manifest["kind"] == "concordia_frozen_1igv_serving_assets"
    assert "data/processed/tsuboyama_ensemble_artifacts.joblib" in manifest["files"]


def test_verified_assets_accept_matching_fixture_bytes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    body = b"fixture asset bytes"
    _fixture_manifest(tmp_path, monkeypatch, {"data/processed/fixture.bin": body})
    (tmp_path / "data/processed").mkdir(parents=True)
    (tmp_path / "data/processed/fixture.bin").write_bytes(body)
    assert assets.verify_assets(tmp_path)["domain"] == "FIXTURE.pdb"


def test_tampered_manifest_is_rejected(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _fixture_manifest(tmp_path, monkeypatch, {"data/processed/fixture.bin": b"body"})
    path = tmp_path / assets.ASSET_MANIFEST_NAME
    path.write_bytes(path.read_bytes().replace(b"FIXTURE.pdb", b"SWAPPED.pdb"))
    with pytest.raises(ValueError, match="differs from the pinned version"):
        assets.verify_assets(tmp_path)


def test_missing_asset_is_named(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _fixture_manifest(tmp_path, monkeypatch, {"data/processed/fixture.bin": b"body"})
    with pytest.raises(FileNotFoundError, match="data/processed/fixture.bin"):
        assets.verify_assets(tmp_path)


def test_tampered_asset_of_equal_size_is_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Size alone cannot stand in for content; this is the joblib threat model."""
    _fixture_manifest(tmp_path, monkeypatch, {"data/processed/fixture.bin": b"trusted"})
    (tmp_path / "data/processed").mkdir(parents=True)
    (tmp_path / "data/processed/fixture.bin").write_bytes(b"swapped")
    with pytest.raises(ValueError, match="digest mismatch"):
        assets.verify_assets(tmp_path)


def test_truncated_asset_is_rejected_on_size(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _fixture_manifest(tmp_path, monkeypatch, {"data/processed/fixture.bin": b"trusted"})
    (tmp_path / "data/processed").mkdir(parents=True)
    (tmp_path / "data/processed/fixture.bin").write_bytes(b"trunc")
    with pytest.raises(ValueError, match="size mismatch"):
        assets.verify_assets(tmp_path)


def test_manifest_escaping_the_asset_root_is_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _fixture_manifest(tmp_path, monkeypatch, {"../outside.bin": b"body"})
    with pytest.raises(ValueError, match="invalid asset path"):
        assets.verify_assets(tmp_path)


def test_digests_are_verified_before_joblib_load() -> None:
    """Ordering is the whole guarantee: unpickling untrusted bytes is the risk."""
    source = inspect.getsource(MeasuredStabilityEngine.__init__)
    assert source.index("verify_assets") < source.index("joblib.load")


# --- 3. Serving initialization is immutable ---


def test_engine_refuses_overridden_individual_artifact_paths(tmp_path: Path) -> None:
    """Callers select a verified root, never a single unverified file."""
    with pytest.raises(ValueError, match="cannot be overridden"):
        MeasuredStabilityEngine(manifest_path=tmp_path / "manifest.json")


def test_engine_initialization_does_not_recalibrate_or_write() -> None:
    source = inspect.getsource(MeasuredStabilityEngine.__init__)
    for mutation in ("_recalibrate_t2", "write_text", "write_bytes", "to_json", "joblib.dump"):
        assert mutation not in source


# --- 4. Caller-supplied metrics cannot self-certify execution ---


def test_supplied_measurements_are_rule_assessment_only() -> None:
    measured = FIXTURE_CLEAN.model_copy(
        update={
            "second_model_interface_agreement": 0.7,
            "perturbed_paratope_interface_agreement": 0.0,
        }
    )
    result = verify_measurements(measured, FIXTURE_SCOPE, claim_text="software test")
    assert result.scientific_use_allowed is False
    assert "caller-supplied measurements have no verified execution provenance" in result.reasons
    assert "Rule assessment only" in result.limitation


# --- 5. Executed-evidence claims require stored execution artifacts ---


def _structure_claim(tmp_path: Path, *, with_execution: bool):
    store = ContentAddressedStore(tmp_path)

    def envelope(kind: str, parents: tuple[str, ...] = (), payload: Any = None) -> str:
        return store.put_json(
            ProvenanceArtifact(
                kind=kind,
                payload_digest=store.put_json(payload or {"test_only": True, "kind": kind}),
                dependencies=parents,
                execution_mode="real",
                scientific_use_allowed=True,
                source="software acceptance test with artificial bytes",
                producing_tool="test-structure-v1",
            ).model_dump(mode="json")
        )

    source = envelope("sequence")
    if with_execution:
        parent = envelope(
            "execution",
            (source,),
            {
                "request_artifact_digest": store.put_json({"test_only": True, "request": "mock"}),
                "response_artifact_digest": store.put_json({"test_only": True, "response": "mock"}),
            },
        )
    else:
        parent = source
    measured = FIXTURE_CLEAN.model_copy(
        update={
            "second_model_interface_agreement": 0.7,
            "perturbed_paratope_interface_agreement": 0.0,
        }
    )
    artifacts = {
        name: envelope("evidence", (parent,))
        for name in ("physical", "samples", "second_model", "counterfactual", "reference")
    }
    claim = ClaimRequest(
        claim_id="test-complex",
        text="software test",
        scope=FIXTURE_SCOPE,
        source_sequence=source,
        evidence=evidence_records(measured, FIXTURE_SCOPE, artifacts),
    )
    return verify_claim(claim, store)


def test_retained_execution_artifacts_allow_a_supported_structure_claim(tmp_path: Path) -> None:
    result = _structure_claim(tmp_path, with_execution=True)
    assert result.status == "SUPPORTED"
    assert result.scientific_use_allowed is True


def test_structure_claim_without_stored_execution_is_not_supported(tmp_path: Path) -> None:
    result = _structure_claim(tmp_path, with_execution=False)
    assert result.status != "SUPPORTED"
    assert result.scientific_use_allowed is False
    reasons = [reason for check in result.checks for reason in check.reasons]
    assert any("lacks a stored execution artifact" in reason for reason in reasons)
