# Evo 2 reading and Concordia design decisions

Read: Brixi, Durrant, Ku et al., *Genome modelling and design across all domains of life with Evo 2*, Nature 652, 1349–1361 (2026), [version of record](https://doi.org/10.1038/s41586-026-10176-5), published 4 March 2026. Methods consulted: [supplement](https://media.springernature.com/original/springer-static/esm/art%3A10.1038%2Fs41586-026-10176-5/MediaObjects/41586_2026_10176_MOESM1_ESM.pdf), particularly A.3 and A.4. No article figures or substantial text are redistributed.

Evo 2 models DNA at nucleotide resolution using StripedHyena 2. The paper evaluates sequence likelihoods, supervised embedding predictors, and sparse-autoencoder features as distinct uses. Performance varies by task: distal regulatory prediction remains weaker than specialized sequence-to-function models. Motif-associated internal features are useful interpretation evidence, but do not themselves prove a causal regulatory effect. The chromatin-design experiments include biological assays beyond computational predictor agreement.

The human variant methods score an 8,192-base window and compare variant and reference likelihoods. Length normalization matters for indels. Some analyses average forward and reverse-complement scores. Supervised BRCA1 evaluation separates genomic positions to avoid placing alternate alleles at the same position in training and test sets.

## Implementation decisions

These are Concordia design choices, not claims made by the paper:

- Freeze model checkpoint, target, assembly, chromosome, strand, and zero-based half-open window in each verification scope.
- Keep mutagenesis in the counterfactual family even when displayed as a position-importance track.
- Begin independent confirmation with a separately sourced regulatory annotation. Overlap indicates contextual consistency, not causal proof.
- Inspect every provenance dependency, including branches that contradict the proposed claim.
- Preserve null results, missing measurements, window sensitivity, and failed executions.
- Require a protocol artifact before importing final outcomes. Do not tune windows or thresholds against the final cohort.

## Compute implications

The [official inference repository](https://github.com/arcinstitute/evo2#requirements), checked 10 September 2026, documents Linux and CUDA. Its current 7B path supports bfloat16 without Transformer Engine; other listed checkpoints have stronger FP8 hardware requirements. This is more specific than the earlier repository-wide statement that all Evo 2 inference requires FP8 hardware. A free CPU Space can serve Concordia's recorded demonstration and verifier. It does not provide validated Evo 2 inference.

## Beyond Phase 10

1. Complete an experimentally grounded regulatory-variant study with audited licensing, immutable real scores, independent annotations, and a frozen protocol.
2. Integrate the qualified Qwen scientist into each process-isolated colony member and replace simulated colony fitness observations with measured execution records.
3. Add Evo 2 SAE feature inspection as a separate interpretation target with layer and SAE-checkpoint provenance.
4. Compare compatible sequence-to-function models only after documenting target equivalence and training-data dependence.
5. Add collaboration, authenticated private projects, and scalable graph projections only after local performance measurements justify them.

Each extension needs an acceptance test, a resource budget, and an explicit scientific validity gate. No additional paid infrastructure is assumed.
