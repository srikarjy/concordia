"""Start the compiled workspace with the existing authenticated HF worker."""

import argparse
import getpass
import os
from pathlib import Path

import uvicorn
from huggingface_hub import get_token

from concordia.api.workspace import create_workspace_app


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--configure-nvidia", action="store_true")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    key_path = root / ".concordia" / "nvidia-api-key"
    if args.configure_nvidia:
        key = getpass.getpass("NVIDIA API key (hidden): ").strip()
        if not key:
            raise SystemExit("No key supplied; configuration unchanged.")
        key_path.parent.mkdir(parents=True, exist_ok=True)
        descriptor = os.open(key_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(descriptor, "w") as handle:
            os.fchmod(handle.fileno(), 0o600)
            handle.write(key)
        print("Key saved locally. Restart this launcher to enable NVIDIA inference.")
        return
    if not os.environ.get("NVIDIA_API_KEY") and key_path.is_file():
        os.environ["NVIDIA_API_KEY"] = key_path.read_text().strip()
    os.environ["OLLAMA_NO_CLOUD"] = "1"
    frontend = root / "frontend" / "dist"
    if not (frontend / "index.html").exists():
        raise SystemExit("Build the UI first: cd frontend && npm run build")
    os.environ.setdefault(
        "CONCORDIA_EVO2_FORWARD_SPACE_URL",
        "https://srikarjy025-concordia-evo2-forward.hf.space",
    )
    token = get_token()
    if token:
        os.environ.setdefault("CONCORDIA_EVO2_FORWARD_HF_TOKEN", token)
    app = create_workspace_app(root / ".concordia" / "workspace", frontend)
    uvicorn.run(app, host="127.0.0.1", port=7861)


if __name__ == "__main__":
    main()
