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
