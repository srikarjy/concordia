"""Generate a no-model local demo report."""

from __future__ import annotations

from pathlib import Path


def write_demo_report(output: str | Path) -> Path:
    """Write an explanatory report using no dataset, model, or network access."""
    target = Path(output)
    target.parent.mkdir(parents=True, exist_ok=True)
    html = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Concordia local workflow demo</title>
  <style>
    body { color: #17202a; font: 16px/1.55 system-ui, sans-serif;
           margin: 0 auto; max-width: 900px; padding: 2rem; }
    code, pre { background: #f2f4f4; border-radius: 4px; padding: .15rem .3rem; }
    pre { overflow-x: auto; padding: 1rem; }
    .notice { background: #fff3cd; border-left: 4px solid #d39e00; padding: 1rem; }
    table { border-collapse: collapse; width: 100%; }
    th, td { border-bottom: 1px solid #d5d8dc; padding: .6rem; text-align: left; }
  </style>
</head>
<body>
  <h1>Concordia local workflow demo</h1>
  <div class="notice"><strong>Illustrative only.</strong> This report contains no model
  response and no experimental finding. It demonstrates the artifact flow that users
  can inspect before downloading data or model weights.</div>
  <h2>Single scientist design</h2>
  <pre>frozen evidence packet
  → one scientist model call
  → validated structured claims
  → deterministic comparison</pre>
  <h2>Conditions</h2>
  <table>
    <tr><th>Condition</th><th>Packet change</th></tr>
    <tr><td>Control</td><td>Prediction plus matching explanation</td></tr>
    <tr><td>Explanation withheld</td><td>Same prediction; explanation absent</td></tr>
    <tr><td>Explanation shuffled</td><td>Same prediction; donor explanation supplied</td></tr>
  </table>
  <h2>What a real run records</h2>
  <ul>
    <li>Dataset and molecule identifiers</li>
    <li>Predictor and TreeSHAP artifact hashes</li>
    <li>Content-hashed packet and intervention manifests</li>
    <li>Exact local runtime, model, prompt, and generation settings</li>
    <li>Raw responses, validation outcomes, and derived metrics</li>
  </ul>
  <p>Run the full pipeline only after reviewing the experiment design and
  reproducibility contract in the repository documentation.</p>
</body>
</html>
"""
    temporary = target.with_suffix(target.suffix + ".tmp")
    temporary.write_text(html, encoding="utf-8")
    temporary.replace(target)
    return target
