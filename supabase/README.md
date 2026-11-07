# Supabase model gateways

`structure-gateway` is the owner-authenticated boundary for structure inspection
of accepted 1IGV mutations. `protein-workbench` serves private protein uploads to
any account with a verified email. Supabase assigns each account, analysis and
prediction a UUID; database reads and writes are scoped to the authenticated
user. Browser roles cannot read the tables or decrypted Vault secrets.

The protein workbench allows 20 saved sequences per account, 30 authenticated
requests per minute, two prediction attempts per UTC day per account, one active
prediction per account, and two concurrent predictions globally. A configurable
global daily call limit is enforced atomically in Postgres. Hosted NVIDIA
prediction stays disabled unless production-service permission and credit limits
are confirmed. Private sequence uploads and history remain available while that
gate is off.

Apply migrations before deploying functions. Configure these non-secret values
for `structure-gateway`:

- `CONCORDIA_OWNER_USER_ID`
- `CONCORDIA_OWNER_EMAIL` (or use the owner user ID)
- `CONCORDIA_MANIFEST_DIGEST`
- `CONCORDIA_1IGV_SEQUENCE`
- `THERMOMPNN_URL`

`protein-workbench` accepts verified-email accounts and has no owner allowlist.
Its prediction gate defaults closed. Enable `CONCORDIA_PUBLIC_NVIDIA_APPROVED`
and set `CONCORDIA_PUBLIC_DAILY_LIMIT` only after public hosted-service
permission and an affordable credit ceiling are confirmed.

The service-role key is a Supabase function secret. The NVIDIA key remains in
Vault under `NVIDIA_API_KEY`; it is not copied into either function or the
frontend.
