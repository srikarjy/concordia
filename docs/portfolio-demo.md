# Five-minute Concordia reviewer demonstration

This demonstration is a local, read-only replay. It uses saved 1IGV review
data and does not call a model, a hosted provider, or an account service.

## Build and open the replay

```sh
PYTHONPATH=src .venv/bin/python scripts/build_review_replay.py
cd frontend
npm run build
npm run test:public
```

Open the static preview at the URL printed by the public test server, then
open the Variant review workspace.

## Walkthrough

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

## What this demonstrates

The portfolio artifact demonstrates provenance-aware review software:
revision-correct exports, human decisions preserved before assay import,
constraint visibility, and an independently checked archive. It does not
demonstrate fresh ThermoMPNN inference, explanation fidelity, prediction
accuracy on new proteins, biological validation, or researcher-utility gains.
