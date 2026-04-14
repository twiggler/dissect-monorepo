# Decision: Do Not Integrate dissect-docs into the Monorepo

### Background

[dissect-docs](https://github.com/fox-it/dissect-docs) is the Sphinx-based documentation
site that covers the entire Dissect ecosystem. It currently lives as a standalone
repository and uses git submodules to pull in all documented packages at build time.
Migrating it into the monorepo was considered as part of the monorepo migration project.
After analysis that integration was ruled out. This document explains why.

---

### Reason 1: Conceptual mismatch — dissect-docs covers projects outside the monorepo

The monorepo contains `dissect.*` packages. However, dissect-docs also documents two
projects that are outside the `dissect.*` namespace and have no plans to be moved into
the monorepo: **acquire** and **flow.record**. Both are maintained in their own
repositories and are independent enough that including them in the monorepo would
not be justified.

This raises a secondary question: why are projects that are not part of the `dissect.*`
namespace documented in the dissect documentation at all? The answer is historical —
`acquire` and `flow.record` are closely related tooling in the same ecosystem and have
always been documented together. That coupling is a reason to keep dissect-docs as a
standalone repository, not to import three unrelated projects into the monorepo.

---

### Reason 2: Read the Docs is incompatible with the monorepo's release model

dissect-docs currently uses [Read the Docs](https://readthedocs.org/) (RTD) for hosting.
RTD's version management is built around a set of implicit rules that do not compose
well with how the monorepo works:

**`latest` tracks the default branch continuously.** RTD rebuilds the `latest` version
on every push to `master`. The monorepo uses trunk-based development — every pull
request is merged directly to `master`. This means documentation would be rebuilt and
updated on every PR merge, including ones that have nothing to do with documentation
or with any public-facing change. There is no mechanism to suppress this without
moving away from trunk-based development.

**`stable` relies on semver tag heuristics that break on namespaced tags.** RTD
automatically promotes the most recent tag that looks like a version number to the
`stable` alias. The monorepo uses namespaced tags of the form `dissect.target/3.12.0`
to associate each release with its package. RTD's heuristic does not recognise this
scheme, so `stable` would either point to the wrong thing or not be updated at all.

**The monorepo generates hundreds of tags.** RTD discovers versions by scanning all
tags in the repository. With 30+ packages each receiving independent releases, the
RTD version list would accumulate hundreds of entries (e.g. `dissect.target/3.12.0`,
`dissect.cstruct/4.1.0`, ...) — none of which correspond to a meaningful documentation
version.

**RTD's automation rule system does not yet support custom `latest`/`stable` logic.**
A [long-standing open issue](https://github.com/readthedocs/readthedocs.org/issues/5319)
(open since 2019, still in "Planned" status as of 2026) tracks the ability to configure
custom rules for when `latest` and `stable` are updated. Until that is resolved, there
is no supported way to make RTD behave correctly with the monorepo's tag scheme.

---

### Reason 3: GitHub Pages resolves these problems cleanly

The documentation build does not need to be tied to RTD. Building with a GitHub Actions
workflow and deploying to GitHub Pages gives full control over when documentation is
published, with no implicit version logic:

- The workflow is triggered explicitly — on a `docs/*` tag, on a manual `workflow_dispatch`,
  or on merges to a dedicated documentation branch. It does not fire on every PR merge.
- Versioning is explicit: the tag or ref that triggered the build is used as the release
  label in `conf.py`. No heuristics, no guessing.
- GitHub Pages supports custom domains identically to RTD.
- All other RTD features (search, PR previews) can be replicated with standard Actions
  tooling.
- `acquire` and `flow.record` no longer need to be git submodules of dissect-docs.
  A CI build step can clone them on demand, making the dependency ephemeral and
  explicit only where it is actually used. This reduces the structural coupling that
  submodules introduce (`.gitmodules` entries, mandatory clone depth considerations,
  submodule initialisation commands in every tooling script).

This approach should be evaluated as part of the dissect-docs repository's own
maintenance work, independently of the monorepo.

---

### Reason 4: dissect-docs needs to be updated to reference the monorepo

After the monorepo migration is complete, the individual `dissect.*` source repositories
will stop being the canonical location for each package's source code. The dissect-docs
repository currently includes each package as a git submodule pointing to the individual
repositories. Those submodules will need to be replaced with a single submodule pointing
to the monorepo, and the `conf.py` path configuration will need to be updated to reflect
the monorepo's `projects/<pkg>/src/` layout.

That work belongs in the dissect-docs repository, not the monorepo, and is tracked
separately.
