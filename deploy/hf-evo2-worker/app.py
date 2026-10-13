from __future__ import annotations

import importlib.util
import platform
from copy import deepcopy
from functools import lru_cache
from pathlib import Path
from typing import Any

import gradio as gr
import numpy as np
import spaces
import torch
from huggingface_hub import hf_hub_download
from qualification import (
    CHECKPOINT_REPOSITORY,
    CHECKPOINT_REVISION,
    build_runtime_qualification,
    installed_package_versions,
)
from scoring import score_causal_logits, unwrap_logits, validate_protocol_sequence

SCHEMA_VERSION = 1
DECLARED_MINIMUM_VRAM_BYTES = 40 * 1024**3
FORWARD_MODEL_CHECKPOINT = f"{CHECKPOINT_REPOSITORY}@{CHECKPOINT_REVISION}/evo2_7b.pt"
FORWARD_TARGET = "mean_next_base_log_likelihood"


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


@lru_cache(maxsize=1)
def _qualify_runtime_once() -> dict[str, Any]:
    """Verify the immutable deployed runtime once without loading the model."""

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
        import_error = f"{type(exc).__name__}: runtime verification failed"

    return build_runtime_qualification(
        selected_paths,
        torch_version=torch.__version__,
        torch_cxx11_abi=torch.compiled_with_cxx11_abi(),
        package_versions=installed_package_versions(),
        imports_succeeded=imports_succeeded,
        import_error=import_error,
    )


def qualify_runtime() -> dict[str, Any]:
    """Return a copy of the process-cached immutable qualification record."""

    return deepcopy(_qualify_runtime_once())


@lru_cache(maxsize=1)
def _load_evo2_model_once() -> Any:
    """Load the pinned Evo2 7B checkpoint once per container lifetime.

    UNVERIFIED: this has never been executed anywhere in this project. Every
    prior qualification step (``probe_gpu``, ``qualify_runtime``) stopped
    short of this call deliberately. The constructor call below follows the
    pinned Evo2 repository's documented usage pattern
    (``from evo2 import Evo2; Evo2('evo2_7b')``) but has not been confirmed
    against the live Space. If this fails, the fix almost certainly belongs
    here, not in the scoring math in ``scoring.py`` (which is unit-tested
    independently of hardware).
    """

    from evo2 import Evo2

    return Evo2("evo2_7b")


def _tokenize(model: Any, sequence: str) -> list[int]:
    """Tokenize under the frozen CharLevelTokenizer-vocab-512 contract.

    UNVERIFIED: tries the documented ``tokenizer.tokenize`` method first and
    falls back to ``tokenizer.encode`` (seen in other tokenizer APIs in this
    ecosystem) only if the first call raises ``AttributeError``. Whichever
    path actually works should be confirmed against the live Space and this
    fallback simplified once it is.
    """

    tokenizer = model.tokenizer
    if hasattr(tokenizer, "tokenize"):
        return list(tokenizer.tokenize(sequence))
    return list(tokenizer.encode(sequence))


def _forward_pass_logits(model: Any, token_ids: list[int]) -> np.ndarray:
    """Run one forward pass and return float64 logits as a NumPy array.

    UNVERIFIED: the exact call signature (``model(input_ids)`` returning a
    ``(logits, embeddings)`` tuple with ``logits`` shaped
    ``(batch, length, vocab)``) matches the pinned repository's documented
    README usage, not a confirmed local run.
    """

    input_ids = torch.tensor(token_ids, dtype=torch.int).unsqueeze(0).to("cuda:0")
    with torch.no_grad():
        outputs = model(input_ids)
    logits = unwrap_logits(outputs)
    return logits[0].float().cpu().numpy().astype(np.float64, copy=False)


@spaces.GPU(duration=300)
def score_sequence(sequence: str) -> dict[str, Any]:
    """Run one real Evo2 7B forward pass under the frozen scoring protocol.

    The duration budget (300s, ZeroGPU's typical ceiling) is a guess sized
    for a cold-start 13.77GB checkpoint load plus one forward pass; it has
    never been measured. If real runs consistently finish well under this or
    time out before completing, tune this value from observed
    ``elapsed_seconds`` in successful and failed runs.

    UNVERIFIED end to end. This is the first code in this project that
    attempts to load the checkpoint and execute a forward pass; nothing here
    can be exercised without a live ZeroGPU allocation. Every failure mode is
    reported as a typed, fail-closed record rather than raising, so a caller
    always gets a structured ``execution_status`` instead of an opaque
    traceback. ``scientific_use_allowed`` is always False here: scope
    eligibility (checkpoint identity, exact window length, scored-token
    count) is decided by the calling adapter
    (``concordia.genomics.evo2_zerogpu.ZeroGpuEvo2ForwardRunner``), which can
    be tested without a GPU, not by this function.
    """

    base_record: dict[str, Any] = {
        "schema_version": 1,
        "model_checkpoint": FORWARD_MODEL_CHECKPOINT,
        "target": FORWARD_TARGET,
        "scientific_use_allowed": False,
    }

    error = validate_protocol_sequence(sequence)
    if error is not None:
        return {**base_record, "execution_status": "FAILED_VALIDATION", "error": error}

    try:
        model = _load_evo2_model_once()
    except Exception as exc:  # noqa: BLE001 - fail closed with a typed record
        return {
            **base_record,
            "execution_status": "FAILED_MODEL_LOAD",
            "error": f"{type(exc).__name__}: model load failed",
        }

    normalized = sequence.strip().upper()
    try:
        token_ids = _tokenize(model, normalized)
    except Exception as exc:  # noqa: BLE001
        return {
            **base_record,
            "execution_status": "FAILED_TOKENIZATION",
            "error": f"{type(exc).__name__}: tokenization failed",
        }

    try:
        logits = _forward_pass_logits(model, token_ids)
    except Exception as exc:  # noqa: BLE001
        return {
            **base_record,
            "execution_status": "FAILED_FORWARD_PASS",
            "error": f"{type(exc).__name__}: forward pass failed",
        }

    try:
        scored = score_causal_logits(logits, token_ids)
    except ValueError as exc:
        return {
            **base_record,
            "execution_status": "FAILED_SCORING",
            "error": str(exc),
        }

    return {
        **base_record,
        "execution_status": "COMPLETED",
        "sequence_length": len(normalized),
        "token_ids": token_ids,
        **scored,
    }


def _spearman(a: list[float], b: list[float]) -> float:
    ra = np.argsort(np.argsort(a)).astype(np.float64)
    rb = np.argsort(np.argsort(b)).astype(np.float64)
    return float(np.corrcoef(ra, rb)[0, 1])


def _make_autograd_safe(inner: Any) -> None:
    """Re-materialize inference-mode weights as normal tensors, once per container."""

    if getattr(inner, "_concordia_autograd_safe", False):
        return
    with torch.inference_mode(False):
        for module in inner.modules():
            for name, parameter in list(module._parameters.items()):
                if parameter is not None:
                    module._parameters[name] = torch.nn.Parameter(
                        parameter.detach().clone(), requires_grad=False
                    )
            for name, buffer in list(module._buffers.items()):
                if buffer is not None:
                    module._buffers[name] = buffer.detach().clone()
    inner._concordia_autograd_safe = True


def _total_log_likelihood(
    inner: Any, embeddings: torch.Tensor, tokens: torch.Tensor, *, checkpointed: bool
) -> torch.Tensor:
    """Summed next-base log-likelihood, optionally with activation checkpointing."""

    from torch.utils.checkpoint import checkpoint

    hidden = embeddings
    for block in inner.blocks:
        if checkpointed:
            hidden = checkpoint(
                lambda value, block=block: block(
                    value, inference_params=None, padding_mask=None
                )[0],
                hidden,
                use_reentrant=False,
            )
        else:
            hidden, _ = block(hidden, inference_params=None, padding_mask=None)
    hidden = inner.norm(hidden.to(inner.block_idx_to_device[0]))
    logits = inner.unembed(hidden)[0, :-1].float()
    log_probabilities = torch.log_softmax(logits, dim=-1)
    targets = tokens[0, 1:].long()
    return log_probabilities.gather(1, targets[:, None]).sum()


@spaces.GPU(duration=300)
def attribute_sequence(sequence: str, check_pairs: int = 24) -> dict[str, Any]:
    """Forward score AND gradient attribution for one frozen-protocol window.

    Same input contract as ``score_sequence`` (exactly 8,192 A/C/G/T bases).
    Backward runs with activation checkpointing, since the full window does not
    fit otherwise. For every position it returns a first-order estimate of the
    change in total log-likelihood for each of the three alternative bases, and
    it checks that estimate against exact rescoring at the middle position plus a
    seeded sample of other positions.
    """

    import time

    base_record: dict[str, Any] = {
        "schema_version": 1,
        "model_checkpoint": FORWARD_MODEL_CHECKPOINT,
        "target": FORWARD_TARGET,
        "attribution_method": "gradient_x_embedding_difference_first_order",
        "scientific_use_allowed": False,
    }
    error = validate_protocol_sequence(sequence)
    if error is not None:
        return {**base_record, "execution_status": "FAILED_VALIDATION", "error": error}
    normalized = sequence.strip().upper()
    try:
        wrapper = _load_evo2_model_once()
        inner = wrapper.model
        _make_autograd_safe(inner)
        token_ids = _tokenize(wrapper, normalized)
        base_ids = {base: _tokenize(wrapper, base)[0] for base in "ACGT"}
        ids = torch.tensor(token_ids, dtype=torch.int).unsqueeze(0).to("cuda:0")

        torch.cuda.reset_peak_memory_stats()
        started = time.monotonic()
        with torch.enable_grad():
            embeddings = inner.embedding_layer(ids).detach().requires_grad_(True)
            objective = _total_log_likelihood(inner, embeddings, ids, checkpointed=True)
            objective.backward()
        torch.cuda.synchronize()
        gradient = embeddings.grad[0].float()
        reference_total = float(objective.item())

        with torch.no_grad():
            table = {
                base: inner.embedding_layer(
                    torch.tensor([[token]], dtype=torch.int).to("cuda:0")
                )[0, 0].float()
                for base, token in base_ids.items()
            }
            estimates = {}
            for base in "ACGT":
                difference = table[base][None, :] - inner.embedding_layer(ids)[0].float()
                estimates[base] = (gradient * difference).sum(dim=1).cpu().numpy()
        backward_seconds = time.monotonic() - started
        peak_memory = int(torch.cuda.max_memory_allocated())

        length = len(normalized)
        rng = np.random.default_rng(7)
        positions = [length // 2] + [
            int(value) for value in rng.integers(1, length, size=max(0, int(check_pairs) - 1))
        ]
        predicted: list[float] = []
        exact: list[float] = []
        checked: list[dict[str, Any]] = []
        for position in positions:
            reference_base = normalized[position]
            alternate = str(rng.choice([b for b in "ACGT" if b != reference_base]))
            mutated = list(token_ids)
            mutated[position] = base_ids[alternate]
            mutated_ids = torch.tensor(mutated, dtype=torch.int).unsqueeze(0).to("cuda:0")
            with torch.no_grad():
                mutated_total = float(
                    _total_log_likelihood(
                        inner, inner.embedding_layer(mutated_ids), mutated_ids, checkpointed=False
                    ).item()
                )
            predicted.append(float(estimates[alternate][position]))
            exact.append(mutated_total - reference_total)
            checked.append(
                {
                    "position": position,
                    "reference": reference_base,
                    "alternate": alternate,
                    "predicted_delta": predicted[-1],
                    "exact_delta": exact[-1],
                }
            )
        quartile = max(1, len(positions) // 4)
        top_exact = set(np.argsort(-np.abs(exact))[:quartile].tolist())
        top_predicted = set(np.argsort(-np.abs(predicted))[:quartile].tolist())
        return {
            **base_record,
            "execution_status": "COMPLETED",
            "sequence_length": length,
            "reference_total_log_likelihood": reference_total,
            "backward_seconds": round(backward_seconds, 2),
            "peak_memory_bytes": peak_memory,
            "gradient_finite": bool(torch.isfinite(gradient).all().item()),
            "substitution_estimates": {
                base: [round(float(v), 5) for v in values] for base, values in estimates.items()
            },
            "agreement_check": {
                "pairs": len(positions),
                "spearman_predicted_vs_exact": _spearman(predicted, exact),
                "sign_agreement": float(np.mean(np.sign(predicted) == np.sign(exact))),
                "top_quartile_recall": len(top_exact & top_predicted) / quartile,
                "checked": checked,
            },
        }
    except Exception as exc:  # noqa: BLE001 - fail closed with a typed record
        return {
            **base_record,
            "execution_status": "FAILED_ATTRIBUTION",
            "error_type": type(exc).__name__,
            "error": str(exc)[:600],
            "peak_memory_bytes": int(torch.cuda.max_memory_allocated())
            if torch.cuda.is_available()
            else None,
        }


with gr.Blocks(title="Concordia Evo2 Forward Worker") as demo:
    gr.Markdown(
        "# Concordia Evo2 Forward Worker\n"
        "Run bounded hardware and runtime checks, or one real forward pass against "
        "the frozen scoring protocol. The forward pass is unverified: it is the "
        "first attempt in this project to load the checkpoint and run inference, "
        "and it may fail on early invocations."
    )
    runtime_button = gr.Button("Verify pinned runtime and checkpoint", variant="primary")
    run_button = gr.Button("Run GPU capability probe")
    result = gr.JSON(label="Qualification record")
    runtime_button.click(fn=qualify_runtime, outputs=result, api_name="qualify_runtime")
    run_button.click(fn=probe_gpu, outputs=result, api_name="probe_gpu")

    gr.Markdown("## Forward scoring (unverified)")
    sequence_input = gr.Textbox(
        label="Exactly 8,192-base DNA sequence (A/C/G/T only)",
        lines=4,
        max_lines=10,
    )
    score_button = gr.Button("Run real forward pass", variant="stop")
    score_result = gr.JSON(label="Forward score record")
    score_button.click(
        fn=score_sequence,
        inputs=sequence_input,
        outputs=score_result,
        api_name="score_sequence",
    )
    attribute_button = gr.Button("Run forward score + gradient attribution", variant="stop")
    attribute_result = gr.JSON(label="Forward + backward record")
    attribute_button.click(
        fn=attribute_sequence,
        inputs=[
            sequence_input,
            gr.Number(value=24, label="agreement-check pairs", precision=0),
        ],
        outputs=attribute_result,
        api_name="attribute_sequence",
    )


if __name__ == "__main__":
    demo.launch()
