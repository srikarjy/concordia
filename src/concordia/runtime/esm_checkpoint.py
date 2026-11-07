"""Load the approved ESM-2 snapshot without mutable refs or pickle weights."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

ESM2_REPO = "facebook/esm2_t33_650M_UR50D"
ESM2_REVISION = "08e4846e537177426273712802403f7ba8261b6c"
ESM2_SAFETENSORS_SHA256 = "a08adabb949fa67ad3c14b509d04fd60368b35007b0095e3358f81200c4f4db0"
ESM2_FILES = ("config.json", "model.safetensors", "tokenizer_config.json", "vocab.txt")


def verified_esm2_snapshot() -> tuple[Path, dict[str, str]]:
    """Fetch only required files at a commit and verify the large weight file."""
    from huggingface_hub import snapshot_download

    snapshot = Path(
        snapshot_download(
            repo_id=ESM2_REPO, revision=ESM2_REVISION, allow_patterns=list(ESM2_FILES)
        )
    )
    if snapshot.name != ESM2_REVISION:
        raise ValueError("ESM-2 snapshot did not resolve to the approved commit")
    digests: dict[str, str] = {}
    for name in ESM2_FILES:
        path = snapshot / name
        with path.open("rb") as handle:
            digests[name] = hashlib.file_digest(handle, "sha256").hexdigest()
    if digests["model.safetensors"] != ESM2_SAFETENSORS_SHA256:
        raise ValueError("ESM-2 safetensors weights differ from the approved SHA-256")
    return snapshot, digests


def load_esm2(model_class: Any) -> tuple[Any, Any, dict[str, str]]:
    """Construct a Transformers model from verified local snapshot files only."""
    from transformers import AutoTokenizer

    snapshot, digests = verified_esm2_snapshot()
    tokenizer = AutoTokenizer.from_pretrained(snapshot, local_files_only=True)
    model = model_class.from_pretrained(
        snapshot, local_files_only=True, use_safetensors=True
    ).eval()
    return tokenizer, model, digests
