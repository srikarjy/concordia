# Configurations

Version-controlled configuration will define dataset, assay, split, fingerprint, predictor, explanation, LLM, intervention, and evaluation settings. Configuration files must contain stable parameters and references only—never credentials, raw responses, or environment-specific absolute paths.

The first baseline configuration is `baseline_nr_ahr.yaml`; `scientist_local.yaml` pins the locally qualified genomic seed model, checkpoint digest, prompt, and qualification report. Changes that affect scientific output should produce a new experiment manifest rather than silently replacing prior results.

`scientist_tools.yaml` defines the initial evaluation-mode tool policy. Policies are deny-by-default and must be versioned with each experiment because tool access is an experimental variable.

`studies/hbb_promoter_inputs.yaml` and `studies/hbb_promoter_protocol.yaml` freeze the two-variant GRCh38 pilot before Evo2 outcomes. The input manifest records ClinVar identities, genomic and window coordinates, reference validation, Ensembl retrieval URLs, and sequence SHA-256 values. These files define a protocol; they do not contain Evo2 results or establish scientific support.
