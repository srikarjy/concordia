---
title: Concordia structure gateway
emoji: 🧬
colorFrom: gray
colorTo: blue
sdk: docker
app_port: 7860
license: mit
---

Explicit, authenticated Boltz-2 structure inspection for accepted 1IGV candidates.
The gateway calls the existing ThermoMPNN Space and preserves its constraints and
rankings. Only a selected, accepted single substitution can reach NVIDIA.

Set `NVIDIA_API_KEY` and `CONCORDIA_STRUCTURE_TOKEN_SHA256` as Space secrets.
The latter is the SHA-256 of a separate high-entropy owner access token, never
the NVIDIA key. Anonymous requests cannot spend inference quota.

Three uncached Boltz calls per rolling day; one in flight at a time. The existing
Boltz gateway caches by mutant sequence. Single-worker deployment is required.
The free Space filesystem is ephemeral: cache, ledger and quota counters survive
process restarts only while that filesystem survives; rebuilds reset them. This
is an owner-only inspection tool, not an anonymous public inference service.

Boltz receives a self-reference MSA. Its structure and confidence are computational
outputs, not measured stability, binding, expression or functional evidence.
This manual inspection action does not change the automatic stability refold gate.
No model weights, holdout data, NVIDIA credential or owner token are in this repo.
