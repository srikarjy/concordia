from concordia.design.loop import (
    D1_SCOPE_STATEMENT,
    compare_structures,
    fixed_positions_jsonl,
    motif_refusal,
    render_scope_statement,
)


def _ca_only_pdb(
    chain_a: list[tuple[str, float, float, float]],
    chain_b: list[tuple[str, float, float, float]],
) -> str:
    lines: list[str] = []
    serial = 1
    for chain_id, residues in (("A", chain_a), ("B", chain_b)):
        for residue_index, (resname, x, y, z) in enumerate(residues, start=1):
            lines.append(
                f"ATOM  {serial:5d}  CA  {resname:>3} {chain_id}{residue_index:4d}    "
                f"{x:8.3f}{y:8.3f}{z:8.3f}  1.00 20.00           C"
            )
            serial += 1
        lines.append("TER")
    lines.append("END")
    return "\n".join(lines) + "\n"


def test_design_with_changed_hard_protected_motif_is_refused() -> None:
    refusal = motif_refusal(
        sequence="QEDNDEA",
        motif_positions=(1, 2, 3, 4, 5, 6, 7),
        motif_letters="QEDNDEE",
        accession="P02633",
        feature_type="UniProt BINDING",
    )
    assert refusal is not None
    assert refusal.trigger == "HARD_PROTECTED_MOTIF_MUTATION"
    assert refusal.evidence["violations"][0]["observed"] == "A"
    assert refusal.evidence["violations"][0]["accession"] == "P02633"


def test_unchanged_motif_is_not_refused() -> None:
    assert (
        motif_refusal(
            sequence="QEDNDEE",
            motif_positions=(1, 2, 3, 4, 5, 6, 7),
            motif_letters="QEDNDEE",
            accession="P02633",
            feature_type="UniProt BINDING",
        )
        is None
    )


def test_scope_statement_rejects_biological_interpretation() -> None:
    statement = render_scope_statement()
    assert statement == D1_SCOPE_STATEMENT
    assert "does not show folding" in statement
    assert "does not show" in statement
    assert "biological success" in statement


def test_fixed_positions_jsonl_is_one_based_and_chain_scoped() -> None:
    assert fixed_positions_jsonl("B", (1, 6)) == '{"input":{"B":[1,6]}}'


def test_structure_comparison_fits_generated_chain_and_measures_motif_in_that_frame() -> None:
    backbone = _ca_only_pdb(
        [("ALA", 0.0, 0.0, 0.0), ("ALA", 1.0, 0.0, 0.0), ("ALA", 0.0, 1.0, 0.0)],
        [("GLN", 10.0, 0.0, 0.0), ("GLU", 11.0, 0.0, 0.0), ("ASP", 10.0, 1.0, 0.0)],
    )
    refold = _ca_only_pdb(
        [("ALA", 20.0, 0.0, 0.0), ("ALA", 21.0, 0.0, 0.0), ("ALA", 20.0, 1.0, 0.0)],
        [("GLN", 30.0, 5.0, 0.0), ("GLU", 31.0, 5.0, 0.0), ("ASP", 30.0, 6.0, 0.0)],
    )
    result = compare_structures(backbone, "pdb", refold, "pdb", "QED", (0, 1, 2))
    assert result.global_ca_atoms == 3
    assert result.motif_ca_atoms == 3
    assert result.global_rmsd_angstrom < 1e-9
    assert result.motif_rmsd_angstrom > 1.0
    assert "generated chain A" in result.global_superposition
