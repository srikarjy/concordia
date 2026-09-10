from __future__ import annotations

import hashlib
import importlib.util
from pathlib import Path
from types import ModuleType

ROOT = Path(__file__).resolve().parents[2]


def load_qualification_module() -> ModuleType:
    path = ROOT / "deploy/hf-evo2-worker/qualification.py"
    spec = importlib.util.spec_from_file_location("evo2_worker_qualification", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_verify_file_hashes_opaque_bytes_without_loading_them(tmp_path: Path) -> None:
    module = load_qualification_module()
    artifact = tmp_path / "checkpoint.pt"
    artifact.write_bytes(b"opaque serialized bytes")
    expected = {
        "filename": "checkpoint.pt",
        "byte_size": artifact.stat().st_size,
        "sha256": hashlib.sha256(artifact.read_bytes()).hexdigest(),
    }

    record = module.verify_file(artifact, expected)

    assert record["verified"]
    assert record["actual_sha256"] == expected["sha256"]


def test_verify_file_fails_closed_for_missing_or_changed_bytes(tmp_path: Path) -> None:
    module = load_qualification_module()
    artifact = tmp_path / "checkpoint.pt"
    expected = {"filename": "checkpoint.pt", "byte_size": 4, "sha256": "0" * 64}

    missing = module.verify_file(artifact, expected)
    artifact.write_bytes(b"data")
    changed = module.verify_file(artifact, expected)

    assert not missing["verified"]
    assert not changed["verified"]
    assert changed["size_matches"]
    assert not changed["sha256_matches"]


def test_runtime_record_cannot_imply_execution_or_scientific_use(tmp_path: Path) -> None:
    module = load_qualification_module()
    selected_paths: dict[str, Path] = {}
    for label in module.EXPECTED_FILES:
        path = tmp_path / label
        path.write_bytes(b"not the selected artifact")
        selected_paths[label] = path

    record = module.build_runtime_qualification(
        selected_paths,
        python_version=module.EXPECTED_PYTHON_VERSION,
        torch_version="2.8.0+cu128",
        package_versions={"evo2": "0.6.0", "vtx": "1.1.0", "flash-attn": "2.8.3"},
        imports_succeeded=True,
    )

    assert not record["runtime_qualified"]
    assert not record["checkpoint_deserialized"]
    assert not record["model_loaded"]
    assert not record["forward_pass_executed"]
    assert record["execution_status"] == "NOT_RUN"
    assert not record["scientific_use_allowed"]


def test_passing_runtime_qualification_still_does_not_execute(tmp_path: Path) -> None:
    module = load_qualification_module()
    selected_paths: dict[str, Path] = {}
    expected_files = {}
    for label in module.EXPECTED_FILES:
        content = f"selected {label}".encode()
        path = tmp_path / label
        path.write_bytes(content)
        selected_paths[label] = path
        expected_files[label] = {
            "filename": label,
            "byte_size": len(content),
            "sha256": hashlib.sha256(content).hexdigest(),
        }
    module.EXPECTED_FILES = expected_files

    record = module.build_runtime_qualification(
        selected_paths,
        python_version=module.EXPECTED_PYTHON_VERSION,
        torch_version="2.8.0+cu128",
        package_versions={"evo2": "0.6.0", "vtx": "1.1.0", "flash-attn": "2.8.3"},
        imports_succeeded=True,
    )

    assert record["runtime_qualified"]
    assert record["execution_status"] == "NOT_RUN"
    assert not record["scientific_use_allowed"]
