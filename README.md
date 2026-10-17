---
title: Concordia Colony Scientific Workspace
emoji: 🧬
colorFrom: green
colorTo: blue
sdk: docker
app_port: 7860
---

# Concordia

Concordia is an audit layer for AI-generated biology. It records what a model
was asked to do, which input and model version it used, and what evidence
supports the result.

## The problem

Biology models can produce confident-looking structures, sequences, and
recommendations that are difficult to reproduce or verify. A high confidence
score is not proof that a result is correct. Without a clear record of the
inputs, settings, model revision, and independent checks, it is easy to trust a
wrong answer or lose the path that produced it.

## What Concordia solves

Concordia turns each model run into a traceable result:

- inputs and outputs are stored as content-addressed artifacts;
- model names, revisions, settings, and provenance are recorded;
- runs are linked through an append-only event ledger;
- deterministic rules check claims against available evidence;
- refusals are first-class results, with the reason and evidence shown;
- results can be replayed instead of reconstructed from notebooks or chat logs.

The system is designed to say **unverifiable** when the evidence is not strong
enough. It does not turn model confidence into a biological claim.

## Current demonstrations

The repository contains two related workflows:

1. **Structure-claim verification** for hosted structure predictions such as
   Boltz-2. The verifier checks geometry, model agreement, and counterfactuals
   without pretending that one model's confidence is independent evidence.
2. **Measured protein-stability analysis** for the frozen 1IGV dataset. It
   applies protected-residue and out-of-distribution refusals, ranks candidates
   with the recorded ranker, and exposes the prediction, interval, evidence,
   and refusal decision together.

The stability demonstration is deliberately narrow: one domain, one property,
and in-silico results only. It does not claim that a mutation will fold, be
stable in a cell, express, bind, or function. Its intervals are too wide to be
used as an acquisition signal.

## Run the project

```bash
make demo      # offline demonstration
make serve     # local workspace at http://127.0.0.1:7860
make test      # tests and verification checks
```

Run the measured-stability workflow without Ollama or hosted design calls:

```bash
PYTHONPATH=src .venv/bin/python scripts/run_typed_stability_demo.py \
  --domain 1IGV --mutations A13Q,Q21E,A13Q:K6Q,L52Y \
  --state-root .concordia/typed-demo
```

The output includes ranked candidates, evidenced refusals, the ranker,
provenance digests, and a verified ledger chain.

Build the read-only static stability page:

```bash
make build-stability-static
```

The page reads committed results and a bundled structure. It performs no model
inference and makes no network calls.

## Scientific boundary

Concordia is software for provenance, verification, and reproducibility. Its
model outputs are computational hypotheses, not validated biological findings
or therapeutic advice. Designed proteins have not been shown here to fold,
express, bind, or function experimentally.

## Links

[Technical overview](docs/technical-overview.md) ·
[Usage and security guide](docs/guide.md) ·
[Static deployment security](docs/STATIC_DEPLOY_SECURITY.md)

## License

MIT. See [LICENSE](LICENSE) and [CITATION.cff](CITATION.cff).
