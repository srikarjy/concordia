"""Small CPU gateway: existing ThermoMPNN HTTP path plus existing Boltz runner."""

import json
import os
from pathlib import Path

from concordia.genomics.boltz_gateway import BoltzGateway
from concordia.genomics.boltz_nvidia import NvidiaHostedBoltzRunner
from concordia.runtime.structure_workflow import create_structure_workflow_app
from concordia.storage.content import ContentAddressedStore

root = Path(os.environ.get("CONCORDIA_STATE_ROOT", "/app/state"))
domain = json.loads(Path("domain.json").read_text())
runner = NvidiaHostedBoltzRunner(ContentAddressedStore(root / "provider-artifacts"))
runner.max_poll_attempts = 12
runner.poll_seconds_header = 30
gateway = BoltzGateway(
    runner,
    database_path=root / "quota.sqlite3",
    per_client_limit=3,
    global_daily_limit=3,
)
app = create_structure_workflow_app(
    state_root=root,
    sequence=domain["sequence"],
    manifest_digest=domain["manifest_digest"],
    access_token_sha256=os.environ.get("CONCORDIA_STRUCTURE_TOKEN_SHA256", ""),
    gateway=gateway,
    scoring_url="https://srikarjy025-concordia-thermompnn.hf.space/score",
)
