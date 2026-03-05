# /// script
# dependencies = ["tomlkit"]
# ///

import tomlkit
from pathlib import Path

# --- CONFIGURATION ---
TARGET_DEPS = {
    "ruff": "0.13.1",
    "pytest": "8.0.0",
}
PROJECTS_DIR = Path("projects")
ROOT_TOML = Path("pyproject.toml")
# ---------------------

def filter_dependencies(dep_list):
    """Safely removes target dependencies from a tomlkit Array or list."""
    to_remove = []
    for i, dep in enumerate(dep_list):
        # We handle both strings and complex objects (though dev deps are usually strings)
        dep_str = str(dep)
        if any(dep_str.startswith(t) for t in TARGET_DEPS):
            to_remove.append(i)
    
    # Remove from back to front to keep indices valid
    for index in reversed(to_remove):
        dep_list.pop(index)
    
    return len(to_remove) > 0

def clean_subproject(file_path):
    """Removes target dependencies from a single sub-project."""
    with open(file_path, "r", encoding="utf-8") as f:
        doc = tomlkit.parse(f.read())

    modified = False
    
    # 1. Check [project.optional-dependencies]
    opt_deps = doc.get("project", {}).get("optional-dependencies", {})
    for group in opt_deps.values():
        if filter_dependencies(group):
            modified = True

    # 2. Check [dependency-groups] (The newer standard)
    dep_groups = doc.get("dependency-groups", {})
    for group in dep_groups.values():
        if filter_dependencies(group):
            modified = True

    if modified:
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(tomlkit.dumps(doc))
        print(f"  [✓] Cleaned {file_path.parent.name}")

def update_root():
    """Adds the target dependencies to the root pyproject.toml."""
    if not ROOT_TOML.exists():
        print("Error: Root pyproject.toml not found.")
        return

    with open(ROOT_TOML, "r", encoding="utf-8") as f:
        doc = tomlkit.parse(f.read())

    if "dependency-groups" not in doc:
        doc["dependency-groups"] = tomlkit.table()
    
    if "dev" not in doc["dependency-groups"]:
        doc["dependency-groups"]["dev"] = tomlkit.array()

    dev_group = doc["dependency-groups"]["dev"]
    
    for name, version in TARGET_DEPS.items():
        spec = f"{name}=={version}"
        # Only add if it's not already there
        if not any(str(d).startswith(name) for d in dev_group):
            dev_group.append(spec)
            print(f"  [+] Added {spec} to root dev group")

    with open(ROOT_TOML, "w", encoding="utf-8") as f:
        f.write(tomlkit.dumps(doc))

def main():
    print("Updating root pyproject.toml...")
    update_root()

    print("\nCleaning sub-projects...")
    for toml_path in PROJECTS_DIR.rglob("pyproject.toml"):
        clean_subproject(toml_path)

if __name__ == "__main__":
    main()