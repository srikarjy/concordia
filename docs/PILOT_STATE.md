# D1 Pilot State

Task 1 — DONE

- Findings: Boltz receives the full complex (designed chain A plus retained chain B). Global Kabsch fit is chain A; the seven motif residues are on chain B and are measured after that chain-A transform, so the metric is intentionally in the designed-complex frame.
- Cached recomputation: 13 completed designs; corrected table is `results/d1_pilot_motif_metrics.csv`.
- Atom counts: generated-chain global fits use 52–66 CA atoms; motif measurements use 7 CA atoms.
- Controls: backbone-self and Boltz-self RMSDs are approximately `7e-15` and `9e-15` Å.
- Files changed: `src/concordia/design/loop.py`, `tests/unit/test_de_novo_design.py`, `results/d1_pilot_motif_metrics.csv`.
- Next step: Task 2 — compute the holdout refusal rate instead of assigning a literal.
