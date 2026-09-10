from __future__ import annotations

import hashlib

import pytest
from pydantic import ValidationError

from concordia.genomes.mutation import MutationEngine
from concordia.genomes.schema import (
    MutationOperator,
    create_seed_genome,
)


def seed_genome():
    return create_seed_genome(hashlib.sha256(b"prompt-v3").hexdigest())


@pytest.mark.parametrize("operator", list(MutationOperator))
def test_mutations_are_deterministic_and_auditable(operator) -> None:
    engine = MutationEngine()
    first = engine.mutate(seed_genome(), operator, 41)
    second = engine.mutate(seed_genome(), operator, 41)
    assert first == second
    child, record = first
    assert record.parent_genome_id == seed_genome().genome_id
    assert record.operator is operator
    assert record.seed == 41
    assert record.old_value != record.new_value
    assert record.validation_result == "VALID"
    assert child is not None
    assert child.genome_id == record.child_genome_id
    assert child.parent_genome_id == seed_genome().genome_id


def test_invalid_genome_identity_is_rejected() -> None:
    value = seed_genome().model_dump(mode="json")
    value["genome_id"] = "0" * 64
    with pytest.raises(ValidationError, match="canonical genome content"):
        type(seed_genome()).model_validate(value)


def test_invalid_mutation_is_preserved() -> None:
    engine = MutationEngine()
    parent, _ = engine.mutate(
        seed_genome(), MutationOperator.REMOVE_OPTIONAL_VERIFICATION_STEP, 1
    )
    assert parent is not None
    child, record = engine.mutate(
        parent, MutationOperator.REMOVE_OPTIONAL_VERIFICATION_STEP, 2
    )
    assert child is None
    assert record.validation_result == "INVALID"
    assert record.validation_error
