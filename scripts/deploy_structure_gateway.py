"""Deploy the allowlisted gateway package; credentials are Space secrets only."""

from __future__ import annotations

import argparse
import hashlib
import os
import secrets
from pathlib import Path

from huggingface_hub import HfApi
from package_structure_gateway import package

from concordia.runtime.secrets import nvidia_api_key

ROOT = Path(__file__).resolve().parents[1]
SPACE = "srikarjy025/concordia-structure-gateway"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("staging", type=Path, help="New, empty package directory")
    parser.add_argument(
        "--configure-secrets",
        action="store_true",
        help="Requires explicit approval to store credentials in this Space",
    )
    args = parser.parse_args()
    package(args.staging)
    key = nvidia_api_key(ROOT)
    if args.configure_secrets and not key:
        raise SystemExit("NVIDIA credential is missing; deployment stopped")
    token_path = ROOT / ".concordia/structure-access-token"
    if args.configure_secrets and not token_path.exists():
        fd = os.open(token_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w") as handle:
            handle.write(secrets.token_urlsafe(32))
    if token_path.exists() and token_path.stat().st_mode & 0o777 != 0o600:
        raise SystemExit("Owner access-token file must have mode 0600")
    token = token_path.read_text().strip() if token_path.exists() else None
    for path in args.staging.rglob("*"):
        if path.is_file():
            data = path.read_bytes()
            if (key and key.encode() in data) or (token and token.encode() in data):
                raise SystemExit("Secret in upload set; deployment stopped")
    api = HfApi()
    api.create_repo(SPACE, repo_type="space", space_sdk="docker", private=False, exist_ok=True)
    if args.configure_secrets:
        assert key and token
        api.add_space_secret(SPACE, key="NVIDIA_API_KEY", value=key)
        api.add_space_secret(
            SPACE,
            key="CONCORDIA_STRUCTURE_TOKEN_SHA256",
            value=hashlib.sha256(token.encode()).hexdigest(),
        )
    commit = api.upload_folder(
        repo_id=SPACE,
        repo_type="space",
        folder_path=args.staging,
        commit_message="Connect authenticated inspection to shared ThermoMPNN and Boltz paths",
    )
    print(f"Space: {SPACE}; revision: {commit.oid}; secrets configured: {args.configure_secrets}")


if __name__ == "__main__":
    main()
