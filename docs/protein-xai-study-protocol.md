# Protein stability XAI study protocol

**Version:** draft 0.1, 2026-10-19. **Evidence state:** protocol and source
inspection only. No new prediction, gradient, fidelity, user, or biological
experiment was run for this document. The numerical gates below are prospective
rules, not achieved results. This is T3 of the
[protein XAI task pack](protein-xai-agent-tasks.md).

## Scientific question and scope

The first product question is whether a researcher can inspect a *particular*
single-substitution stability prediction, understand which residues the model
uses, see whether that explanation is faithful to the model, and record a
reviewable decision. The explanation is about a model prediction. It is not a
claim that the highlighted residues cause experimental stability, folding,
binding, or function.

For reference sequence `S`, fixed reference backbone `P`, mutation `m =
(i, WT, ALT)`, and a **specific pinned ThermoMPNN checkpoint**, define

`f(P,S,m) = - ThermoMPNN_raw_ddG(P,S,m)` in kcal/mol.

Here `f > 0` means the model predicts the mutant to be **more stable** than the
reference. The experimental comparison is `ΔG_mut - ΔG_WT` under the normalized
Tsuboyama convention; Concordia stores it as
`ddg_kcal_higher_is_more_stable`, with WT anchored at zero. ThermoMPNN's raw
convention is destabilization-positive; the sign conversion is explicit in
[`stability/contracts.py`](../src/concordia/stability/contracts.py) and
[`evaluate_structure_aware.py`](../scripts/evaluate_structure_aware.py). The
local historical sign check is supportive, not a substitute for per-checkpoint
parity. The [ThermoMPNN paper](https://www.pnas.org/doi/10.1073/pnas.2314853121)
uses negative predicted ΔΔG for stabilizing candidates. Store *both* raw and
converted values, the transform, units, and model identity.

The initial explanatory question is: **For this fixed-reference-structure
prediction of `i:WT→ALT`, which positions in the reference sequence most affect
`f` through the model's sequence-context representation?** The target is the
exact scalar `f`, never the current ridge ensemble's numeric output, a rank
aggregate, or a whole-protein average. A saturation-mutation landscape
answers a different question and must be shown separately.

Supported feasibility scope: one unmodified chain, 20 canonical amino acids,
one substitution, a complete and uniquely mapped backbone at all modeled
residues, WT identity matching the mapped structure/sequence, explicit
insertion-code and chain handling, no missing modeled residues, and a fixed
reference conformer. The 1IGV development example is 74 residues and comes
from a 50–80-residue local selection filter. This is **not** a claim that the
checkpoint supports only that length or that performance transfers to other
proteins. Reject ambiguous mapping, noncanonical residues, complexes, indels,
multiple mutations, and structure ensembles until separately validated. Record
structure provenance and whether it is experimental or predicted. A predicted
structure does not become experimental evidence by being used as an input.

## Candidate model and feasibility gate

Start with the existing ThermoMPNN adapter's upstream source commit
`370f76ec62bd929f7425e311d8df04a0d094990f` and the locally recorded
weight SHA-256
`af449118ccfb4e34971d802321907ed82a8a035ae80f055bf8fc56009a4a838a`.
These are *declared identities* in the current script; T4 must verify the bytes
and actual loaded checkpoint at execution. The pinned
[`TransferModel`](https://github.com/Kuhlman-Lab/ThermoMPNN/blob/370f76ec62bd929f7425e311d8df04a0d094990f/transfer_model.py)
combines the ProteinMPNN representation with target-site WT and mutant
embeddings. Its sequence tokens are integers. The pinned
[`ProteinMPNN` implementation](https://github.com/Kuhlman-Lab/ThermoMPNN/blob/370f76ec62bd929f7425e311d8df04a0d094990f/protein_mpnn_utils.py)
creates differentiable token embeddings (`W_s(S)`), while the distributed
[`custom_inference.py`](https://github.com/Kuhlman-Lab/ThermoMPNN/blob/370f76ec62bd929f7425e311d8df04a0d094990f/analysis/custom_inference.py)
wraps inference in `torch.no_grad()`. Frozen model weights do not themselves
prevent gradients with respect to an input embedding. **Whether this specific
transfer-model scalar has a usable, faithful embedding gradient remains
untested.** The all-visible decoder permits sequence-context influence but
does not prove nonzero influence at any given residue.

T4/T5 must first reproduce one upstream scalar from identical inputs and
settings, verify raw and converted sign, then expose an embedding-injection
path that produces the same `f` as the ordinary path within `1e-5` kcal/mol in
float32 CPU inference. Confirm a finite, nonzero gradient of `f` with respect
to `h_S` away from the target site and finite-difference agreement on at least
three preselected embedding coordinates using central differences at two step
sizes. Record absolute and relative errors and the chosen numerical step; if
precision makes `1e-5` impossible, report failure and revise the *future*
protocol before touching held-out outcomes. If parity, gradients, memory, or
time fail, do **not** call the result integrated gradients. The fallback is a
recorded, fixed-backbone *context-substitution sensitivity* analysis, explicitly
labeled model sensitivity and evaluated against its own independent controls.

The proposed primary attribution, conditional on that gate, is integrated
gradients (IG) on the per-residue sequence embedding `h_S`. Hold `P`, mapping,
target position `i`, WT/ALT target embeddings, all masks, model weights, and
sampling settings fixed. At each integration point interpolate only the
context-position embeddings `j ≠ i` from a baseline equal to the arithmetic
mean of the checkpoint's 20 canonical amino-acid embeddings to their observed
embeddings. The target site's sequence embedding remains observed. Run 32
midpoint steps for the feasibility extension; sum dimensions to one signed
number per mapped residue and report absolute magnitude only for ranking.
Record signed values too. The baseline is an off-manifold mathematical
reference, not a protein or counterfactual biology. Also run a zero-embedding
baseline as a sensitivity analysis; disagreement is reported, not hidden.
The IG [completeness property](https://arxiv.org/abs/1703.01365) is relative to
this chosen path and scalar, not evidence of biological causation.

For each result calculate `sum_j attribution_j` and
`f(observed context) - f(baseline context)`. The prospective engineering gate is
absolute error ≤ `max(0.02 kcal/mol, 0.05 × |output difference|)` at 32 steps;
repeat at 64 steps if it fails, preserve both attempts, and flag failure if
still outside tolerance. This tolerance is a predeclared numerical diagnostic,
not a universal IG guarantee. Record residual, gradient norms, target-site
attribution exclusion, embedding/sequence/structure indices, missing-residue
map, seed, device, dtype, steps, and runtime. Do not display a residue overlay
if mapping is non-bijective or these checks fail.

## Evaluation 1: prediction quality

**Population and split.** The immediate reproducibility study uses proteins
in the **official Megascale test split** from ThermoMPNN's released split file,
with one frozen structure/sequence mapping and the assay's single-mutation
labels. It is a retrospective replication of a benchmark that the model's
authors already used, not a new independent generalization test. Do not use
1IGV, its variant-level holdout, or model-development proteins as an independent
test. The larger independent study requires a separately collected or selected
protein-family-disjoint assay set whose exposure to this checkpoint and all
Concordia fitting is audited **before** labels are opened. If no clean set is
available, report independent predictive validity as untested.

**Primary endpoint:** mean absolute error (MAE, kcal/mol) of sign-converted
`f` against assay ΔΔG, first averaged over substitutions within each protein,
then equally over proteins. **Comparator:** zero-change prediction (`0.0`
kcal/mol) for every substitution. Also report a predeclared simple per-protein
sequence/structure baseline only if its training data can be kept disjoint;
otherwise do not silently replace the zero baseline. **Unit:** protein (not
variant). **Failure:** the 95% protein-cluster bootstrap confidence interval
for paired `MAE_ThermoMPNN − MAE_zero` does not lie entirely below zero, or
mapping/sign/overlap cannot be verified. **Uncertainty:** 10,000 protein-level
bootstrap resamples with fixed seed `20261019`, reporting the paired difference,
per-protein distribution, point estimate, percentile interval, and protein
count. Secondary endpoints: Spearman within protein where enough non-tied
variants exist, direction accuracy excluding near-zero measured changes by a
predeclared assay noise band, calibration slope/intercept **without fitting on
the test set**, and error stratified by structure provenance, solvent exposure,
position, cysteine, and assay source. Never use a fitted 1IGV interval on this
population. A bootstrap interval excluding zero on a benchmark already used by
the upstream authors is evidence of retrospective performance only.

The [Tsuboyama assay](https://www.nature.com/articles/s41586-023-06328-6)
measures proteolysis-derived folding stability of small domains under its
specific conditions; kinetic effects, aggregation, disulfides, and protease
behavior can complicate interpretation. ThermoMPNN's transfer training used
Megascale data and evaluated a FireProt homologue-free collection in its
[paper](https://www.pnas.org/doi/10.1073/pnas.2314853121). FireProt may serve
as a predeclared *secondary cross-assay* analysis only after checking exact
labels, units, temperature/condition differences, protein overlap, and whether
the upstream authors used it for model or paper selection. Do not pool its
numbers into the primary Megascale MAE. ProteinGym
[DMS scores](https://github.com/OATML-Markslab/ProteinGym) measure varied
fitness phenotypes, not a common folding ΔΔG scale; exclude them from the
primary endpoint.

## Evaluation 2: explanation fidelity

**Population:** a distinct, predeclared subset of mapped official-test
proteins after leakage audit. It is model-fidelity evidence, not a biological
stability result. For each target prediction choose context substitutions
without consulting explanation values or assay labels: for every eligible
context residue `j ≠ i`, choose one of the 19 other canonical amino acids via
`SHA256("20261019|protein_id|target_variant_id|j|candidate_aa")` minimum
digest. Keep `P` fixed, update the context sequence at `j`, and recompute the
*same* target `i:WT→ALT`. Exclude changes that break input validation. These
discrete interventions are held out from the IG construction. They probe what
the model does under altered context; some may be off the biological sequence
distribution.

**Primary endpoint:** within-target Spearman correlation between
`|IG_attribution_j|` and `|f(P,S_j,m) − f(P,S,m)|`, then mean within protein,
then equal-protein mean. **Comparators:** (1) absolute local input gradient
without integration, (2) inverse Cα distance to the mutation, and (3) 100
rankings formed by permuting IG magnitudes *within* Cα-distance bins
`[0,8), [8,16), [16,∞)` Å, preserving contact bias. Record each comparator's
same endpoint and the paired IG-minus-best-comparator difference per protein.
**Failure:** IG does not beat the best comparator with a 95% protein-cluster
bootstrap interval entirely above zero; fewer than 10 eligible context sites
per target; or numerical/mapping gates fail. **Uncertainty:** 10,000 paired
protein-cluster bootstrap resamples, seed `20261019`, plus per-protein and
per-target distributions. Do not use variants as independent replicates.
Secondary: top-five capture of the largest discrete responses and rank
stability under 32 versus 64 steps and mean versus zero baseline. These tests
assess the model's response to fixed-backbone edits, not true energetic
epistasis or residue causality.

**Sanity controls:** repeat the same attribution computation after independently
reinitializing the trainable transfer head (fixed seed) while leaving inputs
and ProteinMPNN weights fixed; report Spearman agreement of maps and output
changes. Also compare with a separately randomized full model *if a valid
reinitialization recipe exists*; otherwise mark that control unavailable.
Identical/highly correlated maps (predeclared median rank correlation ≥0.8)
under the randomized head fail the sanity check. A high-quality contact map
may appear plausible even when model parameters are irrelevant, as illustrated
by [saliency sanity checks](https://arxiv.org/abs/1810.03292). Attribution
methods for protein structure already exist, including
[ExplainableFold](https://arxiv.org/abs/2301.11765); the proposed contribution
is a validated explanation of a specific stability scalar inside a replayable
researcher workflow, **conditional on measured fidelity and utility**, not
novelty from merely coloring a structure.

## Evaluation 3: researcher-task utility

**Task:** an independent protein researcher receives a reference sequence,
structure, candidate list, frozen predictions, assay/provenance caveats, and
one prior recorded select/exclude/defer decision. They must reconstruct that
decision, its evidence, and whether the explanation is scientifically eligible
within 15 minutes. The intended decision and evidence checklist are frozen by
an adjudicator before testing; reviewers do not see the answer key.

**Comparator:** the same evidence as ordinary exported tables, structure file,
and README, without Concordia's linked review/explanation interface. Use a
counterbalanced within-reviewer crossover with disjoint but difficulty-matched
cases; randomize case/order and prevent the same case appearing in both
conditions for one reviewer. **Primary endpoint:** fraction of cases with a
fully correct decision *and* evidence/limitation reconstruction by the time
cap, scored blind from a predeclared rubric. **Unit:** reviewer-case, with
reviewer and case clustering. **Failure:** paired improvement interval does
not exclude zero on the favorable side, substantial incorrect-confidence
increase, or data leakage between conditions. **Uncertainty:** report paired
difference with 95% cluster bootstrap resampling reviewers and cases, the
raw contingency counts, and inter-rater agreement for a second blind scorer.
Time, error discovery, and task completion are secondary. A small convenience
test is formative only; no sample size or power claim is invented here. Select
study size from a separately reported variance/power calculation after a
formative pilot, then freeze cases, rubric, analysis, and stopping rule before
the larger study. No researcher study has been run.

## Exposure, leakage, and assay audit

Before any predictive or XAI evaluation, produce a machine-readable audit of
every candidate protein/variant against (a) ThermoMPNN train/validation/test
identifiers and sequences, (b) ProteinMPNN pretraining structures when
traceable, (c) Concordia's calibration, ensemble, ranking, and prior method
selection inputs, and (d) assay source and condition. Use exact sequence and
variant hashes, reverse/renumbering aliases, local sequence alignment,
MMseqs-style homology clustering at the upstream paper's stated 25% identity
threshold, and manual family/structure review for borderline cases. Record
alignment coverage and ambiguity, not merely an ID match. Treat unknown
pretraining exposure as **unknown**, not clean. Exclude overlapping proteins
and families from claims of independent generalization; retain them only in
an explicitly in-distribution or retrospective stratum.

The current historical artifact reports no `1IGV` substring in split IDs and
a positive sign check, but its split scan is only an identifier test. It does
not establish family-level non-overlap or immunity to upstream training on
the same Megascale assay. Concordia's 1IGV position/variant folds are within
one protein and cannot establish protein-family generalization. Keep
calibration population and training scope explicit for every interval or
uncertainty display. No calibration fit, threshold tuning, variant selection,
or explanation-method choice may inspect the final evaluation labels.

## Frozen bounded feasibility pilot and next freeze

This pilot tests **computation and mapping**, not predictive performance:

1. Input is the already-used local `1IGV.pdb_S1A` example from the versioned
   Tsuboyama manifest and its exact referenced AlphaFold PDB. Read sequence,
   mapping, and model assets only; do not read its assay label during the new
   pilot. Existing historical 1IGV analyses make it ineligible as a blind
   scientific validation case.
2. CPU only, float32, one thread-setting recorded, fixed deterministic seed
   `20261019`, no paid service. Verify model/weight digest; compare ordinary
   and embedding-injection `f`; inspect gradients; then compute IG at **8
   midpoint steps** solely to profile feasibility. No tuning on output quality.
3. Cap the entire new pilot at **20 wall-clock minutes and 8 GiB peak resident
   memory**. Abort cleanly on either bound. Record CPU model, Torch version,
   start/end time, peak memory, status, logs, raw outputs, gradient diagnostics,
   and artifacts. A missing asset or dependency is an `unavailable` outcome,
   not a simulated success.
4. Do not score predictor accuracy, make a residue-importance claim, or mark
   `scientific_use_allowed=true` from this pilot. A terminal model run would
   establish real local execution only.

If 8-step parity/gradient/resource feasibility passes, run a **separate**
32-step numerical extension on this same development example and freeze any
engineering correction before evaluating official-test proteins. The larger
study needs a versioned manifest that names proteins/families, structures,
mutations, exclusion rules, assay schema, checkpoint bytes, context
interventions, baseline, sample-size rationale, and code digest before results
are opened. Choose study size using pilot runtime/variance from *development*
cases; do not use final-set labels or fidelity outcomes for that choice. The
official-test analysis remains retrospective, and an actually new external
family/assay cohort is a separate gate for stronger generalization claims.

## Decisions for implementation

- **T4:** implement one scalar ThermoMPNN prediction adapter with immutable
  input/model/target identity and raw-plus-converted output; validate mapping
  and exact saved-output replay. Do not inherit 1IGV ridge calibration or
  ranker. The real-model parity and resource pilot above is the first execution
  gate. If assets are unavailable, report that state precisely.
- **T5:** implement fixed-structure context sensitivity first as a clearly
  named model diagnostic. Add IG only after input-gradient and parity checks.
  Persist all embedding arrays, mapping, baselines, numerical checks,
  interventions, controls, randomization, and failed attempts. An attractive
  heatmap without model-fidelity evidence is ineligible for scientific claims.
- **Release:** the protocol alone changes no prediction or explanation status.
  Retrospective benchmark replication, fidelity, and researcher utility are
  three different gates; none has passed in this T3 work.
