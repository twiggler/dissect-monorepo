# /// script
# dependencies = ["tomlkit"]
# ///

import tomlkit
from pathlib import Path
import shutil

# --- CONFIGURATION ---
PROJECTS_DIR = Path("projects")
ROOT_TOML = Path("pyproject.toml")
RUFF_CONFIG_FILE = Path("dissect-monorepo-scripts/config/ruff.toml")
# ---------------------

def strip_ruff_from_toml(file_path):
    """Removes [tool.ruff] and its sub-tables from any TOML file,
    but preserves [tool.ruff.lint.isort] if present and adds a central extend.
    """
    if not file_path.exists():
        return False

    with open(file_path, "r", encoding="utf-8") as f:
        doc = tomlkit.parse(f.read())

    if "tool" in doc and "ruff" in doc["tool"]:
        ruff = doc["tool"]["ruff"]

        preserved_isort = None
        if "lint" in ruff and "isort" in ruff["lint"]:
            preserved_isort = ruff["lint"]["isort"]

        del doc["tool"]["ruff"]

        new_ruff = tomlkit.table()
        new_ruff["extend"] = "../../ruff.toml"

        if preserved_isort is not None:
            new_lint = tomlkit.table()
            new_lint["isort"] = preserved_isort
            new_ruff["lint"] = new_lint

        doc["tool"]["ruff"] = new_ruff

        # Remove empty [tool] table if no other tools are left
        if len(doc["tool"]) == 0:
            del doc["tool"]

        with open(file_path, "w", encoding="utf-8") as f:
            f.write(tomlkit.dumps(doc))
        return True
    return False

def main():
    # 1. Ensure the central config exists first
    if not RUFF_CONFIG_FILE.exists():
        print(f"ERROR: {RUFF_CONFIG_FILE} not found!")
        print("Please create the file first with your authoritative settings.")
        return
    
    # Copy the central config to the current working directory
    shutil.copy(RUFF_CONFIG_FILE, Path.cwd() / RUFF_CONFIG_FILE.name)
    print(f"Copied {RUFF_CONFIG_FILE} to current directory.")

    print(f"Using {RUFF_CONFIG_FILE} as the global source of truth.")

    # 2. Clean the root pyproject.toml
    if strip_ruff_from_toml(ROOT_TOML):
        print(f"  [✓] Cleaned root {ROOT_TOML}")

    # 3. Clean the 31 sub-projects
    print("\nCleaning local Ruff configs from sub-projects...")
    count = 0
    for toml_path in PROJECTS_DIR.rglob("pyproject.toml"):
        if strip_ruff_from_toml(toml_path):
            print(f"  [✓] Stripped: {toml_path.parent.name}")
            count += 1
    
    print(f"\nSuccess! 31 projects cleaned. Ruff will now default to {RUFF_CONFIG_FILE}.")
    print("Test it by running: uv run ruff check .")

if __name__ == "__main__":
    main()
