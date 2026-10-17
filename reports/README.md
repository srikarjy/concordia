# Reports

Reports are generated from saved manifests and derived metrics. The demo command
creates an illustrative, no-model HTML workflow report; it contains no scientific
findings. Final study reports must identify their input run manifest, code revision,
model identity, and analysis version.

Small committed qualification records may document external integration or hardware
capability checks. Each such record must state whether inference ran and whether the
result is eligible for scientific use. Hardware probes and hosted sequence generation
are not forward scores or biological evidence.

## Benchmark reports

Run `concordia benchmark` to produce a versioned JSON report containing local
throughput, exact replay correctness, labeled verifier performance, and an
optional real Boltz-2 latency suite. The default Boltz suite is reported as
`NOT_RUN`; use `concordia benchmark --suite boltz --real` only when
`NVIDIA_API_KEY` is configured and hosted inference cost is approved.

Benchmark metrics describe software behavior or service latency. They do not
establish structure quality, binding affinity, biological validity, or clinical
utility.
## Structure baseline control

`structure-null-baseline-benchmark.json` is a reproducible retrospective
control generated from the held-out antibody verifier report:

```bash
PYTHONPATH=src python scripts/benchmark_structure_null.py \
  reports/verifier-on-boltz-benchmark.json \
  --output reports/structure-null-baseline-benchmark.json
```

It uses only geometry measurements, records the source digest, and ignores
DockQ/reference fields during prediction. Its report is permanently marked
`scientific_use_allowed=false` and `prospective_claim_allowed=false`.
