import pytest

from concordia.scientific import (
    CrossModelComparisonSpec,
    CrossModelObservation,
    Evo2SAEFeatureEvidence,
)


def test_sae_feature_requires_exact_layer_checkpoint_and_non_fixture_evidence() -> None:
    feature = Evo2SAEFeatureEvidence(
        model_checkpoint="arc/evo2-7b-forward",
        model_output_layer="decoder.layers.20.mlp.linear_fc2",
        sae_checkpoint="declared-sae-v1",
        sae_checkpoint_digest="a" * 64,
        sequence_digest="b" * 64,
        feature_id=42,
        positions=(10, 12),
        activations=(1.5, 2.0),
        activation_threshold=1,
        execution_mode="recorded_real",
        scientific_use_allowed=True,
    )
    assert feature.positions == (10, 12)
    with pytest.raises(ValueError, match="fixture SAE"):
        Evo2SAEFeatureEvidence.model_validate(
            feature.model_dump(
                mode="json",
                exclude={"execution_mode", "scientific_use_allowed"},
            )
            | {"execution_mode": "fixture", "scientific_use_allowed": True}
        )


def test_cross_model_contract_requires_distinct_training_and_exact_effect() -> None:
    spec = CrossModelComparisonSpec(
        comparison_id="pilot-comparison-v1",
        primary_checkpoint="evo2-7b",
        comparator_checkpoint="independent-sequence-model-v1",
        assembly="GRCh38",
        primary_target="variant_effect",
        comparator_target="equivalent_variant_effect",
        target_equivalence_rationale=(
            "Both targets compare alternate and reference sequence scores."
        ),
        training_independence_evidence=(
            "The comparator must document a separately trained model and corpus."
        ),
        frozen=True,
    )
    assert spec.frozen
    with pytest.raises(ValueError, match="distinct checkpoints"):
        CrossModelComparisonSpec.model_validate(
            spec.model_dump(mode="json") | {"comparator_checkpoint": "evo2-7b"}
        )

    observation = CrossModelObservation(
        comparison_id=spec.comparison_id,
        checkpoint=spec.comparator_checkpoint,
        sequence_digest="c" * 64,
        reference_score=-2,
        alternate_score=-3,
        effect=-1,
        output_artifact_digest="d" * 64,
        execution_mode="real",
        scientific_use_allowed=True,
    )
    assert observation.effect == -1
    with pytest.raises(ValueError, match="alternate minus reference"):
        CrossModelObservation.model_validate(
            observation.model_dump(mode="json") | {"effect": 1}
        )
