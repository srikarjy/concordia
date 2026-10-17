# ADR-0004: Build Concordia as an evidence operating system

**Status:** Accepted  
**Date:** 2026-10-15  
**Deciders:** Concordia maintainers

## Context

Concordia already has a substantial software foundation: typed scientific
objects, content-addressed artifacts, an experiment graph, durable local runs,
an event ledger, independent structure-claim rules, hosted model adapters, and
a read-only browser workspace. The main risk is not a missing model endpoint.
It is that a polished interface could make fixture output, model plumbing, or
single-model confidence look like validated biology.

The product therefore needs a durable distinction between:

1. software that is implemented and tested;
2. model calls that were actually executed;
3. evidence that is independently measured and reproducible; and
4. biological conclusions that remain outside the product boundary until
   protocol, provenance, and validation requirements are met.

## Decision

Build Concordia as an evidence operating system for computational biology,
with the claim as the primary user object.

The core path is:

~~~text
study protocol
  -> immutable inputs and model execution records
  -> claim/evidence graph
  -> independent verification
  -> replayable report
  -> explicit decision and limitations
~~~

Model integrations are replaceable execution adapters. They do not own
verification status, scientific eligibility, or user-facing conclusions.

Every result must carry:

- exact input, output, model, checkpoint, settings, environment, and code
  identities;
- execution mode (recorded_fixture, hosted_generation, real_forward, or
  another explicit value);
- provenance artifact references and producing events;
- scientific_use_allowed derived by a protocol gate rather than supplied by
  a client;
- uncertainty, missing evidence, contradictions, and known limitations;
- a replay mode:
  - replay-read: reproduce the recorded result exactly from saved artifacts;
  - replay-execute: run again and report any drift as a new observation.

The product will be built in the following order:

1. **Trust substrate.** Finish the ledger, artifact, replay, authorization,
   and failure semantics. Make state persistence and integrity visible in API
   contracts. Add external-root export/verification so a report can be
   checked outside the live service.
2. **Study layer.** Promote frozen study protocols, datasets, model pins,
   selection rules, and preregistered outcomes to first-class records. Make
   protocol admission fail closed for fixture, synthetic, incomplete, or
   mismatched evidence.
3. **Independent validation.** Expand the antibody benchmark with a declared
   selection manifest, an independent baseline, repeated seeds, confidence
   calibration, and corrected metrics. Preserve failures and negative results.
   No model's own confidence or samples can independently verify itself.
4. **Scientific workflows.** Connect Evo2, Boltz/OpenFold, virtual-cell, and
   binder-design adapters through the same execution contract. Each adapter
   must produce a real terminal record or an explicit unavailable/failed
   record; queued and plumbing-only states are never reported as completed
   science.
5. **Researcher experience.** Make every UI path claim-first: show evidence
   status, provenance, replay mode, and limitations before visual polish.
   Keep the public deployment read-only and fixture-labeled until a study
   satisfies the same gates.
6. **Operational hardening.** Add durable Postgres/object-store adapters,
   worker attestation, retention controls, rate-limit observability, security
   scanning, and deployment smoke tests without weakening the local/free-first
   path.

## Non-goals

- presenting generated structures or sequence scores as therapeutic,
  diagnostic, or causal findings;
- adding an agent framework as a substitute for deterministic verification;
- treating a content hash or local hash chain as tamper-proof external
  attestation;
- expanding the public Space into an arbitrary model-execution service;
- combining molecular, genomic, and virtual-cell evidence into one unsupported
  scientific conclusion.

## Consequences

- The repository may contain more explicit status and limitation fields than a
  conventional demo application.
- Negative benchmark results and unavailable model paths are first-class
  outputs and must remain visible.
- New model adapters are slower to accept because they need protocol identity,
  artifacts, replay behavior, and failure contracts.
- The same evidence contract can support local fixtures, hosted APIs, and
  later paid GPU workers without changing the verifier or user-facing claim
  semantics.

## Immediate implementation queue

- [x] Restore and keep state_persistence visible in the public tool manifest.
- [x] Add a versioned campaign report export with an independently verifiable
  manifest digest.
- [x] Add an external ledger export containing the chain report, ledger root,
  and artifact manifest.
- [x] Add explicit replay-read and replay-execute API/service contracts.
- [x] Add a study record that binds protocol, selection manifest, model pin,
  evidence families, preregistered outcomes, and fail-closed admission status.
- [ ] Finish the corrected Evo2 real-forward rerun before making any genomic
  claim.
- [x] Add a geometry-only independent null baseline before interpreting
  structure-claim performance. The baseline is a retrospective control only;
  `SUPPORTED` remains an evidence-verifier status, not experimental validation.
- [x] Run that baseline on the independently selected, held-out nine-complex
  antibody benchmark before making any prospective or scientific structure
  claim. The resulting report is `reports/structure-null-baseline-benchmark.json`.

