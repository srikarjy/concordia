import pytest

from scripts.freeze_tsuboyama_rule2_manifest import Candidate, _align


def test_ambiguous_uniprot_alignment_aborts() -> None:
    candidate = Candidate(
        domain_id="repeat.pdb",
        sequence="AB",
        length=2,
        single_substitution_count=0,
        structure_path="repeat.pdb",
    )

    with pytest.raises(ValueError, match="ambiguous"):
        _align(candidate, "P00000", "ABAB")
