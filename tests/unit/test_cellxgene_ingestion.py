from __future__ import annotations

import hashlib
import json
from pathlib import Path

import httpx
import pytest

from concordia.storage.content import ContentAddressedStore
from concordia.virtual_cell.cellxgene import (
    AnndataH5adInspector,
    CellxgeneDatasetSource,
    CellxgeneDiscoverIngestor,
    H5adSummary,
)

COLLECTION_ID = "d5cad3f0-56b6-4fbe-8f2b-be92a8c7820f"
COLLECTION_VERSION = "07a35908-e342-40d0-b03c-65d65ddc3c1a"
DATASET_ID = "6de332e1-465e-4243-9412-6fdc7497e99d"
DATASET_VERSION = "d1acb78a-7d9e-4d4f-8ec3-0db5861aebea"
PAYLOAD = b"bounded h5ad fixture bytes"


class FixtureInspector:
    def inspect(
        self,
        path: Path,
        *,
        perturbation_key: str,
        cell_context_key: str,
    ) -> H5adSummary:
        assert path.read_bytes() == PAYLOAD
        assert perturbation_key == "knockout"
        assert cell_context_key == "cell_type"
        return H5adSummary(
            cell_count=4,
            gene_count=3,
            gene_order_digest="a" * 64,
            obs_schema_digest="b" * 64,
            perturbation_counts={"Control": 2, "SBE1/5": 2},
            cell_context_values=("neural progenitor cell",),
            h5ad_schema_version="fixture-schema",
            title="fixture title",
        )


def source(**updates: object) -> CellxgeneDatasetSource:
    values: dict[str, object] = {
        "collection_id": COLLECTION_ID,
        "collection_version_id": COLLECTION_VERSION,
        "dataset_id": DATASET_ID,
        "dataset_version_id": DATASET_VERSION,
        "collection_url": f"https://cellxgene.cziscience.com/collections/{COLLECTION_ID}",
        "asset_url": f"https://datasets.cellxgene.cziscience.com/{DATASET_VERSION}.h5ad",
        "asset_byte_size": len(PAYLOAD),
        "asset_sha256": hashlib.sha256(PAYLOAD).hexdigest(),
        "expected_cell_count": 4,
        "expected_gene_count": 3,
        "expected_gene_order_digest": "a" * 64,
        "expected_obs_schema_digest": "b" * 64,
        "perturbation_key": "knockout",
        "cell_context_key": "cell_type",
        "required_perturbations": ["Control", "SBE1/5"],
        "census_version": "2025-11-08",
        "retrieved_at": "2026-09-10",
        "publication_doi": "10.1101/example",
        "max_download_bytes": 1_000,
        "limitations": ["fixture metadata for an ingestion contract test"],
    }
    values.update(updates)
    return CellxgeneDatasetSource.model_validate(values)


def metadata() -> dict[str, object]:
    return {
        "collection_id": COLLECTION_ID,
        "collection_version_id": COLLECTION_VERSION,
        "datasets": [
            {
                "dataset_id": DATASET_ID,
                "dataset_version_id": DATASET_VERSION,
                "assets": [
                    {
                        "filetype": "H5AD",
                        "filesize": len(PAYLOAD),
                        "url": (
                            "https://datasets.cellxgene.cziscience.com/"
                            f"{DATASET_VERSION}.h5ad"
                        ),
                    }
                ],
            }
        ],
    }


def test_cellxgene_ingestion_persists_exact_metadata_and_h5ad(tmp_path: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "api.cellxgene.cziscience.com":
            return httpx.Response(200, json=metadata())
        return httpx.Response(200, content=PAYLOAD)

    store = ContentAddressedStore(tmp_path / "artifacts")
    result = CellxgeneDiscoverIngestor(
        store,
        FixtureInspector(),
        transport=httpx.MockTransport(handler),
    ).ingest(source())

    assert store.get_bytes(result.adata_artifact_digest) == PAYLOAD
    assert json.loads(store.get_bytes(result.metadata_artifact_digest)) == metadata()
    assert result.summary.perturbation_counts == {"Control": 2, "SBE1/5": 2}
    assert result.scientific_use_allowed


def test_cellxgene_ingestion_rejects_changed_asset_and_unsafe_url(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="approved dataset host"):
        source(asset_url="https://example.org/input.h5ad")

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "api.cellxgene.cziscience.com":
            return httpx.Response(200, json=metadata())
        return httpx.Response(200, content=b"changed")

    with pytest.raises(RuntimeError, match="Content-Length changed"):
        CellxgeneDiscoverIngestor(
            ContentAddressedStore(tmp_path / "artifacts"),
            FixtureInspector(),
            transport=httpx.MockTransport(handler),
        ).ingest(source())


def test_cellxgene_source_rejects_asset_over_budget() -> None:
    with pytest.raises(ValueError, match="download budget"):
        source(max_download_bytes=len(PAYLOAD) - 1)


def test_cellxgene_ingestion_rejects_redirected_asset(tmp_path: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "api.cellxgene.cziscience.com":
            return httpx.Response(200, json=metadata())
        if request.url.host == "unapproved.example":
            return httpx.Response(200, content=PAYLOAD)
        return httpx.Response(
            302,
            headers={"location": "https://unapproved.example/input.h5ad"},
        )

    with pytest.raises(RuntimeError, match="redirected outside"):
        CellxgeneDiscoverIngestor(
            ContentAddressedStore(tmp_path / "artifacts"),
            FixtureInspector(),
            transport=httpx.MockTransport(handler),
        ).ingest(source())


def test_anndata_inspector_preserves_gene_order_and_perturbation_counts(
    tmp_path: Path,
) -> None:
    ad = pytest.importorskip("anndata")
    np = pytest.importorskip("numpy")
    pd = pytest.importorskip("pandas")
    path = tmp_path / "small.h5ad"
    adata = ad.AnnData(
        X=np.asarray([[1, 0, 2], [0, 3, 1]], dtype=np.float32),
        obs=pd.DataFrame(
            {
                "knockout": ["Control", "SBE1/5"],
                "cell_type": ["progenitor", "progenitor"],
            },
            index=["cell-1", "cell-2"],
        ),
        var=pd.DataFrame(index=["gene-2", "gene-1", "gene-3"]),
    )
    adata.uns["schema_version"] = "test-v1"
    adata.uns["title"] = "small fixture"
    adata.write_h5ad(path)

    summary = AnndataH5adInspector().inspect(
        path, perturbation_key="knockout", cell_context_key="cell_type"
    )

    assert summary.cell_count == 2
    assert summary.gene_count == 3
    assert summary.perturbation_counts == {"Control": 1, "SBE1/5": 1}
    assert summary.cell_context_values == ("progenitor",)
    assert summary.gene_order_digest == hashlib.sha256(
        b'["gene-2","gene-1","gene-3"]'
    ).hexdigest()
