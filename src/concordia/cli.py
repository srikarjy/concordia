"""Command-line entry point for reproducible Concordia stages."""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

from concordia.artifacts import sha256_file
from concordia.config import load_baseline_config
from concordia.evidence.build import build_packets
from concordia.explanations.tree_shap import generate_tree_shap, validate_tree_shap
from concordia.genomics.demo import run_genomic_fixture_demo
from concordia.predictors.baseline import train_baseline
from concordia.predictors.data import download_file
from concordia.reporting.demo import write_demo_report
from concordia.scientist.doctor import check_local_runtime


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="concordia")
    subparsers = parser.add_subparsers(dest="command", required=True)

    download = subparsers.add_parser("download", help="download configured source data")
    download.add_argument("--config", type=Path, default=Path("configs/baseline_nr_ahr.yaml"))

    train = subparsers.add_parser("train-baseline", help="train the configured baseline")
    train.add_argument("--config", type=Path, default=Path("configs/baseline_nr_ahr.yaml"))
    explain = subparsers.add_parser("explain", help="generate TreeSHAP artifacts")
    explain.add_argument("--model", type=Path, required=True)
    explain.add_argument("--molecules", type=Path, required=True)
    explain.add_argument("--output", type=Path, required=True)
    explain.add_argument("--background-size", type=int, default=128)
    explain.add_argument("--limit", type=int)
    validate = subparsers.add_parser("validate-explanations", help="validate TreeSHAP artifacts")
    validate.add_argument("--manifest", type=Path, required=True)
    packets = subparsers.add_parser("build-packets", help="build frozen evidence packets")
    packets.add_argument("--molecules", type=Path, required=True)
    packets.add_argument("--shap-values", type=Path, required=True)
    packets.add_argument("--output", type=Path, required=True)
    packets.add_argument("--limit", type=int)
    demo = subparsers.add_parser("demo", help="write an illustrative report without model access")
    demo.add_argument("--output", type=Path, default=Path("reports/demo.html"))
    doctor = subparsers.add_parser("doctor", help="check local scientist runtime prerequisites")
    doctor.add_argument("--config", type=Path, default=Path("configs/scientist_local.yaml"))
    genomic_demo = subparsers.add_parser(
        "genomic-demo", help="run the software-only genomic evidence vertical slice"
    )
    genomic_demo.add_argument(
        "--output", type=Path, default=Path("artifacts/genomic_fixture_demo")
    )
    api = subparsers.add_parser("serve-api", help="serve the local durable run API")
    api.add_argument("--state-root", type=Path, default=Path(".concordia"))
    api.add_argument("--port", type=int, default=8000)
    worker = subparsers.add_parser("run-worker", help="run the durable local worker")
    worker.add_argument("--state-root", type=Path, default=Path(".concordia"))
    worker.add_argument("--owner")
    worker.add_argument("--once", action="store_true")
    ingest = subparsers.add_parser(
        "ingest-project", help="build a provenance graph from supported project files"
    )
    ingest.add_argument("--root", type=Path, default=Path("."))
    ingest.add_argument(
        "--state-root", type=Path, default=Path(".concordia/ingestion")
    )
    return parser


def main() -> None:
    args = build_parser().parse_args()
    if args.command == "download":
        config = load_baseline_config(args.config)
        if config.dataset.raw_path.exists():
            digest = sha256_file(config.dataset.raw_path)
            if config.dataset.checksum_sha256 and digest != config.dataset.checksum_sha256:
                raise SystemExit("Existing dataset checksum does not match configuration")
        else:
            digest = download_file(
                config.dataset.url,
                config.dataset.raw_path,
                config.dataset.checksum_sha256,
            )
        print(json.dumps({"path": str(config.dataset.raw_path), "sha256": digest}, indent=2))
    elif args.command == "train-baseline":
        config = load_baseline_config(args.config)
        if not config.dataset.raw_path.exists():
            raise SystemExit("Dataset is missing; run `concordia download` first")
        print(json.dumps(train_baseline(config), indent=2))
    elif args.command == "explain":
        print(
            json.dumps(
                generate_tree_shap(
                    args.model,
                    args.molecules,
                    args.output,
                    background_size=args.background_size,
                    limit=args.limit,
                ),
                indent=2,
            )
        )
    elif args.command == "build-packets":
        print(
            json.dumps(
                build_packets(
                    args.molecules,
                    args.shap_values,
                    args.output,
                    limit=args.limit,
                ),
                indent=2,
            )
        )
    elif args.command == "validate-explanations":
        print(json.dumps(validate_tree_shap(args.manifest), indent=2))
    elif args.command == "demo":
        print(json.dumps({"report": str(write_demo_report(args.output))}, indent=2))
    elif args.command == "doctor":
        print(json.dumps(check_local_runtime(args.config), indent=2))
    elif args.command == "genomic-demo":
        print(json.dumps(run_genomic_fixture_demo(args.output), indent=2))
    elif args.command == "serve-api":
        import uvicorn

        from concordia.api.app import create_app

        uvicorn.run(create_app(args.state_root), host="127.0.0.1", port=args.port)
    elif args.command == "run-worker":
        from concordia.runtime.service import RunService
        from concordia.runtime.worker import LocalWorker

        worker = LocalWorker.create(RunService.local(args.state_root), owner=args.owner)
        if args.once:
            record = worker.run_once()
            print(
                json.dumps(
                    record.model_dump(mode="json") if record is not None else {"status": "idle"},
                    indent=2,
                )
            )
        else:
            try:
                while True:
                    if worker.run_once() is None:
                        time.sleep(1)
            except KeyboardInterrupt:
                pass
    elif args.command == "ingest-project":
        from concordia.ingestion.service import ProjectIngestor

        result = ProjectIngestor(args.root, args.state_root).ingest_repository()
        print(
            json.dumps(
                {
                    "schema_version": result.schema_version,
                    "graph_artifact_digest": result.graph_artifact_digest,
                    "file_count": result.file_count,
                    "accepted_entity_count": result.accepted_entity_count,
                    "rejected_entity_count": result.rejected_entity_count,
                },
                indent=2,
            )
        )


if __name__ == "__main__":
    main()
