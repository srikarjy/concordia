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

1. Complete the frozen HBB promoter pilot with immutable real scores and independent annotation artifacts; expand beyond two variants only under a newly frozen protocol.
2. Extend the measured Qwen colony from one software generation to repeated real-evidence generations after scientific inputs exist.
3. Execute Evo 2 SAE feature inspection under the implemented layer and SAE-checkpoint provenance contract.
4. Select a compatible sequence-to-function comparator only after freezing the implemented target-equivalence and training-independence contract.
5. Add collaboration, authenticated private projects, and scalable graph projections only after local performance measurements justify them.

Each extension needs an acceptance test, a resource budget, and an explicit scientific validity gate. No additional paid infrastructure is assumed.

## Implemented post-Phase-10 gates

`StudyProtocol` now records the dataset license, inclusion/exclusion criteria, checkpoint, target, assembly, 8,192-base (or declared) window, coordinate convention, evidence families, hypothesis, and uncertainty method. `ProtocolGate` must freeze this record before any evidence is admitted and rejects fixture, synthetic, recorded-fixture, and ineligible outputs.

`RealEvo2Scorer` is a strict adapter for an externally executed forward pass. It validates checkpoint identity, scoring target, input sequence hash, real execution mode, and scientific-use eligibility; it never falls back to the deterministic scorer. Actual checkpoint execution remains hardware- and dataset-dependent.

NVIDIA's current free hosted `arc/evo2-40b` page documents the `/generate` endpoint. The separate Evo2 NIM documentation exposes `/forward` for a deployed container; the hosted catalog does not document a corresponding forward route. Concordia removed its earlier unverified hosted-forward assumption. `NvidiaHostedEvo2GenerationRunner` now persists the exact request and raw response for a short real API smoke test, validates generated DNA and sampled probabilities, and always sets `scientific_use_allowed=false`. `NvidiaHostedEvo2Runner` fails closed with instructions to use a verified local NIM for the frozen study's likelihood target.

Run the bounded hosted check only after creating a development key on NVIDIA's Evo2 page:

```bash
export NVIDIA_API_KEY='your-key'
.venv/bin/concordia nvidia-evo2-smoke --sequence ACGTACGT --num-tokens 8
unset NVIDIA_API_KEY
```

Never paste the key into chat or commit it. The generated sequence is a model output, not evidence of biological function. Completing the HBB study still requires local `/forward` tensors from compatible hardware and the frozen `mean_next_base_log_likelihood` protocol.

The recorded 10 September 2026 smoke test used the synthetic prompt `ACGTACGT`, requested eight tokens, and returned eight valid DNA bases plus eight bounded sampled probabilities in 328 ms. Request and response bytes are preserved by SHA-256 in the local content-addressed store, with a small committed validation record at `reports/nvidia-evo2-hosted-smoke.json`. This confirms API interoperability only and is not a genomic finding.

The frozen pilot uses ClinVar accessions `VCV000015471.124` and `VCV000015464.124`. Their GRCh38 reference alleles were checked against separately retrieved 8,192-base Ensembl windows before freeze. A released K562 DNase-seq narrowPeak file (`ENCFF185XRG`, experiment `ENCSR000EOT`) was checksum-validated and contains two intervals in the union of those windows; neither interval overlaps the variant base itself. This negative overlap is preserved. Its relationship to attribution is not assessed until real Evo2 output exists. ClinVar assertions and ENCODE annotations remain contextual evidence requiring exact provenance; neither is accepted as causal proof.

Typed post-Phase-10 contracts now reject fixture-backed SAE features and require exact Evo2 layer, SAE checkpoint, sequence digest, activation threshold, and positions. Cross-model evidence must predeclare distinct checkpoints, target equivalence, and training independence, and its recorded effect must exactly equal alternate minus reference. No real SAE or comparator output has been collected.
