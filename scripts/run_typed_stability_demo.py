"""Reproducible no-language-model request-to-result demonstration."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from concordia.stability.request import TypedStabilityRequest, run_typed_request


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--domain", default="1IGV")
    parser.add_argument(
        "--mutations",
        default="A13Q,Q21E,A13Q:K6Q,L52Y",
        help="comma-separated candidates; ':' groups simultaneous mutations",
    )
    parser.add_argument("--state-root", type=Path, default=Path(".concordia/typed-demo"))
    args = parser.parse_args()
    request = TypedStabilityRequest.from_cli(args.domain, args.mutations)
    result = run_typed_request(request, state_root=args.state_root)
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
