"""Command-line entry point for reproducible Concordia stages."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from concordia.artifacts import sha256_file
from concordia.config import load_baseline_config
from concordia.evidence.build import build_packets
from concordia.explanations.tree_shap import generate_tree_shap, validate_tree_shap
from concordia.predictors.baseline import train_baseline
from concordia.predictors.data import download_file
from concordia.reporting.demo import write_demo_report


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


if __name__ == "__main__":
    main()
