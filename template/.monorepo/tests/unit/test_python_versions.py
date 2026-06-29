"""Unit tests for python_versions.py — version-to-identifier mapping."""

import pytest

import python_versions as pv

# ---------------------------------------------------------------------------
# version_to_cibw_id
# ---------------------------------------------------------------------------


def test_cpython_two_component():
    assert pv.version_to_cibw_id("3.11") == "cp311-*"


def test_cpython_minor_two_digits():
    assert pv.version_to_cibw_id("3.12") == "cp312-*"


def test_cpython_single_digit_minor():
    assert pv.version_to_cibw_id("3.9") == "cp39-*"


def test_pypy_version():
    assert pv.version_to_cibw_id("pypy3.11") == "pp311-*"


def test_pypy_different_minor():
    assert pv.version_to_cibw_id("pypy3.10") == "pp310-*"


# ---------------------------------------------------------------------------
# cibw_build_string
# ---------------------------------------------------------------------------


def test_cibw_build_string_cpython_only():
    result = pv.cibw_build_string(["3.10", "3.11"])
    assert result == "cp310-* cp311-*"


def test_cibw_build_string_does_not_include_free_threaded():
    result = pv.cibw_build_string(["3.12"])
    assert "cp3??t-*" not in result


def test_cibw_build_string_mixed_cpython_and_pypy():
    result = pv.cibw_build_string(["3.10", "3.11", "pypy3.11"])
    assert result == "cp310-* cp311-* pp311-*"


def test_cibw_build_string_empty_versions():
    result = pv.cibw_build_string([])
    assert result == ""


# ---------------------------------------------------------------------------
# min_cpython_abi
# ---------------------------------------------------------------------------


def test_min_cpython_abi_single():
    assert pv.min_cpython_abi(["3.10"]) == "cp310"


def test_min_cpython_abi_picks_minimum():
    assert pv.min_cpython_abi(["3.11", "3.10", "3.12"]) == "cp310"


def test_min_cpython_abi_ignores_pypy():
    assert pv.min_cpython_abi(["3.10", "3.11", "pypy3.11"]) == "cp310"


def test_min_cpython_abi_only_pypy_raises():
    with pytest.raises(ValueError, match="No CPython version"):
        pv.min_cpython_abi(["pypy3.11"])
