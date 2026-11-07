# Concordia portfolio finish plan

Date: 2026-10-20.
Owner objective: finish a credible AI/biotech portfolio piece after months of work.
Reviewed baseline: `9b437aa` on `feature/antibody-boltz-concordia`.

**This is the controlling delivery plan for the next portfolio milestone.**
It supersedes the older task pack's open-ended release sequence. It preserves
the scientific definitions and claim boundaries in `protein-xai-study-protocol.md`.
Do not weaken a scientific gate to call a feature validated. Larger scientific
studies are separate from completion of this portfolio milestone.

## 1. The problem and the demonstration

A researcher has candidate protein mutations, model predictions, and assay
results in separate files. They need to compare compatible evidence, understand
limitations, record why they selected or rejected a candidate, and let a
collaborator reconstruct that decision.

Finish this single journey:

**Reference and mutations → prediction evidence → explanation or explicit
diagnostic status → select/exclude/defer → assay comparison → verified export.**

The primary interface is the existing variant review. The frozen 1IGV example
is the demonstration case. New inference, when executed, is explicitly separate
from the saved ridge predictions, ranker, and calibration.

The portfolio should demonstrate:

- practical Python/API and React engineering;
- typed model inputs, residue mapping, units, and provenance;
- meaningful failure handling and independent export verification;
- one bounded investigation of real model execution and explainability;
- a readable account of what succeeded, failed, and remains untested.

Do not require a prospective wet-lab result, a powered researcher study, or a
new-protein generalization claim to finish this engineering portfolio release.
Those studies are required only for the corresponding scientific claims.

## 2. Scope is closed

Reuse the existing review store, content-addressed storage, execution contracts,
assay importer, structure viewer, and export implementation.

Do not add new model providers, agent frameworks, databases, antibody campaigns,
genomic experiments, virtual-cell features, account systems, or design pipelines.
Do not conduct a general rewrite or a whole-repository security program.
Preserve existing workflows without expanding them.

Use a $0 paid-compute budget. No hosted biology calls, GPU rentals, deployment,
pushes, remote merges, credentials changes, or external messages are authorized
by this document. Prepare a local release candidate and exact publication steps.
Publication requires the user's authorization for that concrete release unless
already granted in the active session.

Use one code-writing session at a time in this checkout. The user does not need
multiple agents to agree. An implementation model delivers a patch and evidence;
a separate review session checks the consequential claims.

## 3. Current state: measured, not assumed

The 2026-10-20 review ran against `9b437aa`:

- `make verify`: passed, including 546 Python tests, Ruff, and all configured
  type-check stages.
- Frontend check, workspace build, and stability build: passed.
- Browser suites: 8 workspace, 3 local, and 7 public tests passed. Initial
  server binding was blocked by the sandbox; the permitted local run passed.
- The committed replay ZIP's standalone verifier: passed.
- A clean `git archive HEAD` failed the scientific-asset preflight. Seven
  inputs in the serving manifest are absent from Git, including calibration.
- Additional bounded reproducers exposed the defects listed in F1.

These are local results from the reviewed baseline. They do not establish
remote CI, hosted availability, or biological validity. Recheck the current
tree before implementing; later commits may have fixed an item.

T1 substantially improves installation and routes. T2 is **not accepted yet**
because the reviewed identity and provenance paths still have gaps. T3 is an
implementation specification with unexecuted scientific gates. Do not rerun
T1–T3 from scratch.

## 4. Four sequential jobs

### F1 — Close the reproducibility and correctness defects

Suggested owner: Codex/Sol or another implementation model.
Read `docs/reviews/2026-10-20-t1-t3-review.md` first.

1. **Execution provenance.** Replace the loose execution JSON check with a
   validated record and explicit links. Require successful terminal execution,
   matching input/model/settings identities, and evidence derived from the
   relevant output. A sequence path on one branch and an unrelated execution
   on another must not qualify. Reject malformed, failed, missing, unrelated,
   and corrupt records with a structured invalid/unverifiable result. Preserve
   an actual supported path with consistent retained records. Do not mark
   caller-supplied bytes as authentic merely because they have hashes.
2. **Embedding cache identity.** Before reusing a cache, validate its digest,
   sequence/variant mapping, feature schema, and recorded model identity.
   Never fill unknown historical metadata using today's checkpoint constant.
   Preserve historical files and label unverified origin honestly. Use a
   verified manifest for the frozen cache; give newly generated caches their
   own persisted provenance. Do not silently regenerate historical results.
3. **Assets and clean-clone checks.** Account for every file required by the
   serving manifest, including calibration. Supply a licensed, digest-checked
   acquisition or reproducible preparation path and invoke it before CI's
   scientific regressions. Prefer existing distributable sources or a small
   permitted bundle; do not commit large data/weights indiscriminately.
   Document source, redistribution terms, sizes, and hashes. Test from a clean
   snapshot without reading ignored files from the developer checkout.
   If a release bundle needs publishing, prepare and verify it locally and
   identify that exact remaining publication dependency. Do not claim remote
   reproducibility while the acquisition path is unavailable.
4. **Replay revision correctness.** Exports must match the displayed revision.
   Generate revision-specific static exports, or restrict final-only downloads
   with explicit UI wording. A historical screen must never silently download
   the final shortlist. Test CSV/JSON/ZIP contents, not only HTTP 200.
5. Update the stale installation guidance about startup recalibration and
   the incomplete asset list. Add regression tests for the reproduced cases.

**Exit:** new regression tests pass; valid existing behavior passes; actual
asset checks cover the complete manifest; a clean snapshot can execute the
declared checks using only the documented inputs. Any publishing dependency
is explicitly unresolved. Deliver `docs/handoffs/F1.md`.

**Status 2026-10-20:** local implementation complete; see `handoffs/F1.md`.
The verified archive exists locally and the clean snapshot preflight succeeds
after extraction. Public hosting and fresh remote CI remain unverified.

F1 can be reviewed while F2's local feasibility work is prepared. An external
asset-publication dependency must not prevent independent local work, but it
remains a release reproducibility gate.

### F2 — Finish one bounded predictor/explanation investigation

Suggested owner: Codex/Sol. This combines the smallest useful T4/T5 slice.

Read the current T3 protocol and reuse the existing local ThermoMPNN material.
Inspect assets and dependencies before downloading anything. Keep this runtime
optional so the base review installation stays lightweight.

1. Implement a minimal scoped adapter for one canonical chain and one
   substitution, with strict sequence/structure/WT mapping and explicit
   refusals. Persist model source and actual weight digests, exact inputs,
   settings, raw output, sign conversion, resource use, and terminal status.
2. Target exactly `f = -raw ThermoMPNN ddG`, kcal/mol, higher = more stable.
   Do not attach the old 1IGV ridge intervals or rank-average scores to it.
3. Run T3's predeclared `1IGV.pdb_S1A` feasibility case on CPU, float32,
   seed `20261019`, within **20 minutes and 8 GiB peak resident memory**.
   Enforce the cap in the process controller. Do not inspect assay labels
   during this new feasibility run.
4. Verify ordinary upstream/adapter parity. Test the embedding path and
   gradients before calling anything integrated gradients. Follow T3's
   declared tolerances and 8-step feasibility calculation. Persist failures.
5. Add the bounded context-substitution diagnostic and its exact queried
   outputs. If the gradient gate passes, run the separate 32-step numerical
   extension, with only the protocol's permitted 64-step retry. Do not expand
   into a multi-protein evaluation during this assignment.
6. Implement exact saved-output replay and link diagnostic artifacts to the
   exact prediction. Preserve failed/unavailable results as typed records.

**Finite outcome rule:** deliver the executed outcome, including a negative
one. Repair concrete implementation bugs and rerun only the affected check.
Do not search for new models, tune tolerances after seeing results, or repeat
experiments until the scientific outcome looks favorable.

If real execution cannot run within the declared resources, ship the review
workflow using verified recorded evidence and a clear unavailable/failed
investigation report. Mark T4 real execution or T5 attribution as incomplete
as applicable. That outcome permits a **limited research-software portfolio**
release; it does not permit advertising working or validated protein XAI.
Never satisfy this rule by deliberately omitting feasible required work.

**Exit:** one inspectable real execution with diagnostics, or a reproducible
failure/unavailable record with the exact blocker; a complete attempt log;
artifact replay; tests for contracts, mapping, and failure behavior. Deliver
`docs/handoffs/F2.md` and a machine-readable run/artifact manifest.

**Status 2026-10-20:** local contract and replay implementation complete; see
`handoffs/F2.md`. The preregistered S1A attempt recorded an unavailable result
because the pinned upstream checkout and checkpoint are absent locally. T4/T5
scientific execution remains incomplete; no fresh prediction or attribution is
claimed.

### F3 — Complete the reviewer journey and portfolio presentation

Suggested owner: Claude or Codex/Sol after F2 contracts stabilize.
This is the bounded T6 assignment.

1. Extend the current candidate review to display the saved prediction and
   its source, units, direction, execution mode, and diagnostic status.
2. If a usable explanation exists, show its residue table and synchronize
   structure selection using verified mapping. Show method, target, baseline,
   and diagnostics. Failed/unavailable explanations get an explicit status.
   Do not display a success-colored overlay when numerical/mapping gates fail.
3. Preserve human select/exclude/defer decisions, reasons, protected-position
   overrides, revisions, and decisions made before assay import.
4. Export prediction and diagnostic records, mappings, source identities,
   raw arrays when present, decisions, and a standalone integrity verifier.
   Verify another person can inspect the report without this checkout.
5. Produce a default public **static replay** requiring no account or paid
   provider. No external model calls should be necessary to complete the
   portfolio demonstration. Keep optional integrations outside its main path.
6. Update README and the short demo narrative around this single workflow.
   Clearly label the source and limits of the recorded example. Separate
   implemented software, executed model work, and untested research claims.
   Move historical topics to links instead of growing the main explanation.

**Exit:** a browser test completes the local journey; the static replay
navigates correctly; exports match the selected revision; clean exported bytes
verify and deliberately corrupted copies fail. Include a short demo script
and screenshots from the actual built UI. Deliver `docs/handoffs/F3.md`.

**Status 2026-10-20:** complete for the bounded static replay. The public
replay exposes the unavailable fresh-model result, packages its record in each
revision bundle, and verifies its bytes. The demo script and built screenshot
are in `portfolio-demo.md` and `screenshots/variant-review-replay.png`.

### F4 — Verify once and package the release candidate

Suggested owner: implementation model for packaging; Astra or another fresh
reviewer for the final bounded review.

1. Run the declared clean-install/asset path, Python checks, both builds,
   all three browser suites, and standalone export verification.
2. Run the five-minute demonstration from a clean browser/state directory.
   Show a valid case, a refused or unavailable case, a recorded decision,
   assay comparison, and a verified exported report.
3. Freeze the final code identity, dependency locks, demo artifact hashes,
   resource measurements, and actual checks in `docs/PORTFOLIO_RELEASE.md`.
4. Include a compact result table: prediction execution, explanation
   diagnostics, workflow/export verification, and unrun scientific evaluations.
   Report negative results. Do not invent accuracy or researcher-utility gains.
5. Perform the final review against the checklist below. Repair blockers in
   affected paths and retest them. New ideas become follow-up issues in the
   release document; they do not restart the roadmap.
6. Prepare the exact publication payload and commands. Clearly distinguish a
   locally accepted release candidate from a published release and green
   remote CI. Do not silently publish.

**Exit:** `docs/PORTFOLIO_RELEASE.md` contains the acceptance decision,
reproduction instructions, exact evidence paths, limitations, and publication
status. Deliver `docs/handoffs/F4.md`.

**Status 2026-10-20:** complete as a local release candidate; see
`PORTFOLIO_RELEASE.md` and `handoffs/F4.md`. Commit, push, remote CI, asset
hosting, and deployment remain publication steps outside this local candidate.

## 5. Definition of finished

The portfolio release candidate is complete when:

- [x] A newcomer can understand the researcher problem and launch the saved
  demonstration using the documented clean setup.
- [x] The complete import/review/decision/assay/export journey works.
- [x] Values have correct identities, units, source labels, and revision links.
- [x] Unsupported evidence cannot promote itself into verified execution.
- [x] The bounded model/explanation investigation has a recorded terminal
  outcome; the public wording matches that outcome.
- [x] Export verification succeeds independently and detects tampering.
- [x] Required software checks pass with documented, obtainable assets.
- [x] The README, demo, and case study describe the same current product.
- [x] The final review has no unresolved blocker affecting this journey or
  its factual claims. Optional improvements are explicitly deferred.

Publication adds separate checkboxes:

- [ ] The user-authorized revision is pushed and its actual CI result checked.
- [ ] Any required public assets are available through the tested acquisition path.
- [ ] The intended static deployment is verified through the complete demo path.

**Stop adding features when the release-candidate checklist passes.** A failed
scientific hypothesis can be part of a finished research-software portfolio.
A broken workflow, fabricated provenance, or falsely advertised XAI cannot.

## 6. How the next model should work

At the start:

1. Read this file, the dated review, and the latest `F*.md` handoffs.
2. Check Git status, branch, HEAD, and the assigned current source/tests.
3. Select the first unfinished F job. Do not repeat completed work.
4. Implement the job, run meaningful checks, and leave a concise handoff.
   Use reasonable implementation judgment; do not ask the user to choose
   routine coding details.

Each handoff must state starting/final code identities, owned changes, actual
commands/results, artifact locations/digests, unresolved blockers, and the next
job. Use `passed`, `failed`, `unavailable`, or `not run`. Never use `done` for a
planned, queued, mocked, or unexecuted scientific result.

Do not claim all T1–T7 are complete simply because the portfolio scope is
finished. State which research assignments remain outside this milestone.

### Copy-paste implementation prompt

```text
Finish the next unfinished job in docs/PORTFOLIO_FINISH_PLAN.md.
Repository: /Users/srikarjy/resume_projects/concordia

Read that file, docs/reviews/2026-10-20-t1-t3-review.md, and the latest handoffs.
Inspect the current code before trusting historical summaries. Implement the
assigned job to its concrete acceptance checks; do not give me another roadmap.
Preserve existing work, scientific outputs, and honest failure records.
Use the existing review/storage/export system. Keep the $0 and no-publication
boundaries. Do not expand the scope. Write the specified F handoff with evidence.
If a blocker prevents one part, finish independent work and report the smallest
exact missing input or authorization needed. Never fabricate a passing result.
```

### Copy-paste final reviewer prompt

```text
Review Concordia's portfolio release candidate against
docs/PORTFOLIO_FINISH_PLAN.md. Read the actual patches, F handoffs, saved
artifacts, and current tests. Reproduce consequential claims within the local
$0 budget. Inspect a clean setup, the reviewer journey, provenance rejection,
revision-correct exports, and the exact model/explanation labels.

Return blocking findings with location, trigger, consequence, and remedy.
Separate optional improvements. Give an explicit acceptance decision for the
portfolio milestone and the actual checks run. Do not require deferred
multi-protein, wet-lab, multiuser, or researcher studies unless the release
makes claims that depend on them. Do not invent findings or expand the roadmap.
This is a review; do not modify product code or publish anything.
```
