---
title: Concordia Evo2 Forward Worker
emoji: "🧬"
colorFrom: indigo
colorTo: blue
sdk: gradio
sdk_version: "6.26.0"
python_version: "3.12.12"
app_file: app.py
pinned: false
license: apache-2.0
short_description: Bounded GPU qualification for a frozen Evo2 forward protocol
preload_from_hub:
  - arcinstitute/evo2_7b evo2_7b.pt,config.json bda0089f92582d5baabf0f22d9fc85f3588f6b58
---

# Concordia Evo2 Forward Worker

This ZeroGPU Space is a bounded qualification surface for Concordia's frozen
Evo2 7B forward-scoring protocol. It accepts no DNA sequence and produces no
model output. One check reports assigned GPU metadata. A separate CPU-only check
verifies the exact Python, PyTorch, Evo2, and Vortex versions; selected installed
Evo2 source files; and the preloaded checkpoint and config bytes.

A passing hardware probe means only that the device is a candidate execution
environment. It does not establish Evo2 runtime compatibility, artifact integrity,
scientific validity, or a biological finding.

## Forward scoring (unverified)

This Space also exposes a `score_sequence` function (Gradio `api_name`) that
accepts an exact 8,192-base DNA sequence and attempts one real Evo2 7B forward
pass under the frozen scoring protocol
(`concordia.genomics.evo2_protocol.Evo2ScoringSemantics`). It is called by the
main Concordia deployment's interactive `POST /nvidia/evo2/forward` endpoint
when `CONCORDIA_EVO2_FORWARD_SPACE_URL` points at this Space.

**This has never completed a successful real run.** Model loading
(`_load_evo2_model_once` in `app.py`) and the forward-pass call
(`_forward_pass_logits`) are written against the pinned Evo2 repository's
documented usage pattern, not a confirmed execution — no GPU has been
available to this project to run them. Expect the first several invocations
to fail with `FAILED_MODEL_LOAD` or `FAILED_FORWARD_PASS`; the fix for either
belongs in `app.py`, not in the scoring math (`scoring.py`), which is
independently unit-tested against
`concordia.genomics.evo2_protocol.score_causal_logits` and does not depend on
hardware.

Every response is a typed record with an explicit `execution_status`
(`COMPLETED`, `FAILED_VALIDATION`, `FAILED_MODEL_LOAD`, `FAILED_TOKENIZATION`,
`FAILED_FORWARD_PASS`, or `FAILED_SCORING`) rather than an opaque traceback,
and always carries `scientific_use_allowed: false` — the calling adapter
(`concordia.genomics.evo2_zerogpu.ZeroGpuEvo2ForwardRunner`) independently
re-verifies checkpoint identity, exact window length, and scored-token count
before ever promoting a result to scientific eligibility.

The worker requests the ZeroGPU-supported Python 3.12.12 runtime. Evo2 is
installed from revision `53f195997257c56c00e5ef8d33a54f5baad143a6`, Vortex is
pinned to 1.1.0, and the official FlashAttention 2.8.3 wheel is pinned by
SHA-256 for the measured Torch/CUDA/Python ABI. The checkpoint is preloaded from revision
`bda0089f92582d5baabf0f22d9fc85f3588f6b58`.

The initial probe result is preserved in the main repository at
`reports/evo2-zerogpu-hardware-probe.json`. Runtime qualification hashes the
checkpoint as opaque bytes. It does not deserialize the checkpoint, load the
model, execute a forward pass, or establish numerical or scientific validity.

The main read-only scientific workspace remains at
[`srikarjy025/concordia-colony`](https://huggingface.co/spaces/srikarjy025/concordia-colony).
