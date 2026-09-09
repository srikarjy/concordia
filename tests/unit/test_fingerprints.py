import numpy as np

from concordia.config import FingerprintConfig
from concordia.predictors.fingerprints import morgan_fingerprints


def test_morgan_fingerprints_are_stable_binary_arrays() -> None:
    config = FingerprintConfig(radius=2, n_bits=128, include_chirality=True)
    first = morgan_fingerprints(["CCO", "c1ccccc1"], config)
    second = morgan_fingerprints(["CCO", "c1ccccc1"], config)

    assert first.shape == (2, 128)
    assert first.dtype == np.uint8
    assert set(np.unique(first)).issubset({0, 1})
    np.testing.assert_array_equal(first, second)
