from __future__ import annotations

import hashlib
import platform
from collections.abc import Mapping
from importlib import metadata
from pathlib import Path
from typing import Any

SCHEMA_VERSION = 2
EVO2_REPOSITORY = "https://github.com/ArcInstitute/evo2.git"
EVO2_REVISION = "53f195997257c56c00e5ef8d33a54f5baad143a6"
EVO2_VERSION = "0.6.0"
VTX_VERSION = "1.1.0"
FLASH_ATTN_VERSION = "2.8.3"
FLASH_ATTN_WHEEL_SHA256 = "f25da18657a87fc83dc1bfb8b7751b82246e9db355510226b674fd437c34b5fb"
CHECKPOINT_REPOSITORY = "arcinstitute/evo2_7b"
CHECKPOINT_REVISION = "bda0089f92582d5baabf0f22d9fc85f3588f6b58"

EXPECTED_PYTHON_VERSION = "3.12.12"
EXPECTED_TORCH_VERSION_PREFIX = "2.8.0"
EXPECTED_PACKAGE_VERSIONS = {
    "evo2": EVO2_VERSION,
    "vtx": VTX_VERSION,
    "flash-attn": FLASH_ATTN_VERSION,
}

EXPECTED_FILES = {
    "checkpoint": {
        "filename": "evo2_7b.pt",
        "byte_size": 13_766_621_200,
        "sha256": "c66645929dc1b9c631f5be656da8726f38946315dc9167000a615dd626fcecf4",
    },
    "checkpoint_config": {
        "filename": "config.json",
        "byte_size": 87,
        "sha256": "7f2e195e156de678b6d7db090dca19b37e88671f72ea7c9e1866e103946b69b2",
    },
    "evo2_models_source": {
        "filename": "evo2/models.py",
        "byte_size": 12_471,
        "sha256": "0b757fcc42b37a52b0c3f508e876a52356331392ae8aa16a923576265043b78c",
    },
    "evo2_scoring_source": {
        "filename": "evo2/scoring.py",
        "byte_size": 7_456,
        "sha256": "17e6985cef3a62c2a488133ab5a65050dcf0abeec2f55d1c0b068dfe37c44de6",
    },
    "evo2_model_config": {
        "filename": "evo2/configs/evo2-7b-1m.yml",
        "byte_size": 1_764,
        "sha256": "9637f84ffd796f42cce3f926832b3999ff34a82686beba04505327162b288b1a",
    },
}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(8 * 1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def verify_file(path: Path, expected: Mapping[str, Any]) -> dict[str, Any]:
    """Verify one selected file as bytes without deserializing its content."""

    record: dict[str, Any] = {
        "filename": expected["filename"],
        "expected_byte_size": expected["byte_size"],
        "expected_sha256": expected["sha256"],
        "present": False,
        "size_matches": False,
        "sha256_matches": False,
        "verified": False,
    }
    try:
        if not path.is_file():
            record["error"] = "selected file is missing or is not a regular file"
            return record
        actual_size = path.stat().st_size
        actual_sha256 = _sha256(path)
    except OSError as exc:
        record["error"] = f"file verification failed: {type(exc).__name__}"
        return record

    record.update(
        {
            "present": True,
            "actual_byte_size": actual_size,
            "actual_sha256": actual_sha256,
            "size_matches": actual_size == expected["byte_size"],
            "sha256_matches": actual_sha256 == expected["sha256"],
        }
    )
    record["verified"] = bool(record["size_matches"] and record["sha256_matches"])
    return record


def installed_package_versions() -> dict[str, str | None]:
    versions: dict[str, str | None] = {}
    for package_name in EXPECTED_PACKAGE_VERSIONS:
        try:
            versions[package_name] = metadata.version(package_name)
        except metadata.PackageNotFoundError:
            versions[package_name] = None
    return versions


def build_runtime_qualification(
    selected_paths: Mapping[str, Path],
    *,
    python_version: str | None = None,
    torch_version: str,
    torch_cxx11_abi: bool | None = None,
    package_versions: Mapping[str, str | None] | None = None,
    imports_succeeded: bool,
    import_error: str | None = None,
) -> dict[str, Any]:
    """Build a fail-closed, non-scientific runtime qualification record."""

    measured_python = python_version or platform.python_version()
    measured_packages = dict(package_versions or installed_package_versions())
    files = {
        label: verify_file(selected_paths.get(label, Path("")), expected)
        for label, expected in EXPECTED_FILES.items()
    }
    version_checks = {
        "python": measured_python == EXPECTED_PYTHON_VERSION,
        "torch": torch_version.startswith(EXPECTED_TORCH_VERSION_PREFIX),
        **{
            package_name: measured_packages.get(package_name) == expected_version
            for package_name, expected_version in EXPECTED_PACKAGE_VERSIONS.items()
        },
    }
    runtime_qualified = bool(
        imports_succeeded
        and all(version_checks.values())
        and all(record["verified"] for record in files.values())
    )
    record: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "purpose": "evo2_7b_runtime_and_checkpoint_qualification",
        "source": {
            "repository_url": EVO2_REPOSITORY,
            "revision": EVO2_REVISION,
            "package_version": EVO2_VERSION,
        },
        "flash_attention": {
            "version": FLASH_ATTN_VERSION,
            "wheel_sha256": FLASH_ATTN_WHEEL_SHA256,
            "wheel_platform": "cu12-torch2.8-cxx11abiTRUE-cp312-linux_x86_64",
        },
        "checkpoint": {
            "repository_id": CHECKPOINT_REPOSITORY,
            "revision": CHECKPOINT_REVISION,
            "filename": EXPECTED_FILES["checkpoint"]["filename"],
        },
        "runtime": {
            "python_version": measured_python,
            "torch_version": torch_version,
            "torch_cxx11_abi": torch_cxx11_abi,
            "libc": list(platform.libc_ver()),
            "package_versions": measured_packages,
            "version_checks": version_checks,
            "imports_succeeded": imports_succeeded,
        },
        "files": files,
        "runtime_qualified": runtime_qualified,
        "checkpoint_deserialized": False,
        "model_loaded": False,
        "forward_pass_executed": False,
        "execution_status": "NOT_RUN",
        "scientific_use_allowed": False,
        "limitations": [
            "This qualification hashes checkpoint bytes but never deserializes them.",
            "A passing result does not establish model loading or numerical compatibility.",
            "No sequence is accepted and no scientific result is produced.",
        ],
    }
    if import_error is not None:
        record["runtime"]["import_error"] = import_error
    return record
