# Static stability deployment security

The public deploy is `frontend/dist-stability/`, not the interactive workspace.
It contains one precomputed JSON report and the bundled 1IGV PDB. It has no
backend routes, model weights, credentials, or connector clients.

## Backend route disposition

The existing FastAPI workspace remains a development/service surface and is not
published by this deployment.

| Route family | Disposition | Reason |
| --- | --- | --- |
| `GET /health`, `/ready`, `/api/workspace`, `/api/artifacts*`, `/api/graph`, `/api/events`, `/api/report`, `/api/frameworks` | safe read-only service routes | Fixture/evidence reads only; not shipped in the static bundle |
| `GET /api/capabilities`, `/api/models`, `/api/connectors/health` | authenticated service-only | Configuration and live connector status are internal operational data; not shipped |
| `/experiments*`, `/campaigns*`, `/runs*`, `/colony/run` | requires scoped auth or do not deploy publicly | Mutating workflow, model jobs, replay and campaign state |
| `/nvidia/*`, `/experiments/*/operations/*` | do not deploy publicly | These can spend hosted quota or submit user data to a provider |
| `/v1/structure-claims/*` | do not deploy publicly | Interactive structure operations are outside the static demo |

The static page makes no network request to an API, NVIDIA, Ollama, localhost,
or a filesystem path. Connector health responses use the operational shape
`configured`, `state`, `reachable_at`, and `last_success`; public static output
does not expose that service response or internal endpoint URLs.

## Secret checks

`NVIDIA_API_KEY` is primary and `.concordia/nvidia-api-key` is a local fallback
requiring mode `0600`. The build scans the committed static payload and bundle
for key-shaped values, API key names, provider endpoints, loopback endpoints,
and local paths. The only generic `localhost` text in the current Mol* bundle
is a dependency's Darwin file-URL error message, not a configured endpoint or
request target.
