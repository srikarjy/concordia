"""Hosted binder-design integrations use mocked transports, never real model calls."""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from concordia.genomics.proteinmpnn_nvidia import (
    NvidiaHostedProteinMpnnRunner,
    ProteinMpnnRequest,
    parse_mfasta,
)
from concordia.genomics.rfdiffusion_nvidia import (
    NvidiaHostedRFdiffusionRunner,
    RFdiffusionRequest,
)
from concordia.storage.content import ContentAddressedStore

STRUCTURE_STUB = "ATOM      1  N   MET A   1      12.501   2.331 -26.921  1.00 47.72      N\n"
TARGET_PDB = STRUCTURE_STUB * 3


def _rfdiffusion(tmp_path: Path, handler) -> NvidiaHostedRFdiffusionRunner:
    return NvidiaHostedRFdiffusionRunner(
        ContentAddressedStore(tmp_path / "artifacts"),
        api_key="test-secret",
        transport=httpx.MockTransport(handler),
    )


def _proteinmpnn(tmp_path: Path, handler) -> NvidiaHostedProteinMpnnRunner:
    return NvidiaHostedProteinMpnnRunner(
        ContentAddressedStore(tmp_path / "artifacts"),
        api_key="test-secret",
        transport=httpx.MockTransport(handler),
    )


def test_rfdiffusion_sends_the_documented_body_and_keeps_bounded_provenance(tmp_path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        assert body["contigs"] == "A20-60/0 50-100"
        assert body["hotspot_res"] == ["A50", "A51"]
        assert body["diffusion_steps"] == 25
        assert body["random_seed"] == 7
        return httpx.Response(200, json={"output_pdb": STRUCTURE_STUB, "elapsed_ms": 1200})

    runner = _rfdiffusion(tmp_path, handler)
    result = runner.generate(
        RFdiffusionRequest(
            target_pdb=TARGET_PDB,
            contigs="A20-60/0 50-100",
            hotspot_residues=("A50", "A51"),
            diffusion_steps=25,
            random_seed=7,
        )
    )

    assert result.pdb_text == STRUCTURE_STUB
    assert result.execution_mode == "real_hosted_backbone_generation"
    assert result.scientific_use_allowed is False
    retained = json.loads(runner.artifacts.get_bytes(result.request_artifact_digest))
    assert retained["input_retained"] is False
    assert retained["target_pdb_bytes"] == len(TARGET_PDB)
    # The target structure itself is hashed, never stored in the request artifact.
    assert TARGET_PDB not in json.dumps(retained)


def test_rfdiffusion_omits_optional_fields_when_unset(tmp_path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        assert "hotspot_res" not in body and "random_seed" not in body
        assert body["diffusion_steps"] == 50
        return httpx.Response(200, json={"output_pdb": STRUCTURE_STUB})

    runner = _rfdiffusion(tmp_path, handler)
    assert runner.generate(RFdiffusionRequest(target_pdb=TARGET_PDB, contigs="50-100")).pdb_text


@pytest.mark.parametrize(
    "overrides",
    [
        {"contigs": "A20-60; rm -rf /"},
        {"contigs": "A20-60", "hotspot_residues": ("chain A residue 50",)},
        {"contigs": "A20-60", "diffusion_steps": 500},
        {"contigs": ""},
    ],
)
def test_rfdiffusion_rejects_malformed_requests(overrides) -> None:
    with pytest.raises(ValidationError):
        RFdiffusionRequest(target_pdb=TARGET_PDB, **overrides)


def test_rfdiffusion_rejects_a_response_without_coordinates(tmp_path) -> None:
    runner = _rfdiffusion(
        tmp_path, lambda request: httpx.Response(200, json={"output_pdb": "no atoms here"})
    )
    with pytest.raises(RuntimeError, match="no PDB structure"):
        runner.generate(RFdiffusionRequest(target_pdb=TARGET_PDB, contigs="50-100"))


def test_rfdiffusion_upstream_error_detail_is_logged_not_returned(tmp_path, caplog) -> None:
    runner = _rfdiffusion(
        tmp_path, lambda request: httpx.Response(500, text="upstream trace id=abc123")
    )
    with caplog.at_level("WARNING"), pytest.raises(RuntimeError) as raised:
        runner.generate(RFdiffusionRequest(target_pdb=TARGET_PDB, contigs="50-100"))
    assert str(raised.value) == "NVIDIA RFdiffusion HTTP 500"
    assert "abc123" in caplog.text


def test_parse_mfasta_keeps_order_and_joins_wrapped_lines() -> None:
    text = ">native, score=0.5\nAAAA\nCCCC\n\n>design_1, score=1.25\nDDDD\n"
    assert parse_mfasta(text) == (
        ("native, score=0.5", "AAAACCCC"),
        ("design_1, score=1.25", "DDDD"),
    )


def test_proteinmpnn_designs_only_the_requested_chains(tmp_path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        assert body["input_pdb_chains"] == ["B"]
        assert body["num_seq_per_target"] == 2
        assert body["sampling_temp"] == [0.2]
        assert body["use_soluble_model"] is True
        return httpx.Response(
            200,
            json={
                "mfasta": ">input, score=0.10\nMKTA\n>design_1, score=1.50\nEVQL\n",
                "scores": [0.10, 1.50],
                "probs": [[0.1] * 21],
            },
        )

    runner = _proteinmpnn(tmp_path, handler)
    result = runner.design(
        ProteinMpnnRequest(
            input_pdb=TARGET_PDB,
            design_chains=("B",),
            num_sequences=2,
            sampling_temperature=0.2,
            use_soluble_model=True,
        )
    )

    assert [item.sequence for item in result.designed_sequences] == ["MKTA", "EVQL"]
    assert [item.score for item in result.designed_sequences] == [0.10, 1.50]
    # Per-position probabilities stay in the response artifact, not the result.
    assert "probs" not in result.model_dump()
    assert b"probs" in runner.artifacts.get_bytes(result.response_artifact_digest)


def test_proteinmpnn_falls_back_to_the_scores_array_without_header_scores(tmp_path) -> None:
    runner = _proteinmpnn(
        tmp_path,
        lambda request: httpx.Response(
            200, json={"mfasta": ">design_1\nEVQL\n", "scores": [2.5], "probs": []}
        ),
    )
    result = runner.design(ProteinMpnnRequest(input_pdb=TARGET_PDB))
    assert result.designed_sequences[0].score == 2.5


def test_proteinmpnn_keeps_multi_chain_separators(tmp_path) -> None:
    runner = _proteinmpnn(
        tmp_path,
        lambda request: httpx.Response(200, json={"mfasta": ">design_1\nEVQL/MKTA\n"}),
    )
    result = runner.design(ProteinMpnnRequest(input_pdb=TARGET_PDB))
    assert result.designed_sequences[0].sequence == "EVQL/MKTA"


def test_proteinmpnn_rejects_an_empty_or_duplicate_chain_list() -> None:
    with pytest.raises(ValidationError, match="unique"):
        ProteinMpnnRequest(input_pdb=TARGET_PDB, design_chains=("A", "A"))
    with pytest.raises(ValidationError, match="alphanumeric"):
        ProteinMpnnRequest(input_pdb=TARGET_PDB, design_chains=("chain A",))


def test_proteinmpnn_rejects_a_response_without_sequences(tmp_path) -> None:
    runner = _proteinmpnn(tmp_path, lambda request: httpx.Response(200, json={"mfasta": "   "}))
    with pytest.raises(RuntimeError, match="no sequences"):
        runner.design(ProteinMpnnRequest(input_pdb=TARGET_PDB))


def test_both_runners_require_an_api_key(tmp_path) -> None:
    artifacts = ContentAddressedStore(tmp_path / "artifacts")
    with pytest.raises(RuntimeError, match="NVIDIA_API_KEY"):
        NvidiaHostedRFdiffusionRunner(artifacts, api_key="").preflight()
    with pytest.raises(RuntimeError, match="NVIDIA_API_KEY"):
        NvidiaHostedProteinMpnnRunner(artifacts, api_key="").preflight()
