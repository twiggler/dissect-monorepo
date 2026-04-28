# /// script
# dependencies = []
# ///

"""Patch tests/_docs/conf.py files in all projects for the monorepo layout.

Fixes applied to every project:

1. autoapi_dirs — In the multirepo layout the source lived at the project
   root (``dissect/``), so ``autoapi_dirs`` pointed to ``"../../dissect/"``.
   After migration the source moves into ``src/`` (``src/dissect/``), so the
   path must become ``"../../src/dissect/"``.

2. suppress_warnings — sphinx-autoapi uses astroid for static import
   resolution, which has a known bug with implicit namespace packages
   (e.g. ``dissect.*``).  The ``autoapi.python_import_resolution`` warning
   is suppressed in every conf.py so that ``--fail-on-warning`` does not
   cause false-positive failures.
   See: https://github.com/readthedocs/sphinx-autoapi/issues/285

3. imported-members — Removing ``"imported-members"`` from
   ``autoapi_options`` prevents sphinx-autoapi from documenting re-exported
   symbols at both the re-export location and the original definition
   location.  Without this fix, packages that re-export symbols via
   ``__init__.py`` produce duplicate object descriptions and ambiguous
   ``ref.python`` cross-reference warnings (especially common with the
   ``type`` attribute shared across many cstruct-derived classes).
"""

import re
from pathlib import Path


def _fix_docs_conf_autoapi_dirs(conf_path: Path) -> bool:
    """Fix autoapi_dirs in tests/_docs/conf.py for the monorepo src/ layout.

    In the multirepo layout the source lived at the project root (``dissect/``),
    so ``autoapi_dirs`` pointed to ``"../../dissect/"``.  After migration the
    source moves into ``src/`` (``src/dissect/``), so the path must become
    ``"../../src/dissect/"``.
    """
    old = '["../../dissect/"]'
    new = '["../../src/dissect/"]'
    pattern = re.compile(r'^(autoapi_dirs\s*=\s*)(\[.*\])', re.MULTILINE)

    text = conf_path.read_text()

    def replacer(m: re.Match) -> str:
        return m.group(1) + new if m.group(2) == old else m.group(0)

    new_text = pattern.sub(replacer, text)
    if new_text == text:
        print(f"  [✓] autoapi_dirs already correct or not present: {conf_path}")
        return False

    conf_path.write_text(new_text)
    print(f"  [~] autoapi_dirs: updated {conf_path}")
    return True


_SUPPRESS_WARNINGS_BLOCK = """\
suppress_warnings = [
    # https://github.com/readthedocs/sphinx-autoapi/issues/285
    "autoapi.python_import_resolution",
]"""


def _fix_docs_conf_suppress_warnings(conf_path: Path) -> bool:
    """Ensure suppress_warnings contains the autoapi import-resolution entry.

    sphinx-autoapi uses astroid for static import resolution, which has a
    known bug with implicit namespace packages (e.g. ``dissect.*``).  Every
    project conf.py must suppress this warning so that ``--fail-on-warning``
    does not cause false-positive failures.

    See: https://github.com/readthedocs/sphinx-autoapi/issues/285
    """
    text = conf_path.read_text()
    if "autoapi.python_import_resolution" in text:
        print(f"  [✓] suppress_warnings already present: {conf_path}")
        return False

    anchor = "autoapi_python_use_implicit_namespaces = True"
    if anchor not in text:
        print(f"  [!] anchor not found, skipping: {conf_path}")
        return False

    new_text = text.replace(anchor, anchor + "\n" + _SUPPRESS_WARNINGS_BLOCK)
    conf_path.write_text(new_text)
    print(f"  [~] suppress_warnings: added to {conf_path}")
    return True


def _fix_docs_conf_remove_imported_members(conf_path: Path) -> bool:
    """Remove ``"imported-members"`` from ``autoapi_options``.

    With ``imported-members`` enabled, sphinx-autoapi documents every symbol
    that is re-exported via ``__init__.py`` at *both* the re-export location
    and the original definition location.  This causes duplicate object
    descriptions and ambiguous ``ref.python`` cross-reference warnings that
    cannot reliably be fixed at the source level across the whole monorepo.

    Removing the option means autoapi only documents members at the module
    where they are defined, which is both correct and stable.
    """
    text = conf_path.read_text()
    if '"imported-members"' not in text:
        print(f"  [✓] imported-members already absent: {conf_path}")
        return False

    new_text = re.sub(r'\n    "imported-members",', "", text)
    if new_text == text:
        print(f"  [!] could not remove imported-members from {conf_path}")
        return False

    conf_path.write_text(new_text)
    print(f"  [~] imported-members: removed from {conf_path}")
    return True


def main() -> None:
    projects_dir = Path("projects")
    if not projects_dir.exists():
        print("Error: 'projects' directory not found.")
        return

    for conf_path in sorted(projects_dir.glob("*/tests/_docs/conf.py")):
        print(f"Processing {conf_path}...")
        _fix_docs_conf_autoapi_dirs(conf_path)
        _fix_docs_conf_suppress_warnings(conf_path)
        _fix_docs_conf_remove_imported_members(conf_path)


if __name__ == "__main__":
    main()
