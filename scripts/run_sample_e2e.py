"""Small synthetic-training + live NVIDIA folding workflow through the local API."""

import dataclasses
import json
from pathlib import Path

import httpx

from concordia.campaigns.training import (
    ProteinTrainingExample,
    freeze_protein_dataset,
    sequence_features,
    train_protein_baseline,
)


def main() -> None:
    output = Path(".concordia/sample-crambin")
    output.mkdir(parents=True, exist_ok=True)
    with httpx.Client(timeout=600) as client:
        source = client.get("https://www.rcsb.org/fasta/entry/1CRN/display")
        source.raise_for_status()
        native = "".join(line for line in source.text.splitlines() if not line.startswith(">"))
        assert len(native) == 46
        (output / "reference.fasta").write_text(source.text)
        # Toy objective, NOT an experimental assay or a biological design objective.
        variants = [native] + [
            native[:i] + aa + native[i + 1 :]
            for i, aa in [
                (0, "A"),
                (1, "V"),
                (5, "A"),
                (6, "L"),
                (8, "V"),
                (9, "K"),
                (10, "A"),
                (11, "L"),
                (12, "A"),
            ]
        ]
        examples = tuple(
            ProteinTrainingExample(
                candidate_id=f"sample-{i}",
                sequence=s,
                value=sum(aa in "AVILMFWY" for aa in s) / len(s),
            )
            for i, s in enumerate(variants)
        )
        dataset = freeze_protein_dataset("crambin-synthetic-composition-demo", examples, seed=17)
        model = train_protein_baseline(dataset)
        (output / "dataset.json").write_text(json.dumps(dataclasses.asdict(dataset), indent=2))
        (output / "trained-model.json").write_text(json.dumps(dataclasses.asdict(model), indent=2))
        # Candidate scoring is separate from the held-out training metric.
        candidates = [native, native[:15] + "A" + native[16:], native[:16] + "V" + native[17:]]
        scores = [
            model.intercept
            + sum(w * x for w, x in zip(model.coefficients, sequence_features(s), strict=True))
            for s in candidates
        ]
        selected_index = max(range(len(scores)), key=scores.__getitem__)
        selected = candidates[selected_index]
        base = "http://127.0.0.1:7861"

        def api(method: str, path: str, payload=None):
            response = client.request(method, base + path, json=payload)
            response.raise_for_status()
            return response.json()

        created = api(
            "POST",
            "/experiments",
            {
                "title": "Crambin: synthetic baseline to live NVIDIA structure",
                "description": "Synthetic labels, not measured fitness. Source PDB 1CRN.",
            },
        )
        eid = created["experiment"]["experiment_id"]
        private = output / "access.json"
        private.touch(mode=0o600, exist_ok=True)
        private.chmod(0o600)
        private.write_text(json.dumps(created))
        client.headers["X-Concordia-Experiment-Token"] = created["access_token"]
        root = api(
            "POST",
            f"/experiments/{eid}/nodes",
            {
                "kind": "protein_sequence",
                "operation": "root",
                "label": "Crambin 1CRN reference",
                "payload": {"payload_type": "protein", "sequence": native},
            },
        )
        training = api(
            "POST",
            f"/experiments/{eid}/nodes",
            {
                "kind": "model_run",
                "operation": "import",
                "label": "CPU ridge training: synthetic labels",
                "parent_ids": [root["node_id"]],
                "payload": {
                    "payload_type": "model_run",
                    "model": model.model_id,
                    "model_version": "1",
                    "execution_mode": "local_training_synthetic_labels",
                    "parameters": {
                        "dataset_digest": dataset.dataset_digest,
                        "model_digest": model.artifact_digest,
                        "metrics": model.metrics,
                        "labels": "synthetic hydrophobic fraction",
                    },
                },
            },
        )
        chosen = api(
            "POST",
            f"/experiments/{eid}/nodes",
            {
                "kind": "protein_sequence",
                "operation": "design_sequence",
                "label": "Synthetic plumbing demo candidate — not a biological recommendation",
                "parent_ids": [root["node_id"], training["node_id"]],
                "payload": {
                    "payload_type": "protein",
                    "sequence": selected,
                    "provenance": "synthetic_hydrophobic_fraction_demo",
                    "scientific_use_allowed": False,
                },
            },
        )
        api("POST", f"/experiments/{eid}/candidates/{chosen['node_id']}")
        report = {
            "sample": "crambin 1CRN",
            "source": "https://www.rcsb.org/structure/1CRN",
            "experiment_id": eid,
            "training_labels": "synthetic hydrophobic fraction, not measured",
            "training_metrics": model.metrics,
            "candidate_scores": scores,
            "selected_candidate_index": selected_index,
            "selected_sequence": selected,
            "scientific_use_allowed": False,
            "candidate_provenance": "synthetic_hydrophobic_fraction_demo",
        }
        print(json.dumps({"stage": "training_and_selection_complete", **report}), flush=True)
        try:
            folded = api(
                "POST",
                f"/experiments/{eid}/operations/boltz/predict",
                {
                    "parent_node_id": chosen["node_id"],
                    "sequence": selected,
                },
            )
            result = folded["result"]
            (output / "boltz-result.json").write_text(json.dumps(folded, indent=2))
            (output / "prediction.cif").write_text(result["structure_text"])
            report["folding"] = {
                k: result[k]
                for k in (
                    "model_id",
                    "execution_mode",
                    "confidence_scores",
                    "elapsed_seconds",
                    "request_artifact_digest",
                    "response_artifact_digest",
                    "limitations",
                )
            }
            report["status"] = "COMPLETED"
        except httpx.HTTPStatusError as error:
            report["status"] = "FAILED_FOLDING"
            report["error"] = {
                "http_status": error.response.status_code,
                "detail": error.response.text[:1000],
            }
        manifest = api("GET", f"/experiments/{eid}")
        (output / "experiment-manifest.json").write_text(json.dumps(manifest, indent=2))
        report["node_count"] = len(manifest["nodes"])
        report["edge_count"] = len(manifest["edges"])
        (output / "report.json").write_text(json.dumps(report, indent=2))
        print(json.dumps(report, indent=2), flush=True)


if __name__ == "__main__":
    main()
