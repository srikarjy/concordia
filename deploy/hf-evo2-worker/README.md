---
title: Concordia Evo2 Forward Worker
emoji: "🧬"
colorFrom: indigo
colorTo: blue
sdk: gradio
sdk_version: "6.26.0"
app_file: app.py
pinned: false
license: apache-2.0
short_description: Bounded GPU qualification for a frozen Evo2 forward protocol
---

# Concordia Evo2 Forward Worker

This ZeroGPU Space is a bounded hardware-qualification surface for Concordia's
frozen Evo2 7B forward-scoring protocol. The initial deployment accepts no DNA
sequence and produces no model output. It reports only the assigned GPU, CUDA and
PyTorch versions, BF16 availability, and device memory.

A passing hardware probe means only that the device is a candidate execution
environment. It does not establish Evo2 runtime compatibility, artifact integrity,
scientific validity, or a biological finding.

The initial probe result is preserved in the main repository at
`reports/evo2-zerogpu-hardware-probe.json`. The worker still has no Evo2 dependency,
does not load a checkpoint, and exposes no sequence input.

The main read-only scientific workspace remains at
[`srikarjy025/concordia-colony`](https://huggingface.co/spaces/srikarjy025/concordia-colony).
