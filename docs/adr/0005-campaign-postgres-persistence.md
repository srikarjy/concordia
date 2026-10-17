# ADR 0005: Campaign Postgres persistence boundary

## Decision

Campaign state has an explicit, versioned Postgres schema contract in
`concordia.campaigns.postgres`. The local SQLite store remains the default
development implementation, while a reachable `CONCORDIA_DATABASE_URL`
selects the Postgres repository for campaign state. Both implementations must
preserve the same typed payloads, capability-token hash boundary, foreign-key
lineage, job lease fields, and frozen dataset digest.

## Why

Campaigns contain private sequences, assay results, model-job metadata, and
access capability hashes. They cannot depend on an ephemeral deployment disk
for production durability. The migration is separated from the local store and
records an applied schema revision, so deployment can fail closed on an
unavailable database without silently writing campaign state to ephemeral
SQLite.

## Constraints

- Raw access tokens are never persisted; only their SHA-256 hashes are stored.
- Candidate parent edges and measurement rows are foreign-keyed to a campaign
  lineage, not just identified by an unscoped string.
- Dataset snapshots retain a digest of the exact measurement payload and
  transformation policy.
- Model jobs retain lease and provider-correlation state for reconciliation.
