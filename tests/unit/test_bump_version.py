"""Unit tests for bump_version.py — _bump_minor edge cases."""

import bump_version as bv


def test_bump_minor_three_components():
    assert bv._bump_minor("3.5.2") == "3.6.0"


def test_bump_minor_three_components_at_zero():
    assert bv._bump_minor("3.5.0") == "3.6.0"


def test_bump_minor_two_components():
    assert bv._bump_minor("3.5") == "3.6"


def test_bump_minor_major_zero():
    assert bv._bump_minor("0.0.0") == "0.1.0"


def test_bump_minor_large_minor():
    assert bv._bump_minor("10.99.0") == "10.100.0"


def test_bump_minor_resets_patch():
    assert bv._bump_minor("1.2.99") == "1.3.0"


def test_bump_minor_preserves_major():
    assert bv._bump_minor("5.0.0") == "5.1.0"
