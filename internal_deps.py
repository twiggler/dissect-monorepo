# /// script
# dependencies = ["tomlkit"]
# ///

import tomlkit
from pathlib import Path

# The prefix for your internal packages
PREFIX = "dissect."

def patch_pyproject(file_path):
    print(f"Processing {file_path}...")
    with open(file_path, "r", encoding="utf-8") as f:
        doc = tomlkit.parse(f.read())

    # 1. Identify internal dependencies
    internal_deps = set()
    
    # Check main dependencies
    deps = doc.get("project", {}).get("dependencies", [])
    for dep in deps:
        # Extract the package name before any version specifiers (>=, <, etc.)
        name = dep.split(">")[0].split("=")[0].split("<")[0].split("~")[0].split("[")[0].strip()
        if name.startswith(PREFIX):
            internal_deps.add(name)

    # Check optional dependencies (extras)
    optional_deps = doc.get("project", {}).get("optional-dependencies", {})
    for group in optional_deps.values():
        for dep in group:
            name = dep.split(">")[0].split("=")[0].split("<")[0].split("~")[0].split("[")[0].strip()
            if name.startswith(PREFIX):
                internal_deps.add(name)

    if not internal_deps:
        print(f"  [-] No internal '{PREFIX}' dependencies found.")
        return

    # 2. Rebuild [tool.uv.sources]
    # Ensure tool and tool.uv exist
    if "tool" not in doc:
        doc["tool"] = tomlkit.table()
    if "uv" not in doc["tool"]:
        doc["tool"]["uv"] = tomlkit.table()
    
    # Create or clear the sources table
    sources = tomlkit.table()
    for dep in sorted(internal_deps):
        sources[dep] = {"workspace": True}
    
    doc["tool"]["uv"]["sources"] = sources
    print(f"  [✓] Added {len(internal_deps)} internal sources to [tool.uv.sources]")

    # 3. Write back with formatting preserved
    with open(file_path, "w", encoding="utf-8") as f:
        f.write(tomlkit.dumps(doc))

def main():
    projects_dir = Path("projects")
    if not projects_dir.exists():
        print("Error: 'projects' directory not found.")
        return

    for toml_path in projects_dir.rglob("pyproject.toml"):
        patch_pyproject(toml_path)

if __name__ == "__main__":
    main()
