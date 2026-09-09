"""RDKit molecular fingerprint generation."""

from __future__ import annotations

import numpy as np
from rdkit import Chem, DataStructs
from rdkit.Chem import rdFingerprintGenerator

from concordia.config import FingerprintConfig


def morgan_fingerprints(smiles_values: list[str], config: FingerprintConfig) -> np.ndarray:
    generator = rdFingerprintGenerator.GetMorganGenerator(
        radius=config.radius,
        fpSize=config.n_bits,
        includeChirality=config.include_chirality,
    )
    matrix = np.zeros((len(smiles_values), config.n_bits), dtype=np.uint8)
    for index, smiles in enumerate(smiles_values):
        molecule = Chem.MolFromSmiles(smiles)
        if molecule is None:
            raise ValueError(f"Invalid canonical SMILES at position {index}: {smiles!r}")
        fingerprint = generator.GetFingerprint(molecule)
        DataStructs.ConvertToNumpyArray(fingerprint, matrix[index])
    return matrix
