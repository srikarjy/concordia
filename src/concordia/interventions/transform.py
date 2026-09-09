"""Deterministic evidence interventions with auditable manifests."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from concordia.evidence.packets import _top_attributions
from concordia.evidence.schema import EvidencePacket


@dataclass(frozen=True)
class InterventionResult:
    packet: EvidencePacket
    intervention_id: str
    parent_hash: str
    donor_hash: str | None = None


def withhold(packet: EvidencePacket) -> InterventionResult:
    transformed = packet.model_copy(
        update={"packet_id": f"{packet.molecule_id}:withheld", "explanation": None}
    )
    return InterventionResult(transformed, "explanation_withheld:v1", packet.content_hash())


def shuffle(packet: EvidencePacket, donor: EvidencePacket) -> InterventionResult:
    if packet.molecule_id == donor.molecule_id:
        raise ValueError("Shuffled explanation donor must differ from recipient")
    if donor.explanation is None:
        raise ValueError("Shuffled donor must contain an explanation")
    transformed = packet.model_copy(
        update={"packet_id": f"{packet.molecule_id}:shuffled", "explanation": donor.explanation}
    )
    return InterventionResult(
        transformed,
        "explanation_shuffled:v1",
        packet.content_hash(),
        donor.content_hash(),
    )


def corrupt_sign(
    packet: EvidencePacket, seed: int, fraction: float = 0.1
) -> InterventionResult:
    if packet.explanation is None:
        raise ValueError("Cannot corrupt a withheld explanation")
    if not 0 < fraction <= 1:
        raise ValueError("fraction must be in (0, 1]")
    values = np.asarray(packet.explanation.attributions, dtype=float)
    count = max(1, int(np.ceil(len(values) * fraction)))
    indices = np.random.default_rng(seed).choice(len(values), size=count, replace=False)
    values[indices] *= -1
    top_positive, top_negative = _top_attributions(values)
    explanation = packet.explanation.model_copy(
        update={
            "attributions": tuple(float(value) for value in values),
            "top_positive": top_positive,
            "top_negative": top_negative,
        }
    )
    transformed = packet.model_copy(
        update={
            "packet_id": f"{packet.molecule_id}:corrupted-sign",
            "explanation": explanation,
        }
    )
    return InterventionResult(
        transformed,
        f"explanation_corrupted_sign:v1:seed={seed}",
        packet.content_hash(),
    )
