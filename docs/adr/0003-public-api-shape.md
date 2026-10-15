# ADR-0003: Operation-shaped, versioned public API

**Status:** Accepted
**Date:** 2026-10-14
**Deciders:** Concordia project owner

## Context

The workspace app grew to 27 endpoints under three unrelated naming regimes: `/api/*`
for the saved read-only workspace, `/nvidia/*` for hosted model calls, and
`/experiments/*` for the lineage DAG, plus a one-off `/colony/run`. Adding
RFdiffusion and ProteinMPNN forced the question of where a sixth and seventh model
belong, and the honest answer was that the current shape has no place for them.

Four problems are structural rather than cosmetic.

**The provider is in the path.** `/nvidia/boltz/complex` makes a vendor part of the
public contract. The resource is a complex structure prediction; NVIDIA is one way to
compute it. Self-hosting Boltz, or moving to a second provider, breaks every client
for no domain reason. The same path also pins a model family, so `/nvidia/boltz/complex`
cannot serve a Chai-1 or AlphaFold 3 run.

**The authorization boundary is inverted relative to cost.** `/experiments/*` requires a
capability token and mostly writes local rows. `/nvidia/*` is anonymous and spends the
shared `NVIDIA_API_KEY`. Rate limits bound the damage but not the asymmetry: the free
operations are guarded and the paid ones are open.

**Two ways to call the same model, one without lineage.** `/nvidia/boltz/complex` returns
a structure with no experiment node; `/experiments/{id}/operations/boltz/predict` records
one. The product claim is that every model output carries provenance, so the unrecorded
variant contradicts the pitch it is meant to demonstrate.

**The headline capability is not callable.** Rule-based claim verification is the thing
no incumbent does and the reason the project exists. It has no endpoint. A reviewer who
believes the README cannot exercise it without cloning the repo.

Async handling is also split: Evo 2 forward and attribution return a job id and are polled,
while Boltz and OpenFold2 block for minutes on the same deployment.

## Decision

Shape the API around **operations on domain resources**, version it, and make the model a
parameter rather than a path segment.

```
POST /v1/structure-claims/verify     rule-based verdict from measured signals
POST /v1/predict/complex             {"model": "boltz2", ...}
POST /v1/predict/structure           {"model": "openfold2", ...}
POST /v1/design/backbone             {"model": "rfdiffusion", ...}
POST /v1/design/sequence             {"model": "proteinmpnn", ...}
POST /v1/generate/dna                {"model": "evo2-40b", ...}
POST /v1/score/variants              {"model": "evo2-7b", ...}
GET  /v1/jobs/{job_id}               one envelope for every slow operation
GET  /v1/artifacts/{digest}          content-addressed read
GET  /v1/provenance/{digest}         dependency slice for one artifact
     /v1/experiments/...             unchanged DAG, moved under the prefix
```

Four rules govern it.

1. **A model is a request field with a documented enum, never a path segment.** Adding a
   provider adds an enum value. The response always names the exact `model_id` and
   `model_version` that ran, so the contract stays provider-neutral while the record stays
   specific.
2. **Every operation that spends a shared credential requires a capability token.** The
   existing per-experiment token mechanism extends to a workspace-level token for paid
   operations. Free reads and verification stay open, because they cost a CPU cycle.
3. **Every model operation records lineage.** There is one path, and it writes a model-run
   node and an output node. An operation with nowhere to record is a 422, not a shortcut.
4. **Anything that can exceed a few seconds answers `202` with a job id.** Clients poll one
   envelope. Synchronous-only endpoints are the current cause of proxy timeouts on the Space.

The old paths remain as deprecated aliases that forward to the new handlers, so the deployed
frontend keeps working. They are removed only once the frontend no longer calls them.

`/v1/structure-claims/verify` is implemented first and is self-contained: it takes measured
signals and a scope, builds the claim against an ephemeral store, and returns the status with
its reasons. It spends nothing and stores nothing, so it needs no token and no quota.

## Options considered

### Keep the current paths and add `/nvidia/rfdiffusion/*` and `/nvidia/proteinmpnn/*`

Rejected. It is the cheapest change and it deepens all four problems: two more vendor-named,
anonymous, paid, lineage-free endpoints, and still no way to call the verifier.

### Rewrite in place, without aliases

Rejected. The deployed frontend calls eight of the current paths. A clean break means the
public demo breaks the moment the Space redeploys, for a benefit no visitor can see.

### GraphQL

Rejected. One schema over the DAG is attractive and the client is a single React app that
would gain little. It also makes per-operation cost control and rate limiting harder, which
is the live risk on a free deployment with a shared paid key.

### A resource-per-model REST surface (`/v1/models/{model}/predict`)

Rejected. It reads cleanly but pushes the provider back into the path and makes a request
that compares two models awkward. Operation-first keeps the comparison in one call.

## Consequences

- Clients code against operations, so a provider swap is a config change.
- Paid operations become token-gated, which is a breaking change for any anonymous caller;
  the aliases keep the frontend working but the new paths require a token from the start.
- Two surfaces exist during migration, and the alias table is a maintenance cost until the
  frontend moves.
- A single job envelope means the Evo 2 queue generalizes to Boltz, RFdiffusion and
  ProteinMPNN, replacing per-model polling.
- The verifier becomes demonstrable over HTTP, which is the point of the project.

## Action items

1. Add `POST /v1/structure-claims/verify` (no token, no spend) and document it in the
   read-only tool API so agents can discover it.
2. Introduce the `/v1/jobs/{job_id}` envelope by generalizing `Evo2ForwardJobQueue`.
3. Move the paid operations behind a workspace capability token, keeping the old paths as
   anonymous rate-limited aliases until the frontend is migrated.
4. Expose `design/backbone` and `design/sequence`, which currently have no endpoint.
5. Drop the aliases once `frontend/src/App.tsx` calls only `/v1`.
