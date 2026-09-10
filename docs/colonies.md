# Bounded colony evolution

Phase 6 implements a controlled workflow search, not a debate system. A versioned seed genome owns a prompt reference, ordered workflow, attribution configuration, verification requirements, resource budget, uncertainty prompt version, and policy version. Descendants change exactly one allowlisted field. Arbitrary prompt text and arbitrary tools are not mutation targets.

## Mutation and lineage

The mutation engine supports adding or removing an optional verification step, replacing a tool with an explicitly compatible tool, reordering dependency-independent steps, choosing a declared window size or evidence threshold, changing tool-call budget within fixed limits, and selecting a versioned uncertainty prompt. A mutation record preserves parent and proposed child identities, operator, random seed, old and new values, and validation result. Rejected mutations remain events; they are not silently discarded.

The scheduler creates a fresh executor for every member. Its immutable request contains only the member identity, generation, isolation identity, frozen task digest, and that member's genome. No field can carry a competitor's claims, fitness, or output. Generation selection is a barrier: descendants are not scheduled until every member in the preceding generation has completed or failed and the selection event exists.

## Fitness and stopping

`weighted-fitness-v1` retains every component separately. Positive weights total one across provenance completeness, evidence coverage, counterfactual consistency, attribution-direction agreement, cross-verification coverage, citation validity, schema validity, stability, and tool success. Unsupported claims, contradictions, tool failures, and bounded normalized runtime, token, and compute costs are subtracted. Scores are clamped to zero through one. Descending score selects survivors; immutable member identity breaks ties.

The append-only SQLite ledger supports restart reconstruction and partial-run resume. Completed members are not re-executed. Explicit terminal outcomes cover generation completion, cancellation, member-budget exhaustion, and fitness stagnation. Failed and extinct members remain inspectable.

## Software demonstration

Run:

```bash
.venv/bin/concordia colony-demo --state-root .concordia/colony-demo
```

The command creates a three-member colony, runs two generations, and reports selections and event counts. The executor is `deterministic_colony_fixture`; all outputs set `scientific_use_allowed=false`. This proves orchestration, isolation, ancestry, replay, and deterministic selection only. It does not run Qwen or Evo2 and cannot establish a genomic finding.
