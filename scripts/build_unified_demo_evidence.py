#!/usr/bin/env python3
"""Regenerate docs/unified-standalone.html's embedded evidence/ledger/stability
data from one live, reproducible run.

Without this script the three <script type="application/json"> blocks in that
page were hand-transcribed from whichever run happened to be on screen at the
time, with no way to notice if they drifted apart or from what the documented
commands actually produce. Rerun this after any change that could affect the
Evo2/ThermoMPNN/Boltz replay reports or the measured-stability ranker.

Run: .venv/bin/python -m scripts.build_unified_demo_evidence
"""

from __future__ import annotations

import json
import re
import shutil
from pathlib import Path

from concordia.events.sqlite import SQLiteEventLedger
from concordia.stability.measured import MeasuredStabilityEngine
from concordia.stability.request import TypedStabilityRequest, run_typed_request
from scripts.replay_boltz_3hfm_evidence import replay as replay_boltz
from scripts.replay_evo2_generation_evidence import replay as replay_evo2
from scripts.replay_thermompnn_feasibility import replay as replay_thermompnn

HTML_PATH = Path("docs/unified-standalone.html")
STATE_ROOT = Path(".concordia/unified-demo-evidence")
# Matches the README quickstart's documented example exactly, so the page
# always shows the same candidate set a reader can reproduce themselves.
STABILITY_MUTATIONS = "A13Q,Q21E,A13Q:K6Q,L52Y"


def _compact(data: object) -> str:
    return json.dumps(data, separators=(",", ":")).replace("</", "<\\/")


def _replace_block(html: str, block_id: str, payload: str) -> str:
    pattern = re.compile(
        rf'(<script type="application/json" id="{block_id}">)(.*?)(</script>)', re.S
    )
    new_html, count = pattern.subn(lambda m: m.group(1) + payload + m.group(3), html)
    if count != 1:
        raise RuntimeError(f"expected exactly one {block_id!r} block, found {count}")
    return new_html


def main() -> None:
    if STATE_ROOT.exists():
        shutil.rmtree(STATE_ROOT)
    STATE_ROOT.mkdir(parents=True)

    boltz = replay_boltz(STATE_ROOT)
    evo2 = replay_evo2(STATE_ROOT)
    thermompnn = replay_thermompnn(STATE_ROOT)
    stability_report = run_typed_request(
        TypedStabilityRequest.from_cli("1IGV", STABILITY_MUTATIONS),
        state_root=STATE_ROOT,
        engine=MeasuredStabilityEngine(),
    )

    ledger = SQLiteEventLedger(STATE_ROOT / "events.sqlite3")
    stability_run_id = stability_report["run_id"]
    stability_evidence = next(
        event.payload
        for event in ledger.events(stability_run_id).items
        if event.event_type == "MODEL_RUN_EVIDENCE"
    )

    evidence = [
        boltz.model_dump(mode="json"),
        evo2.model_dump(mode="json"),
        thermompnn.model_dump(mode="json"),
        stability_evidence,
    ]

    chain = ledger.verify_chain()
    ledger_data = {
        "runs_checked": chain.runs_checked,
        "events_checked": chain.events_checked,
        "heads": chain.heads,
        "breaks": [b.model_dump(mode="json") for b in chain.breaks],
        "intact": chain.intact,
    }

    stability_data = {
        "ranked_candidates": [
            {
                "variant_id": item["candidate"]["variant_id"],
                "ddg": item["mean_prediction_ddg_kcal_higher_is_more_stable"],
                "interval_low": item["interval_90_kcal_mol"]["lower"],
                "interval_high": item["interval_90_kcal_mol"]["upper"],
                "rank": item["rank"],
            }
            for item in stability_report["candidates"]
        ],
        "refusals": [
            {"variant_id": item["variant_id"], "triggers": list(item["triggers"])}
            for item in stability_report["refusals"]
        ],
    }

    html = HTML_PATH.read_text(encoding="utf-8")
    html = _replace_block(html, "evidence-data", _compact(evidence))
    html = _replace_block(html, "ledger-data", _compact(ledger_data))
    html = _replace_block(html, "stability-data", _compact(stability_data))
    HTML_PATH.write_text(html, encoding="utf-8")
    print(f"Regenerated {HTML_PATH} from a live run (state root: {STATE_ROOT}).")


if __name__ == "__main__":
    main()
