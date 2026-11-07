---
title: Concordia ThermoMPNN Stability API
emoji: 🧬
colorFrom: blue
colorTo: green
sdk: docker
app_port: 7860
---

# Concordia ThermoMPNN Stability API

CPU-only HTTP wrapper around Concordia's frozen 1IGV measured-stability workflow.
It calls the same `TypedStabilityRequest` and `run_typed_request` path as the CLI;
it does not make hosted NVIDIA calls.

The service is limited to the frozen 1IGV domain, single substitutions, and at most
100 mutation candidates per request. Refusals preserve trigger codes and evidence.
T2 is conditional: its threshold is calibrated for novel positions and cannot fire
for a known training position. This is an in-silico stability result, not a claim
about folding, expression, binding, or biological function.

The frozen holdout artifacts are published in this Space. The 1IGV holdout is
therefore permanently spent for anyone using this public artifact, not only for
Concordia.
