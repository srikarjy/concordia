# Stability scoring and explicit structure inspection

The public page scores through the existing ThermoMPNN Space. A separate owner
action selects an accepted candidate and sends it to the structure gateway. The
gateway re-runs the same frozen scoring endpoint, preserves its ranking and
refusals, constructs the mutant sequence from the bundled 1IGV PDB, and invokes
the existing `NvidiaHostedBoltzRunner` through `BoltzGateway`.

Boltz-2 is the NVIDIA-hosted model in this flow; NVIDIA is not a third model.
This manual inspection does not change the automatic refold gate. It cannot
improve a stability score, supply stability evidence, or override a refusal.

## Access and deployment

The small gateway is packaged with an explicit source-file allowlist and a
secret/path scan. It has no model weights or holdout labels. Dependency versions
and distribution hashes are pinned in `deploy/hf-structure-gateway/requirements.lock.txt`.

```sh
PYTHONPATH=src .venv/bin/python scripts/deploy_structure_gateway.py \
  .concordia/structure-gateway-upload-next
```

That command uploads code only. The deployed code-only gateway is at
`https://srikarjy025-concordia-structure-gateway.hf.space` and fails closed until
access and NVIDIA credentials have been configured. The production frontend has
not been updated to this inspection UI pending that authorization.

**Current blocker:** automatic approval review rejected uploading the NVIDIA key
to this Space because earlier instructions reserved credential storage for a
Worker. Explicit user approval for this new destination is required. The local
test sends the key only to NVIDIA; no credential was uploaded to Hugging Face.

After that approval, add `--configure-secrets` to the deployment command. It stores
`NVIDIA_API_KEY` as a Space secret and the SHA-256 of an independent owner token as
`CONCORDIA_STRUCTURE_TOKEN_SHA256`. The plaintext owner token is generated in
`.concordia/structure-access-token`, mode 0600, ignored by git. Enter that token
in the page's password field. It is never persisted in browser storage. Do not
enter the NVIDIA credential into the page.

Unauthenticated traffic cannot call either provider. Accepted requests are limited
to one in flight and three uncached Boltz calls per rolling day. The SQLite cache
and quota counters are on the free Space's ephemeral filesystem: rebuilding the
Space resets them. This is owner access, not an anonymous public service. The
ThermoMPNN Space remains separate and holds no NVIDIA credential.

## Verification

```sh
PYTHONPATH=src .venv/bin/pytest -q tests/unit/test_structure_workflow.py
cd frontend && npm test -- --config=playwright.public.config.ts
```

The browser tests use clearly marked fixtures; they do not spend hosted quota.
The real integration was tested with:

```sh
PYTHONPATH=src .venv/bin/python scripts/verify_structure_workflow_live.py
```

The local HTTP handler called the real ThermoMPNN Space and real NVIDIA endpoint:
three candidates ranked, two refused, K6Q selected, NVIDIA HTTP 200, 1.625 seconds,
59,983 characters of mmCIF. The combined result is stored locally in
`.concordia/structure-workflow-live/result.json`. Its artifact digest is
`065e5f303aff5e598f5b5223144b9f18e9fb1cb81041e22522f024aa2d2f9610`, and its ledger
chain verifies. Subsequent local verification uses the existing sequence cache.
This proves the composed handler, not the still-unconfigured deployed call path.

The Boltz structure uses a one-sequence self-reference MSA. It is a computational
prediction, not demonstrated folding, stability, expression, binding or function.
Per-residue confidence is not used for ranking or coloring.
