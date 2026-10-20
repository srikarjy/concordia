"""Exercise the combined HTTP handler with real HF and NVIDIA calls, locally.

Secrets are read locally and the NVIDIA credential is sent only to NVIDIA.
Existing cached results are reused by the gateway; failures are never retried.
"""

from __future__ import annotations

import hashlib
import json
import secrets
from pathlib import Path

import httpx
from fastapi.testclient import TestClient

from concordia.genomics.boltz_gateway import BoltzGateway
from concordia.genomics.boltz_nvidia import NvidiaHostedBoltzRunner
from concordia.runtime.secrets import nvidia_api_key
from concordia.runtime.structure_workflow import create_structure_workflow_app
from concordia.storage.content import ContentAddressedStore

ROOT = Path(__file__).resolve().parents[1]
STATE = ROOT / ".concordia/structure-workflow-live"


class RecordedTransport(httpx.HTTPTransport):
    def __init__(self) -> None:
        super().__init__()
        self.statuses: list[int] = []

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        response = super().handle_request(request)
        self.statuses.append(response.status_code)
        return response


def main() -> None:
    domain = json.loads((ROOT / ".concordia/structure-gateway-upload-v1/domain.json").read_text())
    token = secrets.token_urlsafe(32)
    key = nvidia_api_key(ROOT)
    if not key:
        raise SystemExit("NVIDIA credential missing")
    transport = RecordedTransport()
    runner = NvidiaHostedBoltzRunner(
        ContentAddressedStore(STATE / "provider"),
        api_key=key,
        transport=transport,
    )
    runner.poll_seconds_header = 30
    runner.max_poll_attempts = 12
    gateway = BoltzGateway(runner, database_path=STATE / "quota.sqlite3", global_daily_limit=3)
    app = create_structure_workflow_app(
        state_root=STATE,
        sequence=domain["sequence"],
        manifest_digest=domain["manifest_digest"],
        access_token_sha256=hashlib.sha256(token.encode()).hexdigest(),
        gateway=gateway,
        scoring_url="https://srikarjy025-concordia-thermompnn.hf.space/score",
    )
    with TestClient(app) as client:
        response = client.post(
            "/structure",
            headers={"authorization": f"Bearer {token}"},
            json={
                "domain": "1IGV",
                "mutations": ["A13Q", "K6Q", "L52Y", "Q21E", "A13Q:K6Q"],
                "selected_mutation": "K6Q",
            },
        )
    if key in response.text or token in response.text:
        raise SystemExit("Secret detected in response; output withheld")
    data = response.json()
    output = STATE / "result.json"
    output.write_text(json.dumps(data, indent=2))
    print(
        json.dumps(
            {
                "handler_http_status": response.status_code,
                "status": data.get("status"),
                "new_nvidia_http_statuses": transport.statuses,
                "ranked": len(data.get("stability", {}).get("candidates", [])),
                "refused": len(data.get("stability", {}).get("refusals", [])),
                "artifact_digest": data.get("artifact_digest"),
                "ledger_intact": data.get("ledger_intact"),
                "structure_characters": len(
                    (data.get("structure") or {}).get("structure_text", "")
                ),
                "provider_seconds": (data.get("structure") or {}).get("elapsed_seconds"),
                "saved": str(output.relative_to(ROOT)),
            }
        )
    )


if __name__ == "__main__":
    main()
