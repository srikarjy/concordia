# Concordia

A diagnostic image classification harness built on
[ConceptCLIP](https://huggingface.co) that doesn't just predict — it shows
its work three independent ways, measures whether those three ways agree,
and tracks whether "confident" predictions are actually more often correct.

Status: early scaffolding. See [docs/ROADMAP.md](docs/ROADMAP.md) for the
build plan and [ABOUT.md](ABOUT.md) for the motivation.

## What it does (target state)

Given a medical image, Concordia produces:

- **A prediction** — top concept(s) with scores, via ConceptCLIP.
- **An intrinsic explanation** — the model's own region-concept alignment
  heatmap for the top candidates.
- **Two independent cross-checks** — LIME and SHAP, which know nothing
  about "concepts" and only observe how the score moves as the image is
  perturbed.
- **A concordance score** — how much the three explanations agree on
  *where* the evidence is. Agreement is a trust signal; disagreement gets
  surfaced, not hidden.
- **A confidence tier** — high/medium/low, derived from score margins,
  validated against actual accuracy by the evaluation harness rather than
  asserted.

## Why

Most "explainable" medical-imaging demos show one heatmap and stop there.
One method agreeing with itself isn't evidence of anything. Concordia's
premise is that agreement *across independent explanation methods* is a
much stronger and more honest trust signal — and that any confidence
claim is worthless until it's been checked against ground truth. The
[evaluation harness](docs/ROADMAP.md#phase-3-in-detail--evaluation-harness)
exists specifically to make that check, not to be a demo feature.

## Project layout

```
src/concordia/
  engine.py           inference + intrinsic region-concept heatmaps
  explain.py           structured explanation trace + confidence policy
  posthoc_explain.py    LIME / SHAP cross-validation
  memory.py             case history (SQLite)
  eval/                  evaluation harness (accuracy, calibration, concordance)
  api/                   REST/MCP serving layer
k8s/                     deployment manifests
docs/                    roadmap and design notes
```

## Status

Nothing here is trained, tuned, or benchmarked yet — this repo currently
holds the scaffold and the plan. Build order and definition-of-done for
each phase live in [docs/ROADMAP.md](docs/ROADMAP.md).

## License

TBD.
