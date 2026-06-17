"""Unit tests for bump_version.py — _bump_minor and _find_release_tag edge cases."""

from unittest.mock import patch

import bump_version as bv


def test_bump_minor_three_components():
    assert bv._bump_minor("3.5.2") == "3.6"


def test_bump_minor_three_components_at_zero():
    assert bv._bump_minor("3.5.0") == "3.6"


def test_bump_minor_two_components():
    assert bv._bump_minor("3.5") == "3.6"


def test_bump_minor_major_zero():
    assert bv._bump_minor("0.0.0") == "0.1"


def test_bump_minor_large_minor():
    assert bv._bump_minor("10.99.0") == "10.100"


def test_bump_minor_resets_patch():
    assert bv._bump_minor("1.2.99") == "1.3"


def test_bump_minor_preserves_major():
    assert bv._bump_minor("5.0.0") == "5.1"


# ---------------------------------------------------------------------------
# _find_release_tag — tag equivalence (M.m.0 ↔ M.m)
# ---------------------------------------------------------------------------


def test_find_release_tag_exact_match():
    """Primary tag exists — returned immediately."""
    with patch.object(bv, "_tag_exists", return_value=True):
        assert bv._find_release_tag("pkg", "1.23") == "pkg/1.23"


def test_find_release_tag_long_to_short():
    """Version stored as M.m.0, tag was created as M.m — still recognised."""

    def _exists(tag):
        return tag == "pkg/1.23"

    with patch.object(bv, "_tag_exists", side_effect=_exists):
        assert bv._find_release_tag("pkg", "1.23.0") == "pkg/1.23"


def test_find_release_tag_short_to_long():
    """Version stored as M.m, tag was created as M.m.0 — still recognised."""

    def _exists(tag):
        return tag == "pkg/1.23.0"

    with patch.object(bv, "_tag_exists", side_effect=_exists):
        assert bv._find_release_tag("pkg", "1.23") == "pkg/1.23.0"


def test_find_release_tag_nonzero_patch_no_alt():
    """Non-zero patch — no alternate form is tried; returns None when primary missing."""
    with patch.object(bv, "_tag_exists", return_value=False):
        assert bv._find_release_tag("pkg", "1.23.4") is None
