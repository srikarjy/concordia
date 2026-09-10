# Read-only tool integration

The public Concordia workspace publishes a curated OpenAPI contract for
evidence inspection. It is suitable for OpenAPI-compatible assistants,
notebooks, workflow engines, and bioinformatics clients:

```text
https://srikarjy025-concordia-colony.hf.space/api/tools/openapi.json
```

The discovery record is available at
`/.well-known/concordia-tools.json` and `/api/tools`. Clients can inspect the
saved workspace, list and read immutable artifacts, slice the evidence graph,
page through saved events, and download the saved report.

This surface is intentionally narrower than the local control plane. It exposes
only six `GET` operations. It does not expose run creation or cancellation,
CellForge execution, State or Evo2 inference, arbitrary sequences, filesystem
paths, hosted-model credentials, or the ZeroGPU worker. Every returned
scientific object remains fixture-labeled and `scientific_use_allowed=false`.

ChatGPT GPT Actions and other clients that support imported OpenAPI tools can
use the public schema URL directly. In the GPT editor, create an Action, choose
`None` for authentication, and import the schema URL. The privacy-policy URL for
a public GPT is
`https://srikarjy025-concordia-colony.hf.space/privacy`. No API key is required
for this read-only demonstration. The client must retain Concordia's fixture and
uncertainty labels in any answer; it must not describe the saved demonstration
as a biological finding.

For local development, start the workspace and import the equivalent schema:

```bash
.venv/bin/concordia serve-workspace
```

```text
http://127.0.0.1:7860/api/tools/openapi.json
```

The mutable run API remains a separate loopback-only application. A future
write-capable tool gateway would require authentication, per-user quotas,
request persistence, and a new security review before deployment.
