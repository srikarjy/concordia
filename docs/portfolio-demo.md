# Five-minute Concordia reviewer demonstration

This demonstration is a local, read-only replay. It uses saved 1IGV review
data and does not call a model, a hosted provider, or an account service.

## Build and open the replay

```sh
PYTHONPATH=src .venv/bin/python scripts/build_review_replay.py
python3 scripts/build_static_stability.py
python3 scripts/serve_static_preview.py --port 4175
```

Keep that terminal running and open http://127.0.0.1:4175/review.
For editable local reviews, build with `cd frontend && npm ci && npm run build`,
then from the repository root run `PYTHONPATH=src .venv/bin/python -m concordia.cli
serve-workspace --state-root .concordia/portfolio-local --frontend frontend/dist --port 7860`.
Open http://127.0.0.1:7860. Browser tests use separate temporary servers.

## Walkthrough

The [execution runbook](PORTFOLIO_EXECUTION_RUNBOOK.md) covers installation,
the fresh public-data workflow, all software checks, and deployment after approval.

1. Read the replay banner: it identifies the decisions as illustrative and
   says outcomes were imported after the decisions.
2. Inspect the candidate table. Each source retains its metric, unit, and
   preferred direction; disagreements remain visible.
3. Select revision 1. The table returns to its original unreviewed state and
   the `Selected CSV` download becomes `r1-selected.csv`.
4. Return to revision 7. Inspect the recorded decision for K6Q and the later
   published assay outcome.
5. Open `Fresh model execution`. Its checksum-verified record says fresh
   ThermoMPNN execution is unavailable because the pinned local source and
   checkpoint are absent. It contains no prediction or attribution claim.
6. Download the complete bundle. Extract it and run:

   ```sh
   python3 -I verify.py
   ```

   The verifier checks every review revision, its raw inputs, and the attached
   feasibility record. Change one byte in `diagnostics/thermompnn-feasibility.json`
   and rerun it to see `Diagnostic hash mismatch`.

7. Follow **freshly executed 1PGA baseline and real-data results** from the replay
   banner. Compare Ridge with the training-mean baseline, read the single-protein
   limitations, inspect the review history, and download its verified bundle.

## What this demonstrates

The portfolio artifact demonstrates provenance-aware review software:
revision-correct exports, human decisions preserved before assay import,
constraint visibility, and an independently checked archive. It does not
demonstrate fresh ThermoMPNN inference, explanation fidelity, prediction
accuracy on new proteins, biological validation, or researcher-utility gains.
