"""Local scientist runtime diagnostics."""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

import yaml


def check_local_runtime(config_path: str | Path) -> dict[str, Any]:
    """Report prerequisites without downloading models or contacting remote services."""
    config = yaml.safe_load(Path(config_path).read_text(encoding="utf-8"))
    executable = shutil.which("ollama")
    result: dict[str, Any] = {
        "runtime": config.get("runtime"),
        "model": config.get("model"),
        "host": config.get("host"),
        "cloud_disabled": os.environ.get("OLLAMA_NO_CLOUD") == "1",
        "ollama_executable": executable,
        "server_reachable": False,
        "installed_models": [],
    }
    if executable is None:
        result["message"] = "Install Ollama locally before model qualification."
        return result
    try:
        completed = subprocess.run(
            [executable, "list"], capture_output=True, text=True, timeout=5, check=False
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        result["message"] = f"Ollama could not be queried: {error}"
        return result
    if completed.returncode == 0:
        result["server_reachable"] = True
        lines = completed.stdout.splitlines()
        result["installed_models"] = [line.split()[0] for line in lines[1:] if line.strip()]
        model = config.get("model")
        configured_present = model in result["installed_models"]
        result["configured_model_present"] = configured_present
        expected_digest = config.get("checkpoint_sha256")
        result["checkpoint_sha256"] = expected_digest
        if configured_present and expected_digest:
            shown = subprocess.run(
                [executable, "show", str(model), "--modelfile"],
                capture_output=True,
                text=True,
                timeout=5,
                check=False,
            )
            match = re.search(r"^FROM[^\n]*sha256-([0-9a-f]{64})", shown.stdout, re.MULTILINE)
            installed_digest = match.group(1) if match else None
            result["installed_checkpoint_sha256"] = installed_digest
            result["checkpoint_matches"] = installed_digest == expected_digest
        if configured_present and result.get("checkpoint_matches") is True:
            result["message"] = "Qualified local model and pinned checkpoint are ready."
        elif configured_present:
            result["message"] = "Configured model is present but its checkpoint is not verified."
        else:
            result["message"] = "Configured model is not installed."
    else:
        result["message"] = "Ollama is installed but its local server is not reachable."
        result["error"] = completed.stderr.strip() or completed.stdout.strip()
    return result
