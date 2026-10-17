# Concordia backend build list

This is the implementation order for the campaign-centered protein engineering backend.

## Completed

- [x] Campaign, organization scope, and capability-token authorization
- [x] Scoped owner-created access grants with hashed tokens, roles, revocation, and action enforcement
- [x] Campaign rounds with protocol, assay context, budget, and batch size
- [x] Campaign and round lifecycle state machines with authenticated transitions
- [x] Immutable candidate records with parent lineage and sequence hashes
- [x] Measurement records that preserve assay status and replicates
- [x] Typed assay semantics reject measured/censored rows without numeric values
- [x] Finalized rounds and closed campaigns are enforced as read-only at persistence boundaries
- [x] Frozen dataset snapshots with transformation policies
- [x] Versioned recommendation records
- [x] Authenticated campaign API and cross-campaign isolation tests
- [x] Authenticated campaign readback for rounds, candidates, measurements, jobs, and reports
- [x] Append-only redacted campaign audit events with Postgres schema and authenticated readback
- [x] Bind audit provenance into redacted BioRender report manifests
- [x] Campaign model-run contract for provider and training outputs

## Next build order

- [x] Route configured BioNeMo and training calls through campaign model-run jobs
- [x] Provide a configured HTTPS BioNeMo Framework HTTP runner adapter
- [x] Provide a separate artifact-only BioNeMo inference connector and HTTPS adapter
- [x] Add an authenticated BioNeMo `/healthz` preflight contract that performs no inference
- [ ] Validate a production BioNeMo Framework runner deployment
- [ ] Validate a production BioNeMo inference deployment
- [x] Route the project protein baseline through campaign model-run jobs
- [x] Define a frozen-dataset BioNeMo Framework training connector contract
- [x] Add strict CSV assay ingestion with censored and failed-result semantics
- [x] Route Boltz, RFdiffusion, and ProteinMPNN through campaign model-run jobs
- [x] Add typed RFdiffusion → ProteinMPNN → Boltz binder-design stage planning and ranking
- [x] Add durable job attempts, provider request IDs, reconciliation, leases, and cancellation primitives
- [x] Register the first real provider adapter: Boltz through the existing rate-limited gateway
- [x] Move campaign metadata and audit state to the authoritative Postgres repository when configured
- [x] Define the versioned Postgres campaign schema and migration boundary
- [x] Wire reachable Postgres campaign persistence with SQLite development fallback
- [x] Add fail-closed `CONCORDIA_REQUIRE_POSTGRES=1` deployment mode
- [x] Add typed content-addressed artifact references for campaign outputs
- [x] Add object-storage artifact references for structures, assay files, and checkpoints
- [x] Add an injected S3-compatible object-storage artifact adapter
- [x] Add CSV assay ingestion with units, controls, replicates, censored values, and validation errors
- [x] Add baseline project predictors and frozen training dataset contracts
- [x] Aggregate measured assay replicates deterministically while excluding failed results from training labels
- [x] Add recommendation policies with random, diversity, greedy, and uncertainty baselines
- [x] Expose deterministic recommendation selection with persisted seed and replay rationale
- [x] Expose authenticated recommendation replay validation
- [x] Bind recommendation replay to a digest of the original scored inputs
- [x] Persist retrospective benchmark reports as authenticated, content-addressed campaign artifacts
- [x] Add evidence claims and deterministic scientific-use status transitions
- [x] Add organization role and secret rotation primitives
- [x] Add export controls and retention policy primitives
- [x] Add BioRender-compatible report manifests and publication figure specifications
- [x] Add independently verifiable report-manifest digests
- [x] Add explicit replay-read and replay-execute model-run contracts
- [x] Add externally verifiable event-ledger exports with artifact manifests
- [x] Implement and enforce a retrospective benchmark before any prospective experimental claim
- [x] Add a repeated-seed retrospective benchmark harness with a constant baseline
- [x] Add a geometry-only structure null baseline with digestable metrics and a
  non-scientific API report
- [x] Run the structure null baseline on the independently sourced held-out
  antibody benchmark; keep prospective use blocked because retrospective
  calibration is not experimental validation
- [x] Expose a campaign-level validation gate for assay and model provenance checks
- [x] Digest and audit retrospective benchmark results against frozen datasets and seeds
- [x] Add frozen study records with protocol, model-pin, selection-manifest, and admission gates

## Release gates

- [x] No raw sequence or secret appears in campaign structured logs
- [x] Every model output is linked to input and parameter hashes
- [x] External model calls are allow-listed and budgeted
- [x] Enforce an external provider allow-list at model-run creation
- [x] Enforce per-job budget admission against the round budget
- [x] Cross-organization and cross-campaign access tests pass
- [x] Failed and unmeasured candidates remain distinguishable
- [x] Recommendation replay has an executable deterministic validation gate
