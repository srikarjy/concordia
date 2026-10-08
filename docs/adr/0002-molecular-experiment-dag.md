# ADR-0002: Shared immutable molecular experiment DAG

**Status:** Accepted  
**Date:** 2026-10-07  
**Deciders:** Concordia project owner

## Context

Concordia is evolving from a saved genomic audit demonstration into an interactive molecular
experimentation sandbox. DNA generation, sequence edits, scoring, protein design, structure
prediction, comparison, and evidence collection need one shared lineage model. Endpoint-specific
history or mutable project documents would make branching and reproduction unreliable.

## Decision

Represent every molecular object, model invocation, measurement, structure, and evidence record as
an immutable node in an experiment DAG. Payloads are typed and content-addressed. SQLite stores
experiment metadata, lineage edges, and candidate selections. Each experiment uses a random
capability token; the token hash, never the token, is persisted.

The first release supports DNA, protein, structure, model-run, measurement, and evidence nodes;
branching through parent edges; deterministic sequence and measurement comparisons; candidate
selection; and a reproducible manifest digest. Model endpoints are not yet coupled to experiment
writes: that integration must persist a model run and its output atomically enough to avoid partial
lineage.

## Options considered

### Reuse the evidence graph directly

Rejected because the evidence graph describes scientific and provenance relationships but does not
own interactive experiment authorization, branch identity, candidate selection, or typed molecular
payload lifecycles.

### Mutable experiment documents

Rejected because in-place edits obscure prior states and make rollback and reproduction ambiguous.

### Immutable DAG with content-addressed payloads

Selected because it matches Concordia's existing artifact model, preserves every branch, and keeps
future model adapters independent of the persistence backend.

## Consequences

- Rollback means selecting or branching from an earlier node; historical nodes are never rewritten.
- Large molecular payloads live in content-addressed storage instead of SQLite rows.
- Public deployment still requires capability tokens and explicit privacy disclosure.
- Multi-user accounts, sharing policy, deletion workflows, quotas, and Postgres replication remain
  future deployment work.
