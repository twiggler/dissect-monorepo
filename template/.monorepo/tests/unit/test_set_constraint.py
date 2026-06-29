"""Unit tests for set_constraint.py — _replace_specifier edge cases."""

import set_constraint as sc


def test_replace_basic():
    result = sc._replace_specifier("dissect.cstruct>=4.0", "dissect.cstruct", ">=4.7,<5")
    assert result == "dissect.cstruct>=4.7,<5"


def test_replace_no_existing_specifier():
    result = sc._replace_specifier("dissect.cstruct", "dissect.cstruct", ">=4.7,<5")
    assert result == "dissect.cstruct>=4.7,<5"


def test_replace_no_match_returns_none():
    result = sc._replace_specifier("dissect.util>=1.0", "dissect.cstruct", ">=4.7,<5")
    assert result is None


def test_replace_preserves_extras():
    result = sc._replace_specifier("dissect.cstruct[extra]>=4.0", "dissect.cstruct", ">=4.7,<5")
    assert result == "dissect.cstruct[extra]>=4.7,<5"


def test_replace_preserves_marker():
    result = sc._replace_specifier(
        'dissect.cstruct>=4.0 ; python_version >= "3.11"',
        "dissect.cstruct",
        ">=4.7,<5",
    )
    assert result is not None
    assert ">=4.7,<5" in result
    assert 'python_version >= "3.11"' in result


def test_replace_preserves_extras_and_marker():
    result = sc._replace_specifier(
        'dissect.cstruct[extra]>=4.0 ; sys_platform == "win32"',
        "dissect.cstruct",
        ">=4.7,<5",
    )
    assert result is not None
    assert "dissect.cstruct[extra]>=4.7,<5" in result
    assert 'sys_platform == "win32"' in result


def test_replace_normalised_name_dash_vs_dot():
    # dissect-cstruct and dissect.cstruct are the same canonical name
    result = sc._replace_specifier("dissect-cstruct>=4.0", "dissect.cstruct", ">=4.7,<5")
    assert result is not None
    assert ">=4.7,<5" in result


def test_replace_multiple_extras_sorted():
    result = sc._replace_specifier("dissect.cstruct[b,a]>=4.0", "dissect.cstruct", ">=5.0")
    assert result is not None
    # extras are sorted by _replace_specifier
    assert "[a,b]" in result
