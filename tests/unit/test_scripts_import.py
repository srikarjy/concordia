"""Every script in scripts/ must import and expose a main().

The benchmark scripts are not part of the package and CI does not lint or type
check them, so a signature change in a shared helper can break them silently.
That happened once: adding a required argument to ``structure_measurements``
broke ``paratope_counterfactual`` three hours into a run.

These tests need biopython, which is deliberately not a project dependency, so
they skip where it is missing. That means CI does not run them today; they catch
the break for anyone working on the scripts locally.
"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pytest

pytest.importorskip("Bio", reason="scripts need biopython, which is not a project dependency")

SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"
# Scripts that run work at import time rather than under a main() guard.
LEGACY = {"score_complex_against_crystal"}
MODULES = sorted(
    path.stem
    for path in SCRIPTS.glob("*.py")
    if not path.stem.startswith("_") and path.stem not in LEGACY
)


@pytest.fixture(autouse=True)
def _scripts_on_path():
    sys.path.insert(0, str(SCRIPTS))
    try:
        yield
    finally:
        sys.path.remove(str(SCRIPTS))


def test_every_script_is_discovered():
    assert "structure_measurements" in MODULES
    assert "paratope_counterfactual" in MODULES


@pytest.mark.parametrize("name", MODULES)
def test_script_imports_and_resolves_its_helpers(name):
    module = importlib.import_module(name)
    assert module.__doc__, f"{name} needs a docstring explaining what it does"


@pytest.mark.parametrize("name", [n for n in MODULES if n != "structure_measurements"])
def test_entry_point_scripts_expose_main(name):
    module = importlib.import_module(name)
    assert callable(getattr(module, "main", None)), f"{name} has no main()"


def _three_chain_cif(path: Path) -> Path:
    """A minimal three-chain structure: two receptor chains in contact with a ligand."""
    rows = []
    serial = 1
    # Chains 1 A and 2 B sit beside chain 3 C, close enough to register contacts.
    for chain, residues, x_offset in (("A", 2, 0.0), ("B", 2, 3.0), ("C", 2, 6.0)):
        for index in range(residues):
            for atom, element, bump in (("N", "N", 0.0), ("CA", "C", 1.2), ("CB", "C", 2.0)):
                rows.append(
                    f"ATOM {serial} {element} {atom} . ALA {chain} 1 {index + 1} ? "
                    f"{x_offset + bump:.3f} {index * 2.0:.3f} 0.000 1.00 20.00 "
                    f"{chain} {index + 1} 1"
                )
                serial += 1
    body = "\n".join(rows)
    path.write_text(
        "data_test\n"
        "loop_\n"
        "_atom_site.group_PDB\n_atom_site.id\n_atom_site.type_symbol\n"
        "_atom_site.label_atom_id\n_atom_site.label_alt_id\n_atom_site.label_comp_id\n"
        "_atom_site.label_asym_id\n_atom_site.label_entity_id\n_atom_site.label_seq_id\n"
        "_atom_site.pdbx_PDB_ins_code\n_atom_site.Cartn_x\n_atom_site.Cartn_y\n"
        "_atom_site.Cartn_z\n_atom_site.occupancy\n_atom_site.B_iso_or_equiv\n"
        "_atom_site.auth_asym_id\n_atom_site.auth_seq_id\n_atom_site.pdbx_PDB_model_num\n"
        f"{body}\n"
    )
    return path


def test_shared_helpers_run_against_a_real_structure(tmp_path):
    """Calls the helpers, which an import alone does not: the break was an arity error."""
    measurements = importlib.import_module("structure_measurements")
    cif = _three_chain_cif(tmp_path / "mini.cif")

    physical = measurements.physical(cif)
    assert set(physical) == {"clash_count", "buried_surface_area", "variable_domain_fraction"}
    # A designed binder has no variable domain, so that signal must be absent.
    assert "variable_domain_fraction" not in measurements.physical(cif, measurements.BINDER_ROLES)
    assert measurements.interface_agreement(cif, cif) == 1.0
    assert all(
        isinstance(chain, str) and isinstance(index, int)
        for chain, index in measurements.interface_residues(cif)
    )


def test_paratope_selection_runs_end_to_end(tmp_path):
    """The exact call path that a required-argument change broke."""
    counterfactual = importlib.import_module("paratope_counterfactual")
    sites = counterfactual.paratope(_three_chain_cif(tmp_path / "mini.cif"))
    assert set(sites) == {"H", "L"}
    assert all(isinstance(index, int) for indices in sites.values() for index in indices)
    assert counterfactual.mutate("CCCC", [0, 2]) == "ACAC"
