# Independent evidence verification

The versioned `independent-evidence-v1` policy consumes frozen claim scopes and typed evidence observations. It is deterministic and does not call a language model. Observation assessment, strength, and independence metadata must come from trusted tool execution or audited ingestion; they are not fields that a scientist can assign to itself.

`SUPPORTED` requires a passing counterfactual check, at least two sufficiently strong independent families, complete artifact integrity, a path to the declared sequence, exact scope agreement, and no unresolved critical contradiction. A bipartite matching of families to independence groups prevents a shared source group from counting twice. Perturbation methods cannot be relabelled as attribution. Literature is contextual evidence within the declared scope.

Every dependency envelope and payload is rehashed. Every branch is inspected, including fixture branches outside the shortest source path. Missing objects, invalid envelopes, cycles, and budgets fail closed. A fixture or synthetic artifact is ineligible for scientific use. Cryptographic integrity establishes identity, not the truth of imported measurements.

The result retains support and contradiction families, per-evidence reasons, inspected artifacts, and source paths. Claims are not rewritten. Empty evidence returns `MISSING_EVIDENCE`; insufficient families return `PARTIALLY_SUPPORTED`; invalid provenance returns `UNVERIFIABLE`; a valid critical contradiction returns `CONTRADICTED`. Path-only backtracking now returns at most `PARTIALLY_SUPPORTED`, never scientific eligibility.

The initial measurement utilities implement regulatory interval overlap with assembly/chromosome/assay checks and repeat/window summaries with explicit missingness, zero values, dispersion, and sign agreement. One observation does not establish repeated-run stability. Cross-model and literature collection adapters remain future ingestion work.
