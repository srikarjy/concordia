# D1 Pilot Summary

- Task 1: corrected motif-frame measurement; global fit is generated chain A and
  motif is retained chain B in the same complex frame; 13 cached rows recomputed.
- Task 2: holdout refusal rate is computed from 152 decisions: 152 refused,
  1.0; the prior literal was also 1.0.
- Task 3: completed all 16 pilot pairs with 3 new cached Boltz calls; 0/16 pass
  the manifest thresholds.
- Task 4: experimental 1PGB control produced 0.390 Å and 0.594 Å CA RMSD for
  two sequences, so the downstream pipeline is functional.
- Task 5: all four backbones have no CA chain breaks; lengths are 66/66/64/52,
  and none is implausibly compact by the recorded check.
- Recommendation: NO-GO for the full 64-pair campaign. The control passes while
  every D1 design fails badly (global 10.657–49.737 Å; motif 19.545–73.452 Å),
  indicating the generated backbones are not designable/self-consistent. Revisit
  RFdiffusion contig/backbone generation before spending more Boltz quota.

# D1 Pilot State

Task 1 — DONE

- Findings: Boltz receives the full complex (designed chain A plus retained chain B). Global Kabsch fit is chain A; the seven motif residues are on chain B and are measured after that chain-A transform, so the metric is intentionally in the designed-complex frame.
- Cached recomputation: 13 completed designs; corrected table is `results/d1_pilot_motif_metrics.csv`.
- Atom counts: generated-chain global fits use 52–66 CA atoms; motif measurements use 7 CA atoms.
- Controls: backbone-self and Boltz-self RMSDs are approximately `7e-15` and `9e-15` Å.
- Files changed: `src/concordia/design/loop.py`, `tests/unit/test_de_novo_design.py`, `results/d1_pilot_motif_metrics.csv`.
- Next step: Task 2 — compute the holdout refusal rate instead of assigning a literal.

Task 2 — DONE

- Findings: replaced the literal holdout refusal rate with a computation over the
  effective holdout using the existing T1/T3 refusal gate; T2 is explicitly not
  evaluated without a holdout-distance calibration.
- Result: old value `1.0`; computed value `1.0` (`152` refused / `152` evaluated).
- Ranker reporting: selected-ranker name now comes from the persisted ranker
  artifact rather than a duplicated literal.
- Gates: strict stability mypy passed; full pytest passed (`443` tests). Ruff remains
  blocked by two pre-existing I001 findings in `stability/structure_aware.py`, which
  are outside this task and unchanged.
- Files changed: `scripts/evaluate_tsuboyama_uncertainty.py`,
  `scripts/evaluate_structure_aware.py`, `tests/unit/test_tsuboyama_uncertainty.py`.
- Next step: Task 3 — resume only uncached backbone-4 Boltz pairs.

Task 3 — DONE

- Cache inventory: backbone 4 sequences 2–4 were the only missing Boltz pairs;
  the cached ProteinMPNN response supplied all three sequences, so no RFdiffusion
  or ProteinMPNN calls were made.
- Hosted calls: 3 Boltz-2 calls, all parsed and content-addressed; response
  digests are recorded in `data/design/d1_1igv_pilot_v2/boltz-cache-index.json`.
- Results: appended to `results/d1_pilot_motif_metrics.csv`; 16 total designs,
  zero passing the manifest thresholds. Backbone-4 scRMSDs were 17.252, 24.468,
  17.975, and 33.456 Å for sequences 1–4; all had 52 global and 7 motif CA atoms.
- Gates: script-local lint fixed; strict stability mypy passed; full pytest passed
  (443 tests). Repo-wide ruff still reports only the two pre-existing I001 findings
  in `src/concordia/stability/structure_aware.py`.
- Files changed: `scripts/resume_d1_boltz.py`,
  `results/d1_pilot_motif_metrics.csv`,
  `data/design/d1_1igv_pilot_v2/boltz-cache-index.json`.
- Next step: Task 4 — run one bounded designability control.

Task 4 — DONE

- Control: experimentally resolved RCSB PDB `1PGB`, monomer chain A, 56 residues;
  two sequences requested in one ProteinMPNN call and two Boltz monomer calls.
- Results: native-chain CA RMSDs were `0.390` Å and `0.594` Å, with 56 aligned
  atoms for both sequences. Both are below the approximately 2 Å control criterion.
- Interpretation: ProteinMPNN, Boltz input formatting, CA correspondence, and
  chain handling work on a known-good monomer; the D1 failure is in the generated
  RFdiffusion backbones, not the downstream measurement pipeline.
- Gates: strict stability mypy passed; full pytest passed (443 tests). Ruff remains
  blocked only by the two pre-existing I001 findings in
  `src/concordia/stability/structure_aware.py`.
- Files changed: `scripts/run_d1_designability_control.py`,
  `data/design/d1_control/1PGB.pdb`, `data/design/d1_control/cache-index.json`,
  `data/design/d1_control/control-report.json`.
- Next step: Task 5 — local sanity checks on all four RFdiffusion backbones.

Task 5 — DONE

- Geometry: chain-A lengths were 66, 66, 64, and 52; all four had zero
  consecutive CA distances over 4.2 Å.
- DSSP on the actual returned coordinates found 58/64/62/49 helical residues,
  no sheet residues, and 8/2/2/3 loop residues respectively.
- Radius of gyration was 15.921/28.255/27.466/22.417 Å; no compactness flag fired.
- Gates: strict stability mypy passed; full pytest passed (443 tests). Repo-wide
  ruff remains red only for the two pre-existing stability import-order findings.
- Files changed: `scripts/summarize_d1_backbones.py`,
  `results/d1_backbone_sanity.json`.
