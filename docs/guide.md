# Concordia: story, usage, debugging, security

This guide is written from an audit run on 2026-10-11 (local server, CLI, CI history, live Space
read-only probes). Where something was not tested, it says so.

## The story

A model says a stretch of DNA matters, or that an antibody binds an antigen. A colleague asks:
*which model, which checkpoint, which input, and does it survive a perturbation?* Today that answer
lives in a notebook, a chat log, or someone's memory.

Concordia makes the answer a first-class object:

1. **Everything is an artifact.** Inputs, model outputs and claims are stored by SHA-256. A stored
   artifact that has been altered is refused (`409 artifact integrity check failed`; verified).
2. **Everything has lineage.** Experiments are a DAG of DNA, protein, structure, model-run,
   measurement and evidence nodes on immutable branches. Events are append-only and replayable.
3. **Claims are checked by rules, not by another LLM.** A claim needs independent evidence
   families, counterfactual support and in-scope inputs. Fixture and synthetic outputs are rejected
   (`scientific_use_allowed=false`).
4. **A colony explores workflow variants.** A seed scientist (local `qwen3:1.7b`) is mutated into
   bounded variants that cannot see each other. Deterministic fitness selects survivors.

The honest status: the machinery is built and tested; no real scientific finding exists yet.
Evo 2 forward scoring and RFantibody/ProteinMPNN are not wired. See "Known limits".

## Who uses what

| Person | Feature | How |
|---|---|---|
| Researcher | Audit a model claim | Workspace → Investigate: follow claim → evidence → artifact → hash |
| Researcher | Branch and compare edits | `POST /experiments`, add nodes with the returned `X-Concordia-Experiment-Token` |
| Researcher | Protein / antibody structure | Antibody view or `POST /nvidia/boltz/complex` (needs `NVIDIA_API_KEY`) |
| Researcher | Replay a run | Provenance view, or `GET /api/events` and `GET /api/stream` |
| Reviewer | See what is real | Frameworks view or `GET /api/frameworks` (status: integrated / boundary / planned) |
| Integrator | Import tools | `GET /api/tools/openapi.json` (six read-only operations) |
| Engineer | Reproduce everything | `concordia benchmark`, `concordia colony-demo`, `concordia genomic-demo` |

## Run it

```bash
uv sync --extra dev --extra virtual-cell --extra postgres
cd frontend && npm ci && npm run build && cd ..
.venv/bin/concordia serve-workspace --state-root .concordia/workspace --frontend frontend/dist --port 7860
```

CLI features checked in the audit: `list-tools`, `doctor`, `genomic-demo`, `colony-demo`,
`benchmark` (local suites), `ingest-project`, `qwen-colony-demo`.

## What was tested and how it held up

| Area | Result |
|---|---|
| Python suite | 237 passed; ruff and mypy clean |
| Frontend | build OK; 8/8 Playwright tests |
| Read endpoints | all 200; `depth` and `limit` bounds enforced with 422 |
| Artifact integrity | tampered file → 409; traversal and bad digests → 404 |
| Experiment tokens | none → 401, wrong → 403, other experiment's token → 403 |
| Input validation | invalid bases and residues rejected with 422 |
| NVIDIA endpoints without a key | fail closed with 503 |
| Colony rate limit | 5 per minute per client, then 429 |
| Benchmark | throughput, replay, claims complete; Boltz is `NOT_RUN` without `--real` |
| Local Qwen colony | runs end to end, but see the limit below |

## Security findings

| # | Severity | Finding | Status |
|---|---|---|---|
| 1 | High (integrity) | A client could create a node with `scientific_use_allowed: true`. | **Fixed:** rejected with 422; only server-side operations can set it. |
| 2 | Medium | Rate-limit bypass via a client-controlled leftmost `X-Forwarded-For`. | **Fixed:** the client is the entry the trusted proxy appended (`CONCORDIA_TRUSTED_PROXY_HOPS`, default 1). Verify on the live Space after redeploy. |
| 3 | Medium | No quota on experiment creation or node count. | **Fixed:** 10 creations per client per hour, 500 per day globally, 500 nodes per experiment. |
| 4 | Low | No CSP, HSTS or frame policy. | **Fixed:** CSP (docs page exempt), HSTS over HTTPS, `frame-ancestors` limited to the app and Hugging Face. |
| 5 | Low | Supabase leaked-password protection off (portfolio auth tables). | Open: dashboard setting. |

The live Space only picks these up after a redeploy.

Positive findings: no CORS is configured (same-origin only), uvicorn runs as a non-root user in
Docker, secrets are env-only, the public OpenAPI surface is read-only, and server and CI action
versions are commit-pinned.

## Known limits (be upfront about these)

- **Claim benchmark is self-labeled.** 50 generated cases score accuracy 1.0 and macro-F1 1.0.
  This shows the plumbing works, not that the verifier is accurate on real claims.
- **Local Qwen colony.** In an audit run, all three members had `schema_valid_response_rate = 0.0`
  and a survivor was still selected. Fixed: members with no valid response now go extinct
  (`NO_VALID_RESPONSE`), and a generation with no viable member ends the colony as `EXTINCT`. The
  1.7B model still needs a better prompt or a larger model to produce valid claims.
- **Space was stale.** The live Space predates the framework catalog and antibody work.
- **Supabase persistence unexercised.** The three Concordia tables exist with RLS on and 0 rows.

## Debugging checklist

| Symptom | Check |
|---|---|
| `503` from `/nvidia/*` | `NVIDIA_API_KEY` is unset (by design, fails closed) |
| `429` for everyone on a Space | `CONCORDIA_TRUST_PROXY_HEADERS=1` not set; all visitors share the proxy IP |
| `409 artifact integrity check failed` | stored file no longer matches its digest; restore or re-run |
| `ModuleNotFoundError: psycopg` | install with `--extra postgres` |
| Playwright server fails to start | the web server must use the project venv (`../.venv/bin/python`) |
| State resets after redeploy | set `CONCORDIA_DATABASE_URL` so state persists in Postgres |
| Space shows old UI or 404 on a new route | redeploy; the Space was last built 2 Oct |
| `qwen` runs fail | `concordia doctor` shows Ollama, model and checkpoint digest |

## What makes it portfolio- and research-grade next

1. Close findings 1 to 3.
2. Redeploy the Space and connect Supabase.
3. Run one real Boltz-2 antibody-antigen case end to end and publish the artifact, replay and
   verifier verdict, including a case where the verifier disagrees with the model.
4. Replace the self-labeled benchmark with held-out, independently labeled cases.
