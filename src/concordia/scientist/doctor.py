"""Local scientist runtime diagnostics."""

from __future__ import annotations

import os
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
        result["configured_model_present"] = config.get("model") in result["installed_models"]
        result["message"] = "Runtime is reachable; qualify the configured model before collection."
    else:
        result["message"] = "Ollama is installed but its local server is not reachable."
        result["error"] = completed.stderr.strip() or completed.stdout.strip()
    return result
