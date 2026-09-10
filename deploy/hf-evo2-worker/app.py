from __future__ import annotations

import importlib.util
import platform
from pathlib import Path
from typing import Any

import gradio as gr
import spaces
import torch
from huggingface_hub import hf_hub_download
from qualification import (
    CHECKPOINT_REPOSITORY,
    CHECKPOINT_REVISION,
    build_runtime_qualification,
    installed_package_versions,
)

SCHEMA_VERSION = 1
DECLARED_MINIMUM_VRAM_BYTES = 40 * 1024**3


def _probe_payload() -> dict[str, Any]:
    cuda_available = torch.cuda.is_available()
    payload: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "purpose": "evo2_7b_forward_hardware_qualification",
        "python_version": platform.python_version(),
        "torch_version": torch.__version__,
        "cuda_runtime_version": torch.version.cuda,
        "cuda_available": cuda_available,
        "declared_minimum_vram_bytes": DECLARED_MINIMUM_VRAM_BYTES,
        "candidate_environment": False,
        "scientific_use_allowed": False,
        "limitations": [
            "This probe does not load Evo2 or execute a forward pass.",
            "Hardware capacity does not establish runtime or numerical compatibility.",
            "No genomic or biological conclusion can be drawn from this record.",
        ],
    }
    if not cuda_available:
        payload["failure_reason"] = "CUDA is unavailable inside the allocated GPU function."
        return payload

    device = torch.cuda.current_device()
    properties = torch.cuda.get_device_properties(device)
    total_memory = int(properties.total_memory)
    payload.update(
        {
            "device_index": device,
            "device_name": properties.name,
            "compute_capability": [properties.major, properties.minor],
            "total_memory_bytes": total_memory,
            "bf16_supported": bool(torch.cuda.is_bf16_supported()),
            "candidate_environment": bool(
                torch.cuda.is_bf16_supported() and total_memory >= DECLARED_MINIMUM_VRAM_BYTES
            ),
        }
    )
    return payload


@spaces.GPU(duration=45)
def probe_gpu() -> dict[str, Any]:
    """Return bounded device metadata from a real ZeroGPU allocation."""

    return _probe_payload()


def _evo2_package_root() -> Path:
    spec = importlib.util.find_spec("evo2")
    if spec is None or not spec.submodule_search_locations:
        raise RuntimeError("The pinned Evo2 package is not importable.")
    return Path(next(iter(spec.submodule_search_locations)))


def qualify_runtime() -> dict[str, Any]:
    """Verify pinned runtime and checkpoint bytes without loading the model."""

    selected_paths: dict[str, Path] = {}
    imports_succeeded = False
    import_error: str | None = None
    try:
        checkpoint_path = hf_hub_download(
            repo_id=CHECKPOINT_REPOSITORY,
            filename="evo2_7b.pt",
            revision=CHECKPOINT_REVISION,
            local_files_only=True,
        )
        checkpoint_config_path = hf_hub_download(
            repo_id=CHECKPOINT_REPOSITORY,
            filename="config.json",
            revision=CHECKPOINT_REVISION,
            local_files_only=True,
        )
        package_root = _evo2_package_root()
        selected_paths = {
            "checkpoint": Path(checkpoint_path),
            "checkpoint_config": Path(checkpoint_config_path),
            "evo2_models_source": package_root / "models.py",
            "evo2_scoring_source": package_root / "scoring.py",
            "evo2_model_config": package_root / "configs/evo2-7b-1m.yml",
        }
        __import__("evo2")
        __import__("vortex")
        imports_succeeded = True
    except Exception as exc:
        import_error = f"{type(exc).__name__}: {exc}"

    return build_runtime_qualification(
        selected_paths,
        torch_version=torch.__version__,
        torch_cxx11_abi=torch.compiled_with_cxx11_abi(),
        package_versions=installed_package_versions(),
        imports_succeeded=imports_succeeded,
        import_error=import_error,
    )


with gr.Blocks(title="Concordia Evo2 Forward Worker") as demo:
    gr.Markdown(
        "# Concordia Evo2 Forward Worker\n"
        "Run bounded hardware and runtime checks before executing Evo2. "
        "Neither check loads the model or produces scientific evidence."
    )
    runtime_button = gr.Button("Verify pinned runtime and checkpoint", variant="primary")
    run_button = gr.Button("Run GPU capability probe")
    result = gr.JSON(label="Qualification record")
    runtime_button.click(fn=qualify_runtime, outputs=result, api_name="qualify_runtime")
    run_button.click(fn=probe_gpu, outputs=result, api_name="probe_gpu")


if __name__ == "__main__":
    demo.launch()
