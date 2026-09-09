# Reproducibility Contract

Every experiment must make the exact inputs to prediction, explanation, intervention, LLM generation, and evaluation identifiable. Reproducibility means both replaying saved artifacts exactly and clearly identifying sources of nondeterminism that cannot be removed.

## Required identities

- Dataset source URL, retrieval time, license/terms reference, byte checksum, and logical dataset version.
- Original row identifier, original SMILES, canonical SMILES, duplicate group, scaffold, assay, label, and split.
- Separate seeds for splitting, model fitting, cohort selection, shuffled-donor assignment, and response generation where supported.
- Predictor family, hyperparameters, library versions, training-data identity, serialized artifact checksum, and probability-class ordering.
- Fingerprint algorithm, radius, bit count, chirality flag, and RDKit version.
- XAI library/version, explained output, output scale, feature-dependence choice, background-data identity, expected value, and validation tolerance.
- Evidence packet schema version and content hash; document source/version, excerpt, usage status, and stable evidence identifier.
- Prompt text/version, claim-schema version, LLM provider, exact model identifier returned by the provider, generation parameters, request time, and retry history.
- Intervention type/version, parameters, parent packet hash, resulting packet hash, and donor mapping where applicable.
- Evaluation version, metric definitions, matching rules, annotation-set version, raw response identity, and derived-result checksum.

## Manifest rules

Manifests are immutable JSON documents with stable key ordering for hashing. Paths are relative to an experiment root or represented by artifact URIs. A changed input or configuration creates a new run identifier; derived outputs never overwrite raw inputs or responses.

Each run records the source-code revision and environment lock. A dirty working tree must be recorded or rejected for final study runs. Credentials are never written to manifests.

## Randomness

Code must use explicit local random generators rather than process-global random state. Stable split and donor algorithms use sorted inputs before seeded operations. Parallel model execution may introduce platform-level differences; the fitted artifact and environment record are the replay authority.

Hosted LLM APIs may remain nondeterministic at temperature zero and may change behind a model alias. Saved raw responses permit exact evaluator replay. New API calls are new observations and record the provider-returned model/version metadata.

## Storage policy

Git tracks code, configs, prompts, schemas, small manifests, checksums, documentation, and permitted summary results. Raw or processed datasets, fitted models, full evidence payloads, restricted documents, API responses, and bulk experiment outputs live in ignored artifact locations or external storage.

External artifacts must have a checksum and retrieval/provenance record. A missing external artifact is a reproducibility failure, even if its path remains in a manifest.
