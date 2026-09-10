"""Bounded, provenance-preserving CELLxGENE Discover ingestion."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Literal, Protocol
from urllib.parse import urlsplit

import httpx
from pydantic import BaseModel, ConfigDict, Field, model_validator

from concordia.storage.content import ContentAddressedStore

SHA256_PATTERN = r"^[0-9a-f]{64}$"
UUID_PATTERN = r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"


class CellxgeneDatasetSource(BaseModel):
    """Immutable source selection made before a State output exists."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[1] = 1
    collection_id: str = Field(pattern=UUID_PATTERN)
    collection_version_id: str = Field(pattern=UUID_PATTERN)
    dataset_id: str = Field(pattern=UUID_PATTERN)
    dataset_version_id: str = Field(pattern=UUID_PATTERN)
    collection_url: str
    asset_url: str
    asset_byte_size: int = Field(ge=1)
    asset_sha256: str = Field(pattern=SHA256_PATTERN)
    expected_cell_count: int = Field(ge=1)
    expected_gene_count: int = Field(ge=1)
    expected_gene_order_digest: str = Field(pattern=SHA256_PATTERN)
    expected_obs_schema_digest: str = Field(pattern=SHA256_PATTERN)
    perturbation_key: str = Field(min_length=1)
    cell_context_key: str = Field(min_length=1)
    required_perturbations: tuple[str, ...] = Field(min_length=2)
    census_version: str = Field(min_length=1)
    retrieved_at: str = Field(min_length=1)
    publication_doi: str = Field(min_length=1)
    max_download_bytes: int = Field(default=50_000_000, ge=1)
    scientific_use_allowed: Literal[True] = True
    limitations: tuple[str, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_urls_and_budget(self) -> CellxgeneDatasetSource:
        expected_collection = (
            f"https://cellxgene.cziscience.com/collections/{self.collection_id}"
        )
        if self.collection_url != expected_collection:
            raise ValueError("CELLxGENE collection URL does not match its identifier")
        asset = urlsplit(self.asset_url)
        if (
            asset.scheme != "https"
            or asset.hostname != "datasets.cellxgene.cziscience.com"
            or asset.username is not None
            or asset.password is not None
            or asset.query
            or asset.fragment
            or asset.path != f"/{self.dataset_version_id}.h5ad"
        ):
            raise ValueError("CELLxGENE asset URL is outside the approved dataset host")
        if self.asset_byte_size > self.max_download_bytes:
            raise ValueError("CELLxGENE asset exceeds the declared download budget")
        if len(set(self.required_perturbations)) != len(self.required_perturbations):
            raise ValueError("required perturbation labels must be unique")
        return self

    @property
    def metadata_url(self) -> str:
        return (
            "https://api.cellxgene.cziscience.com/curation/v1/collections/"
            f"{self.collection_id}"
        )


class H5adSummary(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    cell_count: int = Field(ge=1)
    gene_count: int = Field(ge=1)
    gene_order_digest: str = Field(pattern=SHA256_PATTERN)
    obs_schema_digest: str = Field(pattern=SHA256_PATTERN)
    perturbation_counts: dict[str, int]
    cell_context_values: tuple[str, ...]
    h5ad_schema_version: str
    title: str


class H5adInspector(Protocol):
    def inspect(
        self,
        path: Path,
        *,
        perturbation_key: str,
        cell_context_key: str,
    ) -> H5adSummary: ...


class AnndataH5adInspector:
    """Read-only AnnData inspection kept behind an optional dependency."""

    def inspect(
        self,
        path: Path,
        *,
        perturbation_key: str,
        cell_context_key: str,
    ) -> H5adSummary:
        try:
            import anndata as ad
        except ImportError as error:
            raise RuntimeError(
                "install the virtual-cell optional dependency before H5AD ingestion"
            ) from error
        adata = ad.read_h5ad(path, backed="r")
        try:
            missing = {
                perturbation_key,
                cell_context_key,
            } - set(adata.obs.columns)
            if missing:
                raise ValueError(f"H5AD is missing required observation columns: {sorted(missing)}")
            genes = [str(value) for value in adata.var_names]
            if len(set(genes)) != len(genes):
                raise ValueError("H5AD var_names must be unique for State input")
            obs_columns = sorted(str(value) for value in adata.obs.columns)
            perturbation_counts = {
                str(label): int(count)
                for label, count in adata.obs[perturbation_key]
                .astype(str)
                .value_counts()
                .sort_index()
                .items()
            }
            contexts = tuple(
                sorted(str(value) for value in adata.obs[cell_context_key].astype(str).unique())
            )
            return H5adSummary(
                cell_count=int(adata.n_obs),
                gene_count=int(adata.n_vars),
                gene_order_digest=_canonical_digest(genes),
                obs_schema_digest=_canonical_digest(obs_columns),
                perturbation_counts=perturbation_counts,
                cell_context_values=contexts,
                h5ad_schema_version=str(adata.uns.get("schema_version") or "unknown"),
                title=str(adata.uns.get("title") or "untitled"),
            )
        finally:
            adata.file.close()


class CellxgeneIngestionResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[1] = 1
    request_artifact_digest: str = Field(pattern=SHA256_PATTERN)
    metadata_artifact_digest: str = Field(pattern=SHA256_PATTERN)
    adata_artifact_digest: str = Field(pattern=SHA256_PATTERN)
    collection_id: str = Field(pattern=UUID_PATTERN)
    collection_version_id: str = Field(pattern=UUID_PATTERN)
    dataset_id: str = Field(pattern=UUID_PATTERN)
    dataset_version_id: str = Field(pattern=UUID_PATTERN)
    byte_size: int = Field(ge=1)
    summary: H5adSummary
    execution_mode: Literal["real"] = "real"
    scientific_use_allowed: Literal[True] = True
    limitations: tuple[str, ...] = Field(min_length=1)


class CellxgeneDiscoverIngestor:
    """Fetch only a predeclared H5AD whose metadata, size, and digest all match."""

    def __init__(
        self,
        artifacts: ContentAddressedStore,
        inspector: H5adInspector,
        *,
        transport: httpx.BaseTransport | None = None,
        timeout_seconds: float = 120.0,
    ):
        self.artifacts = artifacts
        self.inspector = inspector
        self.transport = transport
        self.timeout_seconds = timeout_seconds

    def ingest(self, source: CellxgeneDatasetSource) -> CellxgeneIngestionResult:
        request_digest = self.artifacts.put_json(source.model_dump(mode="json"))
        with httpx.Client(
            follow_redirects=True,
            timeout=self.timeout_seconds,
            transport=self.transport,
        ) as client:
            metadata_response = client.get(source.metadata_url)
            metadata_response.raise_for_status()
            if str(metadata_response.url) != source.metadata_url:
                raise RuntimeError("CELLxGENE metadata redirected outside the frozen URL")
            if len(metadata_response.content) > 10_000_000:
                raise RuntimeError("CELLxGENE metadata response exceeded the configured limit")
            metadata_digest = self.artifacts.put_bytes(metadata_response.content)
            metadata = metadata_response.json()
            self._validate_metadata(source, metadata)
            with client.stream("GET", source.asset_url) as asset_response:
                asset_response.raise_for_status()
                if str(asset_response.url) != source.asset_url:
                    raise RuntimeError("CELLxGENE asset redirected outside the frozen URL")
                declared_length = asset_response.headers.get("content-length")
                if declared_length is not None and int(declared_length) != source.asset_byte_size:
                    raise RuntimeError("CELLxGENE asset Content-Length changed")
                chunks: list[bytes] = []
                byte_size = 0
                for chunk in asset_response.iter_bytes():
                    byte_size += len(chunk)
                    if byte_size > source.max_download_bytes:
                        raise RuntimeError("CELLxGENE download exceeded the configured limit")
                    chunks.append(chunk)
        payload = b"".join(chunks)
        if len(payload) != source.asset_byte_size:
            raise RuntimeError("CELLxGENE asset byte size changed")
        if hashlib.sha256(payload).hexdigest() != source.asset_sha256:
            raise RuntimeError("CELLxGENE asset SHA-256 changed")
        adata_digest = self.artifacts.put_bytes(payload)
        summary = self.inspector.inspect(
            self.artifacts.path_for(adata_digest),
            perturbation_key=source.perturbation_key,
            cell_context_key=source.cell_context_key,
        )
        self._validate_summary(source, summary)
        return CellxgeneIngestionResult(
            request_artifact_digest=request_digest,
            metadata_artifact_digest=metadata_digest,
            adata_artifact_digest=adata_digest,
            collection_id=source.collection_id,
            collection_version_id=source.collection_version_id,
            dataset_id=source.dataset_id,
            dataset_version_id=source.dataset_version_id,
            byte_size=len(payload),
            summary=summary,
            limitations=source.limitations,
        )

    @staticmethod
    def _validate_metadata(
        source: CellxgeneDatasetSource, metadata: Mapping[str, Any]
    ) -> None:
        if metadata.get("collection_id") != source.collection_id:
            raise RuntimeError("CELLxGENE collection identity changed")
        if metadata.get("collection_version_id") != source.collection_version_id:
            raise RuntimeError("CELLxGENE collection version changed")
        datasets = metadata.get("datasets")
        if not isinstance(datasets, list):
            raise RuntimeError("CELLxGENE metadata has no dataset list")
        dataset = next(
            (
                item
                for item in datasets
                if isinstance(item, Mapping) and item.get("dataset_id") == source.dataset_id
            ),
            None,
        )
        if dataset is None or dataset.get("dataset_version_id") != source.dataset_version_id:
            raise RuntimeError("CELLxGENE dataset version changed")
        assets = dataset.get("assets")
        if not isinstance(assets, list):
            raise RuntimeError("CELLxGENE dataset has no asset list")
        matching = [
            item
            for item in assets
            if isinstance(item, Mapping)
            and item.get("filetype") == "H5AD"
            and item.get("url") == source.asset_url
        ]
        if len(matching) != 1 or matching[0].get("filesize") != source.asset_byte_size:
            raise RuntimeError("CELLxGENE H5AD asset metadata changed")

    @staticmethod
    def _validate_summary(source: CellxgeneDatasetSource, summary: H5adSummary) -> None:
        if summary.cell_count != source.expected_cell_count:
            raise RuntimeError("CELLxGENE H5AD cell count changed")
        if summary.gene_count != source.expected_gene_count:
            raise RuntimeError("CELLxGENE H5AD gene count changed")
        if summary.gene_order_digest != source.expected_gene_order_digest:
            raise RuntimeError("CELLxGENE H5AD gene order changed")
        if summary.obs_schema_digest != source.expected_obs_schema_digest:
            raise RuntimeError("CELLxGENE H5AD observation schema changed")
        missing = set(source.required_perturbations) - set(summary.perturbation_counts)
        if missing:
            raise RuntimeError(f"CELLxGENE H5AD lacks perturbations: {sorted(missing)}")


def _canonical_digest(values: list[str]) -> str:
    payload = json.dumps(values, sort_keys=False, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
