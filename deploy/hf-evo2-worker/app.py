from __future__ import annotations

import platform
from typing import Any

import gradio as gr
import spaces
import torch

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
                torch.cuda.is_bf16_supported()
                and total_memory >= DECLARED_MINIMUM_VRAM_BYTES
            ),
        }
    )
    return payload


@spaces.GPU(duration=45)
def probe_gpu() -> dict[str, Any]:
    """Return bounded device metadata from a real ZeroGPU allocation."""

    return _probe_payload()


with gr.Blocks(title="Concordia Evo2 Forward Worker") as demo:
    gr.Markdown(
        "# Concordia Evo2 Forward Worker\n"
        "Run a bounded hardware probe before installing or executing Evo2. "
        "This produces no scientific evidence."
    )
    run_button = gr.Button("Run GPU capability probe", variant="primary")
    result = gr.JSON(label="Qualification record")
    run_button.click(fn=probe_gpu, outputs=result, api_name="probe_gpu")


if __name__ == "__main__":
    demo.launch()
