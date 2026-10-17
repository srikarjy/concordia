"""Typed artifact references for campaign structures, assays, and checkpoints."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any, Literal, Protocol

from concordia.storage.content import ContentAddressedStore

ArtifactKind = Literal["structure", "assay", "checkpoint", "report"]


@dataclass(frozen=True)
class CampaignArtifact:
    digest: str
    kind: ArtifactKind
    media_type: str
    size_bytes: int
    storage_key: str


class CampaignArtifactStore:
    """Content-addressed artifact store with a campaign-safe type boundary."""

    def __init__(self, store: ContentAddressedStore):
        self.store = store

    def put(self, payload: bytes, *, kind: ArtifactKind, media_type: str) -> CampaignArtifact:
        if not payload:
            raise ValueError("artifact payload cannot be empty")
        if not media_type or "/" not in media_type:
            raise ValueError("media_type must be a valid type/subtype")
        digest = self.store.put_bytes(payload)
        return CampaignArtifact(
            digest=digest,
            kind=kind,
            media_type=media_type,
            size_bytes=len(payload),
            storage_key=f"campaign-artifacts/{kind}/sha256/{digest}",
        )

    def get(self, artifact: CampaignArtifact) -> bytes:
        payload = self.store.get_bytes(artifact.digest)
        if len(payload) != artifact.size_bytes:
            raise ValueError("artifact size does not match its recorded reference")
        return payload


class ObjectStorageClient(Protocol):
    def put_object(self, *, bucket: str, key: str, body: bytes, content_type: str) -> Any: ...

    def get_object(self, *, bucket: str, key: str) -> bytes: ...


class ObjectStorageArtifactStore:
    """S3-compatible adapter; the client is injected to keep credentials external."""

    def __init__(self, client: ObjectStorageClient, *, bucket: str, prefix: str = "concordia"):
        if not bucket or not prefix:
            raise ValueError("bucket and prefix are required")
        self.client = client
        self.bucket = bucket
        self.prefix = prefix.strip("/")

    def put(self, payload: bytes, *, kind: ArtifactKind, media_type: str) -> CampaignArtifact:
        if not payload:
            raise ValueError("artifact payload cannot be empty")
        if not media_type or "/" not in media_type:
            raise ValueError("media_type must be a valid type/subtype")
        digest = hashlib.sha256(payload).hexdigest()
        key = f"{self.prefix}/campaign-artifacts/{kind}/sha256/{digest}"
        self.client.put_object(
            bucket=self.bucket,
            key=key,
            body=payload,
            content_type=media_type,
        )
        return CampaignArtifact(
            digest=digest,
            kind=kind,
            media_type=media_type,
            size_bytes=len(payload),
            storage_key=key,
        )

    def get(self, artifact: CampaignArtifact) -> bytes:
        payload = self.client.get_object(bucket=self.bucket, key=artifact.storage_key)
        if len(payload) != artifact.size_bytes:
            raise ValueError("object storage artifact size does not match its reference")
        if hashlib.sha256(payload).hexdigest() != artifact.digest:
            raise ValueError("object storage artifact digest does not match its reference")
        return payload


__all__ = [
    "ArtifactKind",
    "CampaignArtifact",
    "CampaignArtifactStore",
    "ObjectStorageArtifactStore",
    "ObjectStorageClient",
]
