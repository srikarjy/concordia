"""Render the saved sample without making any additional model calls."""

# ruff: noqa: E501 -- embedded HTML and JavaScript templates

import html
import json
import shutil
from pathlib import Path


def main() -> None:
    source = Path(".concordia/sample-crambin")
    destination = Path("frontend/dist/sample-crambin")
    destination.mkdir(parents=True, exist_ok=True)
    report = json.loads((source / "report.json").read_text())
    result = json.loads((source / "boltz-result.json").read_text())["result"]
    structure = result["structure_text"]
    assert "_atom_site." in structure and result["structure_format"].lower() == "mmcif"
    for name in (
        "report.json",
        "prediction.cif",
        "trained-model.json",
        "dataset.json",
        "experiment-manifest.json",
        "reference.fasta",
    ):
        shutil.copyfile(source / name, destination / name)
    shutil.copyfile("frontend/node_modules/3dmol/build/3Dmol-min.js", destination / "3Dmol.js")
    (destination / "viewer.js").write_text("""
fetch('./prediction.cif').then(r => r.text()).then(text => {
  const viewer = $3Dmol.createViewer(document.getElementById('viewer'), {backgroundColor:'#102027'});
  const model = viewer.addModel(text, 'cif');
  viewer.setStyle({}, {cartoon:{color:'spectrum'}, stick:{radius:0.12}});
  viewer.zoomTo(); viewer.render();
  document.getElementById('viewer-status').textContent = 'Rendered ' + model.selectedAtoms({}).length + ' atoms. Drag to rotate.';
  window.addEventListener('resize', () => viewer.resize());
}).catch(error => { document.getElementById('viewer-status').textContent = error.message; });
""")
    confidence = result["confidence_scores"][0]
    summary = html.escape(json.dumps(report, indent=2))
    (destination / "index.html").write_text(f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><title>Concordia — completed crambin sample</title>
<style>body{{font:17px system-ui;background:#102027;color:#e6f2ed;margin:35px auto;max-width:1100px;padding:20px}}
h1{{font-size:32px}}a{{color:#88e7c0}}#viewer{{height:480px;position:relative;border:1px solid #76b59e}}
.warning{{background:#493522;padding:18px;border-radius:8px}}pre{{white-space:pre-wrap;font-size:13px}}
.steps{{padding:18px;background:#173e34;border-radius:8px}}</style></head><body>
<h1>Crambin: synthetic plumbing demo — not a biological recommendation</h1>
<p class="steps">10 synthetic training examples → CPU ridge fit → rank 3 candidates → NVIDIA Boltz-2 → saved structure and lineage</p>
<p class="warning">Low confidence: {confidence:.3f}. Selected Cys16→Ala variant. Synthetic hydrophobic-fraction labels are not experimental fitness measurements. This result does not support a claim of improved protein function.</p>
<p>Training split: 8 training / 2 test. Saved experiment: {html.escape(report["experiment_id"])}.</p>
<div id="viewer"></div><p id="viewer-status">Loading structure…</p>
<p><a href="prediction.cif" download>Download structure</a> · <a href="report.json">Report JSON</a> ·
<a href="trained-model.json">Trained baseline</a> · <a href="experiment-manifest.json">Experiment lineage</a> ·
<a href="https://www.rcsb.org/structure/1CRN">Reference protein: PDB 1CRN</a> · <a href="/">Workspace</a></p>
<details><summary>Full run report</summary><pre>{summary}</pre></details>
<script src="./3Dmol.js"></script><script src="./viewer.js"></script></body></html>""")
    print("http://127.0.0.1:7861/sample-crambin/index.html")


if __name__ == "__main__":
    main()
