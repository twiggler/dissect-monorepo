"""Unit tests for affected_tests.py — pure graph logic."""

import affected_tests as af


# ---------------------------------------------------------------------------
# is_global_trigger
# ---------------------------------------------------------------------------

def test_global_trigger_root_pyproject():
    assert af.is_global_trigger(["pyproject.toml"])


def test_global_trigger_uvlock():
    assert af.is_global_trigger(["uv.lock"])


def test_global_trigger_justfile():
    assert af.is_global_trigger(["Justfile"])


def test_global_trigger_monorepo_script():
    assert af.is_global_trigger([".monorepo/affected_tests.py"])


def test_global_trigger_workflow():
    assert af.is_global_trigger([".github/workflows/ci.yml"])


def test_global_trigger_mixed_with_regular():
    # Even a single global-trigger file in a mixed list should trigger all.
    assert af.is_global_trigger([
        "projects/dissect.util/dissect/util/__init__.py",
        "uv.lock",
    ])


def test_not_global_trigger_project_file():
    assert not af.is_global_trigger(["projects/dissect.util/dissect/util/__init__.py"])


def test_not_global_trigger_empty():
    assert not af.is_global_trigger([])


# ---------------------------------------------------------------------------
# transitive_dependents
# ---------------------------------------------------------------------------

def test_transitive_dependents_isolated():
    reverse = {"a": set(), "b": set(), "c": set()}
    assert af.transitive_dependents({"a"}, reverse) == {"a"}


def test_transitive_dependents_direct_only():
    # b depends on a; changing a should pull in b but not c
    # reverse[x] = set of packages that depend on x
    reverse = {"a": {"b"}, "b": set(), "c": set()}
    assert af.transitive_dependents({"a"}, reverse) == {"a", "b"}


def test_transitive_dependents_chain():
    # b depends on a, c depends on b; changing a should affect a, b, c
    reverse = {"a": {"b"}, "b": {"c"}, "c": set()}
    assert af.transitive_dependents({"a"}, reverse) == {"a", "b", "c"}


def test_transitive_dependents_diamond():
    # base ← {b, c} ← d: changing base should reach d via both paths
    reverse = {
        "base": {"b", "c"},
        "b": {"d"},
        "c": {"d"},
        "d": set(),
    }
    result = af.transitive_dependents({"base"}, reverse)
    assert result == {"base", "b", "c", "d"}


def test_transitive_dependents_multiple_seeds():
    # b depends on a, d depends on c
    reverse = {"a": {"b"}, "b": set(), "c": {"d"}, "d": set()}
    result = af.transitive_dependents({"a", "c"}, reverse)
    assert result == {"a", "b", "c", "d"}


# ---------------------------------------------------------------------------
# build_reverse_graph
# ---------------------------------------------------------------------------

def test_build_reverse_graph_simple(tmp_path):
    # Dependency graph (forward):  pkg-a --> pkg-b
    # Reverse graph:               pkg-b --> {pkg-a}
    (tmp_path / "pkg-a").mkdir()
    (tmp_path / "pkg-a" / "pyproject.toml").write_text(
        '[project]\nname = "pkg-a"\nversion = "1.0"\ndependencies = ["pkg-b>=1.0"]\n'
    )
    (tmp_path / "pkg-b").mkdir()
    (tmp_path / "pkg-b" / "pyproject.toml").write_text(
        '[project]\nname = "pkg-b"\nversion = "1.0"\ndependencies = []\n'
    )
    workspace = {
        "pkg-a": ("pkg-a", tmp_path / "pkg-a"),
        "pkg-b": ("pkg-b", tmp_path / "pkg-b"),
    }
    reverse = af.build_reverse_graph(workspace)
    assert reverse["pkg-b"] == {"pkg-a"}
    assert reverse["pkg-a"] == set()


def test_build_reverse_graph_optional_deps(tmp_path):
    # Same topology as the simple case but the dependency is declared in
    # [project.optional-dependencies] rather than [project.dependencies]:
    #
    #   Dependency graph (forward):  pkg-a --[extra]--> pkg-b
    #   Reverse graph:               pkg-b --> {pkg-a}
    (tmp_path / "pkg-a").mkdir()
    (tmp_path / "pkg-a" / "pyproject.toml").write_text(
        '[project]\nname = "pkg-a"\nversion = "1.0"\ndependencies = []\n'
        '[project.optional-dependencies]\nextra = ["pkg-b>=1.0"]\n'
    )
    (tmp_path / "pkg-b").mkdir()
    (tmp_path / "pkg-b" / "pyproject.toml").write_text(
        '[project]\nname = "pkg-b"\nversion = "1.0"\ndependencies = []\n'
    )
    workspace = {
        "pkg-a": ("pkg-a", tmp_path / "pkg-a"),
        "pkg-b": ("pkg-b", tmp_path / "pkg-b"),
    }
    reverse = af.build_reverse_graph(workspace)
    assert reverse["pkg-b"] == {"pkg-a"}


def test_build_reverse_graph_no_self_loop(tmp_path):
    # A package listing itself as a dependency should not create a self-loop:
    #
    #   Dependency graph (forward):  pkg-a --> pkg-a  (self-reference)
    #   Reverse graph:               pkg-a --> {}      (self-loop suppressed)
    (tmp_path / "pkg-a").mkdir()
    (tmp_path / "pkg-a" / "pyproject.toml").write_text(
        '[project]\nname = "pkg-a"\nversion = "1.0"\ndependencies = ["pkg-a>=1.0"]\n'
    )
    workspace = {"pkg-a": ("pkg-a", tmp_path / "pkg-a")}
    reverse = af.build_reverse_graph(workspace)
    assert reverse["pkg-a"] == set()


# ---------------------------------------------------------------------------
# packages_from_changed_files
# ---------------------------------------------------------------------------

def test_packages_from_changed_files_match(tmp_path, monkeypatch):
    pkg_dir = tmp_path / "projects" / "pkg-a"
    pkg_dir.mkdir(parents=True)
    workspace = {"pkg-a": ("pkg-a", pkg_dir)}
    monkeypatch.setattr(af, "WORKSPACE_ROOT", tmp_path)
    result = af.packages_from_changed_files(["projects/pkg-a/module.py"], workspace)
    assert result == {"pkg-a"}


def test_packages_from_changed_files_unrelated(tmp_path, monkeypatch):
    pkg_dir = tmp_path / "projects" / "pkg-a"
    pkg_dir.mkdir(parents=True)
    workspace = {"pkg-a": ("pkg-a", pkg_dir)}
    monkeypatch.setattr(af, "WORKSPACE_ROOT", tmp_path)
    result = af.packages_from_changed_files(["unrelated/file.py"], workspace)
    assert result == set()


def test_packages_from_changed_files_multiple(tmp_path, monkeypatch):
    (tmp_path / "projects" / "pkg-a").mkdir(parents=True)
    (tmp_path / "projects" / "pkg-b").mkdir(parents=True)
    workspace = {
        "pkg-a": ("pkg-a", tmp_path / "projects" / "pkg-a"),
        "pkg-b": ("pkg-b", tmp_path / "projects" / "pkg-b"),
    }
    monkeypatch.setattr(af, "WORKSPACE_ROOT", tmp_path)
    result = af.packages_from_changed_files([
        "projects/pkg-a/a.py",
        "projects/pkg-b/b.py",
    ], workspace)
    assert result == {"pkg-a", "pkg-b"}
