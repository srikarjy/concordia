# Roadmap

Concordia is built in phases. Each phase produces something runnable and
measurable — no phase depends on speculative future work.

## Phase 0 — Scaffolding (this commit)
- Repo structure, packaging, README, About.
- No modeling code yet.

## Phase 1 — Inference engine
- `concordia/engine.py`: wraps a Hugging Face ConceptCLIP checkpoint.
  Given an image, returns top-k concept predictions with scores and,
  for the top-2 concepts, a region-concept alignment heatmap.
- Minimal CLI: `concordia infer <image>` prints predictions + saves heatmap.
- Done when: runs end-to-end on a handful of sample images with no crashes.

## Phase 2 — Structured explanation trace
- `concordia/explain.py`: turns raw engine output into a structured trace —
  `primary_finding`, `evidence` (supporting/competing concepts), a
  `decision_basis` (why this confidence tier, in terms of score margins),
  and a `counterfactual` (what would need to change for a different verdict).
- Confidence policy: thresholds that map score margins to
  high/medium/low-confidence tiers with different downstream handling
  (e.g. low confidence → flag for review rather than auto-report).
- Done when: trace output is stable JSON, covered by unit tests on
  synthetic score distributions (clear win, close call, ambiguous).

## Phase 3 — Evaluation harness (the priority — see below)
- Validates Phases 1–2 against ground truth. Without this, "confidence
  tier" and "explanation" are just labels with no evidence behind them.

## Phase 4 — Post-hoc cross-validation
- `concordia/posthoc_explain.py`: LIME and SHAP as independent,
  model-agnostic checks on the intrinsic heatmap from Phase 1.
- Opt-in (`posthoc=True`) — expensive, meant for interrogating a specific
  result, not routine calls.
- A **concordance score**: quantify agreement between intrinsic/LIME/SHAP
  salient regions (e.g. IoU or rank correlation of top regions), surfaced
  in the trace output rather than left for a human to eyeball three
  heatmaps side by side.

## Phase 5 — Case memory
- `concordia/memory.py`: SQLite-backed case history (single-writer —
  documented constraint, not an oversight).
- Similarity retrieval: given a new case's embedding, surface the nearest
  past cases and how they were adjudicated, as a fourth evidence source
  alongside intrinsic/LIME/SHAP.

## Phase 6 — Serving + deployment
- `concordia/api/`: thin REST (and optionally MCP) interface over the
  harness.
- Dockerfile + `k8s/` manifests (Deployment, Service, PVC for memory.db).
- `replicas: 1` by design until memory.py moves off SQLite.

---

## Phase 3 in detail — Evaluation Harness

**Why this is next, not last:** everything upstream (confidence tiers,
"high-confidence" claims, explanation quality) is currently asserted, not
measured. The eval harness is what turns Concordia from a demo into
something whose claims can be checked.

**Scope:**

1. **Dataset.** Pull a small labeled public set (target: 150–300 images,
   e.g. a subset of a public dermatology or radiology dataset with class
   labels). Store a manifest (`data/manifest.csv`: image path, label,
   split) — never commit the images themselves if the source license
   doesn't allow redistribution.

2. **Metrics — model quality.**
   - Top-1 / top-k accuracy, per-class and aggregate.
   - AUC per class (one-vs-rest) where applicable.
   - Confusion matrix.

3. **Metrics — calibration (does confidence mean anything).**
   - Reliability diagram: for each confidence tier (high/medium/low from
     Phase 2's policy), what fraction of predictions in that tier were
     actually correct?
   - Expected Calibration Error (ECE) as a single number to track over
     time.
   - This is the test of the confidence policy's core claim — if
     "high confidence" cases aren't meaningfully more accurate than
     "medium confidence" ones, the policy is decorative.

4. **Metrics — explanation quality.**
   - Concordance score (Phase 4) vs. correctness: does agreement between
     intrinsic/LIME/SHAP predict when the model is right?
   - If ground-truth region annotations exist for any subset of the data,
     compute localization overlap (IoU) between the heatmap and the
     annotated region — a direct check that the model is looking at the
     right evidence, not just getting the label right for the wrong reason.

5. **Output.** A single `eval report` (JSON + a rendered summary) per run,
   versioned by model checkpoint + dataset manifest hash, so results are
   comparable across changes.

**Done when:** running `concordia eval --dataset data/manifest.csv`
produces a report with all of the above, and the numbers are believable
enough to put in the README's About section as an actual claim rather
than an aspiration.
