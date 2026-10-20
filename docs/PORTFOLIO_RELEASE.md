# Concordia portfolio release candidate

Date: 2026-10-20. The local release commit is the repository `HEAD` at review
time; the preceding reviewed baseline was
`9b437aad87c9706c3993bdf931a071bb56458fce`. It has not been pushed,
deployed, or checked by remote CI.

## Acceptance decision

Accepted for a limited research-software portfolio demonstration. The shipped
story is a provenance-aware researcher review workflow:

`candidate mutations → recorded evidence → human decision → later assay import → verified export`

The default public path is the static 1IGV replay. It has no account, model
call, or paid-provider requirement. It exposes a separate checksum-verified
ThermoMPNN feasibility record whose terminal status is `unavailable`.

## Result record

| Area | Evidence state | Result |
| --- | --- | --- |
| Candidate review, decisions, assay comparison | Software-tested | Local and static browser workflows passed. |
| Revision-correct exports | Software-tested | Replay revision 1 and revision 7 produce distinct exports. |
| Bundle integrity | Software-tested | The standalone verifier accepts exact bytes and rejects changed input or diagnostic bytes. |
| ThermoMPNN fresh execution | Unavailable | Pinned source checkout and checkpoint were absent locally. No prediction was run. |
| Explanation, gradients, integrated gradients | Not run | No attribution or biological interpretation is displayed. |
| Predictive performance on new proteins | Not evaluated | The 1IGV replay is a saved retrospective example. |
| Biological validation and researcher utility | Not evaluated | No prospective experiment or user study was conducted. |

## Release artifacts

| Artifact | SHA-256 |
| --- | --- |
| `reports/thermompnn-feasibility/2026-10-20-1igv-s1a.json` | `88906a76e3d9eb498a631443784980bd2ed89cacdde84cd979a27a5c5bf4b2d2` |
| `frontend/public/review-replay/r7-bundle.zip` | `3d83a3e60898aa539dd908ded015b244134d9907ea9981cd1d6ba44753920fa4` |
| [`variant-review-replay.png`](screenshots/variant-review-replay.png) | `93a23b84e2340e4b7e575439df3968a3aba26a24b10426bf73b6dfbabd15d07b` |

The r7 bundle contains `diagnostics/thermompnn-feasibility.json` and
`diagnostics.json`. Its verifier checks those diagnostic bytes in addition to
the review history and raw imported inputs.

## Reproduction

```sh
PYTHONPATH=src .venv/bin/python scripts/build_review_replay.py
PYTHONPATH=src .venv/bin/python -m pytest -q
make verify
cd frontend
npm run check
npm run build
npm run build:stability
npm run test:local
npm run test:public
```

For the reviewer walk-through and deliberate corruption check, follow
[portfolio-demo.md](portfolio-demo.md). The screenshot above was captured from
the built static replay after the browser tests.

## Checks executed for this candidate

- `make verify`: passed: frozen-asset availability, Ruff, strict stability
  typing, repository typing, and deployment typing.
- Full Python suite: passed (with two FastAPI/TestClient deprecation warnings).
- Frontend TypeScript check and both production builds: passed.
- Browser suites: 8 workspace, 3 local, and 7 public tests passed.
- Standalone verifier for the r7 static export: passed; a test also confirms a
  changed diagnostic record produces `Diagnostic hash mismatch`.

The frontend build reports existing large Molstar chunks and a third-party
3Dmol `eval` warning. Neither changed the review replay behavior.

## Publication status and remaining external dependency

Do not call this published. Before publication, commit the reviewed tree,
push the authorized revision, verify remote CI, and publish the F1 frozen asset
archive through a tested acquisition location. Public asset hosting and remote
CI remain unverified. No deployment or external publication action has been
taken here.
