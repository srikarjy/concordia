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

The checkpoint digest must resolve to an actual content-addressed artifact. A fixture run uses a stored absence marker that explicitly contains no model weights; it never invents a checkpoint identity.

`RecordedStateFixtureRunner` exercises this boundary locally without State weights. Its output explicitly says that it contains no predictions and always sets `scientific_use_allowed=false`. It exists for contract, persistence, and corruption tests only.

## CELLxGENE real-input demonstration

`CellxgeneDiscoverIngestor` accepts only a frozen collection/dataset version and an H5AD URL on the approved CELLxGENE dataset host. It persists the request and exact collection metadata before downloading, enforces a byte ceiling, verifies byte size and SHA-256, and checks the AnnData shape, unique `var_names`, ordered-gene digest, observation schema, context column, perturbation column, and required labels.

The initial input is the 1,789-cell `e12.5 thalamic progenitors` dataset from the public Shh-perturbation collection. It contains 908 `Control` and 881 `SBE1/5` cells under the `knockout` column. The file has 30,198 features and a fixed 29,755,471-byte H5AD identity. It is real input data, not a State prediction, and its feature space has not been qualified against a checkpoint.

Install the optional reader and run the bounded demonstration:

```bash
uv sync --extra virtual-cell
.venv/bin/concordia cellxgene-state-demo
```

The command downloads at most 50 MB, writes the real H5AD and source metadata into local content-addressed storage, creates a persisted checkpoint-absence marker, and exercises the fixture runner. The final report remains `scientific_use_allowed=false`.

## Pinned external State source

Concordia does not vendor State. `configs/virtual_cell/state_source.yaml` pins the official repository at revision `9bbfe78a434a55205e4de834e1ea99f85f7a3add`, package version `0.11.3`, its Python constraint, and exact source/model-policy hashes. Verify a separately cloned checkout without importing or executing it:

```bash
git clone https://github.com/ArcInstitute/state.git .concordia/external/state
git -C .concordia/external/state checkout 9bbfe78a434a55205e4de834e1ea99f85f7a3add
.venv/bin/concordia verify-state-checkout --checkout .concordia/external/state
```

The verifier rejects a wrong remote, revision, dirty tree, package identity, Python constraint, or changed license/policy file. State currently requires Python below 3.13, so its future execution environment must remain isolated from Concordia's Python 3.13 environment.

## Selected K562 release

`configs/virtual_cell/state_k562_release.yaml` is a distinct release-selection record. It does not alter the earlier `state_source.yaml` audit, whose `NOT_ACCEPTED` value remains an accurate historical statement about source verification. The release record states that the user accepted the applicable State terms on 10 September 2026 for non-commercial use only.

The selected Hugging Face release is `arcinstitute/ST-HVG-Replogle` at revision `bb6a9562cbbf1fd152df14cc53b4cc7517c77175`. It pairs `zeroshot/k562/checkpoints/best.ckpt` with `zeroshot/k562/eval_best.ckpt/adata_real.h5ad`. The manifest pins the checkpoint, configuration, matched dataset, policy files, and required mapping files by canonical relative path, byte size, and SHA-256.

Run the fail-closed verifier after staging the release:

```bash
.venv/bin/concordia verify-state-release --root .concordia/external/state-k562
```

The verifier rejects traversal, symlinks, missing files, size changes, and digest changes. It opens only the H5AD in read-only backed mode and verifies its 188,590-cell by 2,000-gene shape, gene order, observation schema, `k562` context, `gene` perturbation column, and 10,691 `non-targeting` controls. It does not deserialize the checkpoint, `.pt`, `.torch`, or pickle files. A passing result therefore reports `execution_status=NOT_RUN` and `scientific_use_allowed=false`.

## Real adapter requirements

A real runner must use an exact State release and checkpoint under Arc's applicable noncommercial model/output license and acceptable-use policy. It must run with network disabled after all artifacts are staged, preserve the exact AnnData input and generated matrix, record the gene order, and keep failed or partial execution artifacts. Evaluation must use a predeclared held-out perturbation split and deterministic metrics from measured expression; another language model cannot decide accuracy.

State may contribute cross-scale contextual evidence to a future Concordia study only when a genomic perturbation, cell context, expression target, and assay are explicitly linked. Agreement with Evo2 remains model agreement, not experimental proof. Strong claim support still requires complete provenance, counterfactual evidence, an independent evidence family, and no unresolved critical contradiction.

## Current limitation

The source checkout, selected K562 checkpoint, helper artifacts, and matched AnnData input are now reproducibly verifiable. The selected files have not been loaded, no prediction has been produced, and no held-out evaluation has been run. Execution must use an isolated Python 3.11 or 3.12 environment and remains limited to non-commercial use. The CPU Hugging Face Space is a saved, read-only software demonstration and does not execute State.
