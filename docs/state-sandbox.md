# Arc State virtual-cell boundary

Arc State predicts population- and cell-level transcriptomic responses to genetic, chemical, or cytokine perturbations. It operates on sets of cells and AnnData-derived expression features, so it is a separate scientific vertical from Evo2 nucleotide likelihood and attribution. State output cannot be used as an interchangeable genomic score.

## Implemented contract

`StatePredictionRequest` freezes:

- AnnData artifact SHA-256, media type, cell count, gene count, and gene-order digest;
- preprocessing version and exact cell-context and perturbation columns;
- perturbation kind, identifier, dose, and duration where applicable;
- State model identity and checkpoint digest;
- the post-perturbation gene-expression target;
- cell, gene, time, memory, output, and network budgets.

`StateSandbox` verifies the input artifact before work, persists the canonical request, delegates only to an approved typed runner, verifies every returned identity and output shape, and checks the prediction artifact hash. Changed inputs or settings therefore create new requests and artifacts.

`RecordedStateFixtureRunner` exercises this boundary locally without State weights. Its output explicitly says that it contains no predictions and always sets `scientific_use_allowed=false`. It exists for contract, persistence, and corruption tests only.

## Real adapter requirements

A real runner must use an exact State release and checkpoint under Arc's applicable noncommercial model/output license and acceptable-use policy. It must run with network disabled after all artifacts are staged, preserve the exact AnnData input and generated matrix, record the gene order, and keep failed or partial execution artifacts. Evaluation must use a predeclared held-out perturbation split and deterministic metrics from measured expression; another language model cannot decide accuracy.

State may contribute cross-scale contextual evidence to a future Concordia study only when a genomic perturbation, cell context, expression target, and assay are explicitly linked. Agreement with Evo2 remains model agreement, not experimental proof. Strong claim support still requires complete provenance, counterfactual evidence, an independent evidence family, and no unresolved critical contradiction.

## Current limitation

The `arc-state` runtime, model weights, and real AnnData cohort are not installed or committed. State's code and model outputs have specific noncommercial licensing terms, and the public atlas may involve cloud-account access even when a free allowance applies. Concordia therefore does not download them automatically or imply that the CPU Hugging Face Space can execute State.
