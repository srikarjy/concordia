# Configurations

Version-controlled configuration will define dataset, assay, split, fingerprint, predictor, explanation, LLM, intervention, and evaluation settings. Configuration files must contain stable parameters and references only—never credentials, raw responses, or environment-specific absolute paths.

The first baseline configuration is `baseline_nr_ahr.yaml`; `scientist_local.yaml` is a candidate local-runtime configuration for Phase 3. Changes that affect scientific output should produce a new experiment manifest rather than silently replacing prior results.

`scientist_tools.yaml` defines the initial evaluation-mode tool policy. Policies are deny-by-default and must be versioned with each experiment because tool access is an experimental variable.
