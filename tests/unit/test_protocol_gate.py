import hashlib

import pytest

from concordia.genomics.evo2 import SequenceScore
from concordia.genomics.evo2_real import RealEvo2Scorer
from concordia.genomics.schema import GenomicSequence
from concordia.scientific.protocol import ProtocolGate, StudyProtocol, StudyStatus


def protocol() -> StudyProtocol:
    return StudyProtocol(
        protocol_id="regulatory-variant-v1",
        dataset_id="declared-dataset-pending-license",
        dataset_license="license-to-be-recorded-before-freeze",
        inclusion_criteria=("single-nucleotide regulatory variants",),
        exclusion_criteria=("ambiguous reference alleles",),
        model_checkpoint="evo2-checkpoint-pending",
        scoring_target="declared_variant_likelihood_delta",
        assembly="GRCh38",
        window_size=8192,
        evidence_families=("counterfactual", "biological_annotation"),
        hypothesis="attribution regions may agree with controlled perturbations",
        uncertainty_method="repeated windows and independent runs",
    )


def test_protocol_must_be_frozen_before_admission() -> None:
    draft = protocol()
    frozen = ProtocolGate.freeze(draft)
    assert frozen.status is StudyStatus.FROZEN
    with pytest.raises(ValueError, match="frozen"):
        ProtocolGate.admit_artifact(
            draft, execution_mode="real", scientific_use_allowed=True
        )
    with pytest.raises(ValueError, match="fixture"):
        ProtocolGate.admit_artifact(
            frozen, execution_mode="recorded_fixture", scientific_use_allowed=False
        )


class Runner:
    def __init__(self, mode: str = "real", sequence_hash: str | None = None):
        self.mode = mode
        self.sequence_hash = sequence_hash

    def score(self, sequence: GenomicSequence, *, checkpoint: str, target: str):
        return SequenceScore(
            model_id=checkpoint,
            execution_mode=self.mode,
            sequence_hash=self.sequence_hash or sequence.content_hash(),
            score=0.2,
            target=target,
            scientific_use_allowed=self.mode == "real",
        ).model_dump(mode="json")


def test_real_evo2_adapter_requires_matching_eligible_output() -> None:
    sequence = GenomicSequence(
        sequence_id="chr1:0-4", sequence="ACGT", assembly="GRCh38", region="chr1:0-4", strand="+"
    )
    scorer = RealEvo2Scorer(Runner(), checkpoint="evo2-7b", target="likelihood_delta")
    assert scorer.score(sequence).execution_mode == "real"
    with pytest.raises(ValueError, match="refuses fixture"):
        RealEvo2Scorer(
            Runner("recorded_fixture"), checkpoint="evo2-7b", target="likelihood_delta"
        ).score(sequence)
    with pytest.raises(ValueError, match="sequence hash"):
        RealEvo2Scorer(
            Runner("real", hashlib.sha256(b"wrong").hexdigest()),
            checkpoint="evo2-7b",
            target="likelihood_delta",
        ).score(sequence)
