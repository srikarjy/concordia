# Configurations

Version-controlled configuration will define dataset, assay, split, fingerprint, predictor, explanation, LLM, intervention, and evaluation settings. Configuration files must contain stable parameters and references only—never credentials, raw responses, or environment-specific absolute paths.

The first baseline configuration is `baseline_nr_ahr.yaml`; `scientist_local.yaml` pins the locally qualified genomic seed model, checkpoint digest, prompt, and qualification report. Changes that affect scientific output should produce a new experiment manifest rather than silently replacing prior results.

`scientist_tools.yaml` defines the initial evaluation-mode tool policy. Policies are deny-by-default and must be versioned with each experiment because tool access is an experimental variable.

`studies/hbb_promoter_inputs.yaml` and `studies/hbb_promoter_protocol.yaml` preserve the original two-variant GRCh38 pilot freeze before Evo2 outcomes. The input manifest records ClinVar identities, genomic and window coordinates, reference validation, Ensembl retrieval URLs, and sequence SHA-256 values. `studies/hbb_promoter_evo2_protocol_v2.yaml` supersedes the protocol—not the cohort—before execution because v1 did not identify an immutable released checkpoint or exact causal scoring semantics. Both versions remain preserved, and neither contains Evo2 results or establishes scientific support.

`virtual_cell/cellxgene_shh_e12_5.yaml` pins one bounded real CELLxGENE H5AD, including collection and dataset versions, byte size, SHA-256, shape, observation schema, gene order, perturbation column, and download ceiling. `virtual_cell/state_source.yaml` pins the official State source revision and policy-file digests. Source verification does not accept the separate model license or authorize model-weight execution.
