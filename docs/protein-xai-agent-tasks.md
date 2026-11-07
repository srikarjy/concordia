# Concordia: assignments for coding and research models

> **Current delivery instructions (2026-10-20):**
> Follow [PORTFOLIO_FINISH_PLAN.md](PORTFOLIO_FINISH_PLAN.md) and the
> [T1–T3 review](reviews/2026-10-20-t1-t3-review.md).
> The F1–F4 jobs define the bounded portfolio release. This older T1–T7 pack
> remains technical background; do not restart it or make every later research
> study a prerequisite for finishing the portfolio.

Prepared 2026-10-19. These are implementation handoffs, not completed features.
The detailed design is [protein-xai-build-instructions.md](protein-xai-build-instructions.md).
The baseline is [the repository audit](audits/2026-10-19-repository-audit.md).

## Model selection

**Default: GPT-6.1 Sol, High reasoning, in Codex with repository and terminal
access.** Use it for the implementation assignments below. Reserve GPT-6 Astra
at XHigh for protocol design, unresolved scientific questions, and hard reviews.
Use a fresh session for review so it must inspect the evidence independently.

The local Codex configuration currently selects `gpt-6-astra` at `xhigh`; its
model catalog also lists `gpt-6.1-sol`. No model setting was changed while writing
this handoff. OpenAI describes Sol as its lower-cost option for complex coding
and Astra as its most capable model for demanding work.
[Official model comparison](https://developers.openai.com/api/docs/models)

If Claude Code is already available, Claude Opus 5.5 is a reasonable alternative
implementation model or cross-vendor reviewer. Anthropic currently recommends
it for most workloads and describes it as suited to long-running coding work.
Claude Sonnet 5.5 is an optional lower-cost choice for a tightly specified UI or
documentation task. [Official Claude model comparison](https://platform.claude.com/docs/en/models/overview)

These assignments are engineering judgments, not results of a head-to-head
benchmark on Concordia. Use existing subscription access first. Do not buy another
subscription or run several expensive agents merely to obtain agreement. Model
agreement is not independent biological evidence. Check availability in the
actual model picker; local catalog entries do not establish remaining quota.

## How to run the work

Use a coding agent with access to the **current local checkout**. GitHub alone
does not contain all the audited features, uncommitted work, or these new handoff
documents. A cloud agent needs a deliberately prepared private snapshot or
reviewed branch containing the required files; do not assume cloning main is
equivalent. A chat-only model can review the supplied documents but cannot verify
implementation without the source, tools, and execution artifacts.

1. Give an implementation model the common brief and **one assignment** below.
2. Keep it working until the assignment has a concrete patch, meaningful checks,
   and a handoff. Do not ask it to build the entire roadmap in one turn.
3. Give the completed patch, handoff, and reviewer prompt to Astra or an available
   independent reviewer. Return specific findings to the implementation model.
4. Integrate accepted changes, update the handoff baseline, then start the next
   dependent assignment. A reviewer must see the code and artifacts, not only
   the implementer's summary.

Default order:

```text
T1: reproducible installation and CI
  -> T2: artifact and provenance correctness
  -> T4: scoped protein predictor and typed contracts
  -> T5: explanation method and fidelity checks
  -> T6: researcher workflow and export
  -> T7: frozen evaluation and final integration review

T3: scientific protocol may run alongside T1/T2 in its own document.
Its relevant protocol decisions must be frozen before T4/T5 evaluation.
```

Use one code-writing session at a time in the current checkout. For concurrent
code work, use isolated worktrees/branches seeded from the same reviewed baseline
and assign nonoverlapping ownership. Existing uncommitted/untracked work is not
automatically copied to a new worktree: preserve and transfer required local
changes explicitly before starting. Never reset or force-clean this checkout.
One integrator owns dependency/lock changes and merges. Do not switch a shared
checkout's branch while another model is using it.

## Common brief — paste this before any assignment

```text
You are implementing a defined part of Concordia, a protein mutation evidence
workbench with a scientifically evaluated explainability layer.

Repository: /Users/srikarjy/resume_projects/concordia

Read first:
- docs/protein-xai-build-instructions.md
- docs/audits/2026-10-19-repository-audit.md
- docs/audits/2026-10-19-file-inventory.tsv
- docs/adr/0004-concordia-product-depth.md
- Relevant current source and nearest tests.

The audit is a dated baseline, not a substitute for inspecting current code.
Start with git status, branch/HEAD, and the assigned path's current behavior.
Preserve all preexisting changes. Do not rewrite the application or create a
second review database/event ledger. Extend the existing review, artifact,
execution, assay-import, and export components.

Implement the assigned task; do not stop after proposing a plan. Make routine
reversible implementation decisions and run appropriate checks. Report a real
blocker precisely and complete independent work that remains possible. Do not
ask for repeated approval of ordinary coding steps.

Constraints:
- No deployment, pushes, remote merges, credential changes, paid model/GPU jobs,
  or externally sent messages. Deliver the local patch and a reviewable handoff.
- Default paid-compute budget is $0. Prefer existing local assets and bounded CPU
  runs. Do not call hosted biology providers as part of routine tests.
- Do not delete or rewrite historical scientific reports, weaken assertions to
  make tests pass, or silently skip failing required checks.
- Keep current 1IGV results and calibration scoped to that frozen example.
- Distinguish model prediction, explanation, policy trace, and biological evidence.
- A model confidence score, attractive heatmap, or LLM rationale is not validation.
- Keep imported evidence labeled as imported and supplied values labeled as
  supplied. Eligibility must follow verified protocol and provenance.
- Preserve rejected/failed results and raw artifacts. Never manufacture metrics,
  citations, successful execution, model pins, or scientific conclusions.

At completion, write docs/handoffs/<TASK-ID>.md with:
1. Starting commit and relevant preexisting changes.
2. Concrete behavior changed and files owned/modified.
3. Exact checks run and observed results, including failures/not-run checks.
4. Model/data/artifact/protocol identities when relevant.
5. Remaining limitations and instructions for the next assignment.
6. A concise diff summary and location of generated artifacts.

Do not mark a scientific gate passed just because software tests pass.
```

## T1 — Make installation, checks, and routes reproducible

Model: **GPT-6.1 Sol / High**. Dependency: none.

```text
Implement T1. Focus on reproducible installation/CI and intended page entrypoints.

Inspect .github/workflows/ci.yml, pyproject.toml, uv.lock, deployment dependency
manifests, Makefile, frontend build/Playwright configs, and vercel.json.

1. Reproduce the documented missing-Torch test-collection dependency and missing-
   Bio published runtime problem in a disposable environment where practical.
   Separate lightweight imports from optional model execution. Define dependency
   profiles that match actual test/runtime needs. Do not install every optional
   model package merely to make unrelated tests import.
2. Fix whole-tree typing ambiguity from multiple deployment app.py entrypoints
   with explicit checked roots. Make required checks meaningful and blocking.
3. Include local review and public browser tests in the appropriate CI jobs.
   Use isolated temporary state; do not erase existing researcher state.
4. Fix the build/navigation contract so the intended review and stability pages
   are both shipped where advertised. Preserve localhost-only writable reviews;
   a hosted review route must be an explicitly read-only replay at this stage.
5. Validate clean installation/packaging of the chosen runtime profile. If a
   required asset is not distributable yet, expose the exact missing prerequisite
   and hand it to T2 instead of relying on an invisible developer-machine file.

Deliver targeted regression checks, full relevant local checks, and T1.md.
GitHub CI remains unverified until a future authorized push actually runs it;
local success must not be reported as remote CI success.
```

Acceptance: required checks run in the declared environment; no duplicate-module
typing abort; intended routes work under production-like rewrites; tested local
and read-only public behavior remains distinct. No silent test exclusions.

## T2 — Repair artifact identity and evidence provenance

Model: **GPT-6.1 Sol / High**, reviewed by **Astra / XHigh**. Depends on T1.

```text
Implement T2 in reviewable subchanges. Inspect stability/measured.py, the ESM
extraction/baseline scripts, runtime/model_registry.py, verification/structure_rules.py,
verification/cross.py, and the structure-verification API path.

1. Enforce declared checkpoint revisions in real model loader calls; record
   resolved revisions and weight identities. Add a test that detects an omitted
   or wrong revision without downloading a large model.
2. Define a versioned manifest for all inputs needed by frozen stability serving:
   dataset, structures, embeddings, ensemble, ranker, calibration, and versions.
   Validate trusted file digests before unsafe model deserialization. Provide an
   explicit asset root and reproducible preparation/fetch instructions.
3. Move calibration/refitting writes out of MeasuredStabilityEngine initialization.
   Serving loads validated immutable artifacts. Preserve the existing frozen
   scientific outputs or explain and version any intended change.
4. Separate caller-supplied metric rule evaluation from provenance-backed claim
   verification. Supplied numbers must not become recorded_real/scientifically
   eligible merely because a rule passes. Design the compatibility/version change
   explicitly; do not globally disable legitimate verification to satisfy a test.
5. Require stored source/execution artifacts for claims of executed evidence.
   Keep support status, execution provenance, and biological validation separate.

Test tampered/missing artifacts, revision mismatch, immutable initialization,
supplied-metric provenance, and a valid retained-evidence path. Use small fixtures
for software checks and preserve their fixture labels. Deliver T2.md.
```

Acceptance: serving does not recalibrate or mutate shared scientific assets;
recorded pins match actual loading behavior; supplied metrics cannot self-certify
execution; regression outputs and compatibility are accounted for.

## T3 — Design the scientific protocol and assess feasibility

Model: **GPT-6 Astra / XHigh**. Can run alongside T1/T2. Code is read-only.
Owns `docs/protein-xai-study-protocol.md` and `docs/handoffs/T3.md`.

```text
Complete T3 as a scientific-methods reviewer. Read current source and primary
literature. Do not change product code, run hosted inference, or tune on test labels.

Specify the initial scalar prediction target, folding-stability sign convention,
supported input scope, candidate model/checkpoint, and exact explanation question.
Assess whether the proposed model actually exposes the inputs/gradients needed.

Define three distinct evaluations: predictive performance, model-explanation
fidelity, and researcher-task utility. For each, specify a primary endpoint,
comparator, unit of analysis, failure criterion, and uncertainty procedure.

Audit data overlap with upstream model training as well as Concordia's own
training/tuning. Specify protein/family separation, assay compatibility,
calibration population, and how unknown training exposure is reported.

For XAI, specify baselines/interventions, feature-to-residue mapping, numerical
checks, randomization controls, matched structural controls, and held-out
intervention tests that do not merely repeat how the explanation was constructed.
Separate fixed-structure model sensitivity from biological epistasis/causality.

Freeze the pilot selection rule, settings, resource limit, and analysis before
examining outcomes. Propose a bounded CPU feasibility pilot; label it as such.
Define how its measurements will inform a separately frozen larger study, without
reusing the final evaluation set for method selection. Do not invent a sufficient
sample size or assume generalization from 1IGV.

Cite primary sources. Mark uncertain claims and unavailable tests. Compare related
protein XAI work before proposing novelty. Deliver a concrete protocol and T3.md,
including precise decisions/blockers for T4 and T5.
```

Acceptance: an engineer can implement/evaluate the specified method without
inventing its output target, controls, split, or success criterion. Unresolved
feasibility is an explicit experiment, not a declaration of impossibility.

## T4 — Build a real, scoped predictor with typed records

Model: **GPT-6.1 Sol / High**. Depends on T1/T2 and relevant T3 decisions.

```text
Implement T4 using the existing execution/artifact system. Introduce the minimal
typed ProteinInput, PredictionTarget, ModelExecution, ExplanationSpec/Result,
and validation-reference contracts needed for the planned workflow. New protein
XAI modules can live under src/concordia/protein_xai/; do not duplicate storage.

Implement the protocol-selected pinned predictor adapter, initially assessing
ThermoMPNN. Reproduce a small upstream example; verify sign, numeric parity,
model/weight identity, and fresh computation. A frozen lookup service is not
fresh model inference. Keep the old 1IGV path available as a separate example.

Validate sequence/structure mapping, chain and insertion codes, missing residues,
wild-type identity, and mutation scope. Refuse unsupported inputs clearly. Do not
transfer the old calibration or aggregate rank score to the new predictor.

Persist raw inputs/outputs, settings, versions, timing, and measured memory.
Provide exact saved-output replay with no model call. Reruns produce new records.
Start with one bounded local CPU example and record actual resource use.

Add meaningful contract, mapping, invalid-input, artifact, and parity checks.
If runtime assets are unavailable, implement the honest unavailable path and
report which real-execution gate is blocked; do not fabricate a successful sample.
Deliver T4.md with stable interfaces and one inspectable execution if feasible.
```

Acceptance: a valid scoped input reaches actual model computation; invalid inputs
fail before execution; replay verifies saved artifacts; downstream explanation
code receives an unambiguous scalar target and input mapping.

## T5 — Implement explanations and test fidelity

Model: **GPT-6.1 Sol / High**, scientific review by **Astra / XHigh**.
Depends on T3 and T4.

```text
Implement T5 against the frozen protocol and T4 interfaces.

First implement a controlled model-sensitivity baseline. Keep a substitution
landscape distinct from attribution of one chosen prediction. Record exact
interventions, fixed inputs, all resulting outputs, and matched controls.

Then implement one protocol-approved attribution method only if the adapter
supports it. For integrated gradients, specify scalar output, tensors, baseline,
integration path, residue aggregation, and convergence/completeness tolerances.
Test these properties; do not assume them from the method's name.

Implement model-randomization and known-behavior controls, explanation stability,
and fidelity on held-out interventions with matched random/structural controls.
Do not evaluate an occlusion explanation solely on the same occlusions used to
build it. Label retraining-dependent checks not evaluated if training is unavailable.

Persist method/version, target execution, raw arrays, mapping, baseline, seeds,
diagnostics, failures, and resource use. A failed method remains inspectable with
a failed validation status. Do not substitute attention/pLDDT or LLM prose for XAI.

Deliver numerical checks plus a bounded real-model example where feasible,
clearly separated from fixtures. Produce T5.md with results and limitations.
```

Acceptance: one exact prediction has an inspectable, replayable explanation;
the relevant fidelity checks were executed and their actual outcomes are visible.
A failure is a valid research result, but not a validated explanation release.

## T6 — Put explanations into the researcher's workflow

Model: **GPT-6.1 Sol / High**; **Claude Sonnet 5.5** is an alternative if already
available and the contracts are stable. Depends on T4/T5.

```text
Implement T6 by extending review/workflow.py, api/reviews.py, review-main.tsx,
the existing structure viewer, and export logic. Reuse the existing review store.

Deliver this journey: import/reference and candidates -> inspect prediction ->
inspect explanation and fidelity status -> compare evidence -> select/exclude/
defer with reason -> import assay outcomes -> export and verify.

Every displayed value must identify its source, predictor, property, units,
direction, and execution mode. Distinguish ranking policy from numeric prediction.
Show uncertainty only for its supported population. Synchronize residue tables
and structure selection through the validated mapping, including missing residues.

Link evidence artifacts into review revisions. Preserve decisions made before
assay import. Export raw explanation data, method/baseline, diagnostics, model/data
identities, and an offline verifier. Test that corruption is rejected.

Add an end-to-end browser test and an independent export-verification test.
Exercise failures and refusal paths as well as the happy path. Keep local review
authorization and read-only public replay boundaries intact. Do not add a new
hosted multiuser service or provider calls in this assignment.

Deliver T6.md and a complete local demonstration using a clearly labeled fixture
or real saved execution, with provenance preserved in both cases.
```

Acceptance: a researcher can complete the journey and another person can verify
the exported record. UI screenshots alone are not completion evidence.

## T7 — Run the frozen pilot and integrate the result

Implementation: **GPT-6.1 Sol / High**. Independent review: **Astra / XHigh** or
**Claude Opus 5.5** with access. Depends on T1–T6.

```text
Implement/run T7 using the versioned scientific protocol and the reviewed code.

Build any missing evaluation harness against retained predictions/explanations.
Run only the frozen pilot within its declared local resource budget. Do not enlarge
the experiment, retune on final labels, call paid services, or omit failed cases.

Report predictive accuracy, explanation fidelity, and workflow verification
separately. Include baselines, refusal/acceptance coverage, interval width when
applicable, uncertainty at the appropriate protein/family level, leakage findings,
excluded cases, compute cost, and all negative results. Repeated seeds are not
independent biological replicates.

Run the relevant full software checks and the complete researcher journey.
Update capability documentation to match actual demonstrated behavior. Record
not-run gates, including researcher interviews/prospective assays where absent.
Never describe a small feasibility pilot as broad biological validation.

Deliver an immutable pilot report/artifact manifest, T7.md, and a final integration
summary that another model can independently audit. Do not deploy or push.
```

Acceptance: complete, reproducible accounting of the declared pilot and integrated
workflow. A performance claim requires the protocol's criterion to be met; an
honest negative report can still complete the research assignment.

## Independent reviewer prompt

```text
Review the completed Concordia assignment independently. This is a read-only
review: inspect the actual diff, relevant current source/tests, task handoff,
protocol, and saved artifacts. Do not trust the author's summary as evidence.

Check correctness, compatibility, failure behavior, scientific semantics,
artifact identity, leakage, and whether the checks establish the stated claim.
Distinguish code defects, missing validation, and optional improvements. Verify
the crucial claim with a bounded reproducer when feasible and within the same
zero-paid-compute/no-deployment constraints.

Specifically look for fake model execution, decorative XAI, inconsistent units,
unforced model revisions, unsupported calibration transfer, self-certified
provenance, and test changes that conceal failures.

Return:
- Blocking findings with file/line, trigger, consequence, and concrete remedy.
- Nonblocking findings separately.
- Checks you actually executed and their results.
- Acceptance decision for THIS task and the exact evidence still missing.

Do not certify biological validity from software tests or agreement between LLMs.
If no blocker is found, say so; do not invent findings to fill a checklist.
```
