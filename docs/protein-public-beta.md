# Public protein uploads and prediction gate

Verified email users can save a private, single-record FASTA or pasted protein
(20–300 standard residues, input <=8 KB). Supabase generates a user UUID and
an analysis UUID. Identical sequences reuse the user's existing analysis.
The application permits twenty uploads per account and thirty authenticated
requests per minute. Tables deny direct browser access; each gateway lookup is
scoped to the verified user. Uploaded proteins never enter 1IGV stability scoring.

Prediction reservations serialize in Postgres. Limits: two attempts per UTC day
per user, one active job per user, two globally, and a configured global daily
limit. Successful result reuse does not consume quota. The unique analysis/model/
settings key prevents duplicate submissions. Failed jobs are retained and are not
automatically retried. A crashed running job remains blocked for operator review;
it is not released into a potentially duplicate provider call.

## Launch blocker, verified 2026-10-18

NVIDIA API Trial Terms sections 1.2 and 1.4 restrict trial use to internal testing
and evaluation, excluding production. Section 4.2 restricts making the API service
available to others. Model licensing alone does not authorize public hosted use.
Source: https://assets.ngc.nvidia.com/products/api-catalog/legal/NVIDIA%20API%20Trial%20Terms%20of%20Service.pdf

Therefore public predictions default OFF. Uploads require no NVIDIA access.
Only after production-service permission and credits are verified may an operator
set CONCORDIA_PUBLIC_NVIDIA_APPROVED=true and CONCORDIA_PUBLIC_DAILY_LIMIT to a
positive integer <=200. No balance has been verified in this pass. The approved
ceiling must also respect available credits. Browser parameters cannot enable it.

Predictions send query-only alignments, never claim an evolutionary search, use
explicit user consent, and time out at 90 seconds. HTTP 202 is recorded as an
unsupported asynchronous response without resubmission. Longer jobs require a
provider submit/poll adapter before public release. Stored results contain request
settings, input and response digests, model name and latency; no verified ledger
chain is claimed. This is not yet a complete replay store of raw provider responses.

## Verification

`node --test supabase/tests/protein-contract.test.mjs`

`npm test --prefix frontend -- --config=playwright.public.config.ts`

Apply migrations before deploying `protein-workbench`. Auth must allow the custom
domain as a redirect. Tests using fixture sessions are software tests, not evidence
of successful email delivery or live NVIDIA inference.
