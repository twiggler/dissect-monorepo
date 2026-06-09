# /// script
# dependencies = []
# ///

"""Rewrite the 'Build and test instructions' section in each project README.

Replaces tox-based instructions (``tox -e build``, ``tox``) with the
monorepo equivalents:

- ``just test <project>``   — runs the test suite via ``uv run pytest``
- ``uv build --package``    — builds source and wheel distributions

The replacement is idempotent: if a README already contains the new
section it is left untouched.
"""

import re
import sys
from pathlib import Path


# The section ends just before the next `## ` heading.  We match from the
# heading line through the last character before the blank-line separator
# that precedes the next heading.
_SECTION_PATTERN = re.compile(
    r"^## Build and test instructions\n.*?(?=\n## )",
    re.MULTILINE | re.DOTALL,
)

# Sentinel: if this string is already present the section is up-to-date.
_SENTINEL = "just test "

_SECTION_TEMPLATE = """\
## Build and test instructions

This project is part of the [dissect monorepo](https://github.com/fox-it/dissect). \
Building and testing is managed from the monorepo root.

To run the tests for this project, run the following command from the monorepo root:

```bash
just test {project}
```

To build source and wheel distributions:

```bash
uv build --package {project} --out-dir dist/{project}
```

The build artifacts can be found in the `dist/{project}/` directory.

For a more elaborate explanation on how to build and test the project, please see \
[the recipes](../../doc/recipes.md) or \
[the documentation](https://docs.dissect.tools/en/latest/contributing/tooling.html).
"""


def _rewrite_readme(readme_path: Path) -> bool:
    project = readme_path.parent.name
    text = readme_path.read_text()

    if _SENTINEL in text:
        print(f"  [✓] already up-to-date: {readme_path}")
        return False

    new_section = _SECTION_TEMPLATE.format(project=project)
    new_text, count = _SECTION_PATTERN.subn(new_section, text)

    if count == 0:
        print(f"  [!] section not found, skipping: {readme_path}")
        return False

    readme_path.write_text(new_text)
    print(f"  [~] updated: {readme_path}")
    return True


def main() -> None:
    projects_dir = Path("projects")
    if not projects_dir.exists():
        print("Error: 'projects' directory not found. Run from the monorepo root.", file=sys.stderr)
        sys.exit(1)

    for readme_path in sorted(projects_dir.glob("*/README.md")):
        print(f"Processing {readme_path}...")
        _rewrite_readme(readme_path)


if __name__ == "__main__":
    main()
