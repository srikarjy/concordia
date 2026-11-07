# Concordia researcher product review — 2026-10-18

## Intended user and problem

The clearest initial user is a computational protein-engineering PhD student or
postdoc who must explain mutation selection to a PI, collaborator, or reviewer.
Harvard is a possible research setting, not evidence of adoption or endorsement.
This assessment is based on repository inspection and published work, not user
interviews with Harvard researchers.

The proposed job: review candidate mutations alongside model provenance,
uncertainty, biological constraints, exclusions, and reproducible result records.
The research hypothesis is that this reduces manual reconciliation across scripts,
structures, prediction tables, and lab-meeting notes. Time savings and improved
experimental hit rates have not been demonstrated here.

## What the current page actually does

- Scores only mutations present in the frozen 1IGV table, with constraints.
- Orders accepted candidates using ThermoMPNN/one-hot rank averages. The displayed
  numeric predictions and intervals come from the persisted ensemble; ranking
  and displayed predicted energy are distinct quantities.
- Refuses protected sites, embedding-distance outliers, and multi-mutants.
  Unseen positions and buried-core residues are soft flags.
- Displays a bundled predicted structure and offers a separate authenticated
  structure-prediction action. Structure agreement is not stability validation.
- Offers a separate protein-upload workspace. Uploaded sequences do not inherit
  the 1IGV predictor, calibration, or validation results.

The interval mean width of 4.67 kcal/mol is a held-out aggregate, not the width of
both displayed example intervals. Similarly, 94.1% empirical coverage is not a
94.1% probability that an individual candidate is useful. The visible example
intervals alone do not establish decision utility on a new protein.

## Research grounding

- Harvard's Marks-associated ProteinGym project evaluates mutation-effect models
  against experimental assays and supplies benchmark comparisons. This supports
  focusing on evaluation and experimental evidence rather than model confidence:
  https://github.com/OATML-Markslab/ProteinGym
- A Harvard dissertation describes machine-learning-assisted antibody optimization
  as part of improving experimental pipelines. It supports this user/workflow
  hypothesis, not a claim that the author needs Concordia:
  https://dash.harvard.edu/entities/publication/f3f7286a-450e-4bd8-903a-a8753a61bb6e
- ThermoMPNN predicts point-mutation stability changes using a protein structure.
  Its authors supply the underlying method; Concordia's contribution must be the
  surrounding evidence and decision workflow, not ownership of that predictor:
  https://github.com/Kuhlman-Lab/ThermoMPNN
- The ThermoMPNN-D study reports difficulty capturing double-mutant epistasis.
  Refusing multi-mutants in this singles-only implementation is defensible, but
  is not a universal claim that no double-mutant models exist:
  https://pmc.ncbi.nlm.nih.gov/articles/PMC11659742/

## Debug findings and fixes

The initial page populated saved results while the input field contained a
different candidate set. The saved origin was not visibly identified. The page
now identifies the result source and lists the actual displayed candidate set,
including while a new request runs or fails.

A failed initial artifact fetch left the page on a loading message. It now checks
HTTP status and displays a load error. Browser regression tests cover both cases.
The page also clarifies the energy sign convention, benchmark status, and held-out
coverage/width labels. These changes do not change scores or scientific gates.

## Highest-value next experiment

Recruit one protein-engineering researcher with a retrospective, shareable
mutation-assay dataset. Walk through their existing selection/review process;
measure time to assemble an auditable report and whether another person can
reconstruct the decision. Record baseline performance and reasons for exclusions.

Only then extend to arbitrary proteins with explicit sequence/structure mapping,
assay conditions and units, assay-specific labels, family-aware held-out testing,
simple baseline comparisons, and calibration applicable to the new setting.
Importing experimental results and exporting a reviewable decision report would
connect the current demo to that workflow. None of these future requirements is
satisfied merely by accepting a FASTA upload.

## Remaining boundaries

Local tests do not verify email delivery, production account isolation, service
availability, deployed inference, or biological utility. Existing deployment
notes describe conflicting credential destinations (HF owner gateway versus the
Supabase path used by the current UI); reconcile them against deployed state
before operating deployment scripts. No secrets or deployment settings were
changed during this review.

## Verification performed in this review

- Full Python pytest suite passed.
- Frontend TypeScript check and both builds passed.
- Public-page browser suite: 5 passed, including two new regression cases.
- Existing workspace browser suite: 8 passed using port 7864 and isolated
  temporary state because port 7861 was already occupied.
- Supabase protein contract tests: 3 passed.
- Local typed scoring of A13Q, K6Q, L52Y, Q21E, and A13Q:K6Q: three ranked,
  two refused, ledger intact. No hosted inference was requested.
- Build warnings remain for large visualization bundles and legacy 3Dmol eval;
  these builds succeeded. Changes are local and were not deployed.
