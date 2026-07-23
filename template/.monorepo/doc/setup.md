# First-time release setup

This is a one-time checklist to make the release pipeline
([release.yml](../.github/workflows/release.yml) and
[release-native.yml](../.github/workflows/release-native.yml)) work for a repository.
See [release-strategy.md](release-strategy.md) for the design rationale behind each step.

Everything here is manual: it involves creating a GitHub App, configuring PyPI publishing (Trusted
Publishing or a token), and storing secrets. None of it can be safely committed to the repository,
and the PyPI-side steps have no public API to automate.

## Prerequisites

- Admin access to the GitHub repository (to create environments and secrets).
- An account on [pypi.org](https://pypi.org) and [test.pypi.org](https://test.pypi.org) with
  permission to publish the projects.
- Optional: the [`gh`](https://cli.github.com/) CLI, authenticated (`gh auth login`), if you prefer
  the command line over the GitHub UI. Replace `OWNER/REPO` with your repository in every command.

## 1. Create the release GitHub App

`release.yml` mints a short-lived installation token so that the git tags it pushes are seen as a
real user push and trigger `release-native.yml`. Tags pushed with the built-in `GITHUB_TOKEN` are
deliberately ignored by GitHub's `push: tags` trigger, so this App is **required** for native
projects to release automatically.

1. Go to **GitHub → Settings → Developer settings → GitHub Apps → New GitHub App**.
2. Scope it to this repository only, grant **Repository permissions: Contents = Read & Write**, and
   disable everything else.
3. After creation, note the numeric **App ID** shown on the app's settings page.
4. Generate a private key (bottom of the app settings page) and download the `.pem` file.
5. **Install** the app on this repository.

Store the credentials as **repository-level** secrets (not environment secrets — they are needed
before the workflow selects an environment):

Via the UI: **Settings → Secrets and variables → Actions → New repository secret**.

Via `gh`:

```bash
gh secret set RELEASE_APP_ID --repo OWNER/REPO --body "<numeric App ID>"
gh secret set RELEASE_APP_PRIVATE_KEY --repo OWNER/REPO < path/to/private-key.pem
```

| Secret | Value |
|---|---|
| `RELEASE_APP_ID` | The numeric App ID |
| `RELEASE_APP_PRIVATE_KEY` | The full contents of the downloaded `.pem` file |

Without these secrets, tags pushed by `release.yml` will not trigger `release-native.yml` (no error,
silent skip).

## 2. Configure PyPI Trusted Publishing (recommended)

The recommended way to authenticate is OIDC
[Trusted Publishing](https://docs.pypi.org/trusted-publishers/): PyPI accepts a short-lived,
cryptographically verifiable token that GitHub Actions mints at run time, so there is no long-lived
credential to store, leak, or rotate. When no `UV_PUBLISH_TOKEN` secret is present in the active
environment, the workflow automatically authenticates via OIDC.

Configure a Trusted Publisher for each project on each index. On [pypi.org](https://pypi.org) and
[test.pypi.org](https://test.pypi.org), go to **Account → Publishing → Add a new pending publisher**
and fill in:

| Field | Value |
|---|---|
| PyPI Project Name | The distribution name (e.g. `dissect.util`) |
| Owner | `OWNER` |
| Repository name | `REPO` |
| Workflow name | `release.yml` |
| Environment name | `production_publish` (on the production index) / `test_publish` (on the test index) |


> **Fallback — account-scoped API token.** If you prefer not to register a Trusted Publisher per
> project, mint a single account-scoped API token per index instead. One token covers every project
> under the account, so the setup is one token per index regardless of how many projects exist:
>
> - **PyPI**: [pypi.org](https://pypi.org) → Account Settings → API tokens → Add API token.
> - **TestPyPI**: [test.pypi.org](https://test.pypi.org) → Account Settings → API tokens → Add API token.
>
> Store the token as described in step 3. Whenever `UV_PUBLISH_TOKEN` is set in the environment, the
> workflow uses it in preference to OIDC.

## 3. Create the publish environments

The workflow's `target` input is a **release role** (`production` or `test`), not a raw index name.
Each role maps to a GitHub environment named `<role>_publish` and, via `[tool.monorepo.release]` in
the root `pyproject.toml`, to a `[[tool.uv.index]]` name that receives the artifacts:

| Role | Environment | Default index (`[tool.monorepo.release]`) |
|---|---|---|
| `production` | `production_publish` | `production-index` (`pypi`) |
| `test` | `test_publish` | `test-index` (`testpypi`) |

Both environments are **required regardless of which authentication mode you use**: the environment
name is part of the Trusted Publisher configuration in step 2, and it also scopes any secrets and
gates production releases.

Via the UI: **Settings → Environments → New environment** (`production_publish` and `test_publish`).

Via `gh`:

```bash
gh api repos/OWNER/REPO/environments/production_publish -X PUT
gh api repos/OWNER/REPO/environments/test_publish -X PUT
```

**Trusted Publishing (recommended):** no further secrets are needed — leave `UV_PUBLISH_TOKEN` unset
and the workflow authenticates via OIDC.

**Token fallback:** if you minted account-scoped tokens in step 2, store the matching token as a
`UV_PUBLISH_TOKEN` secret in each environment. Per-environment scoping ensures the test-index token
can never be used to publish to the production index and vice versa.

```bash
gh secret set UV_PUBLISH_TOKEN --repo OWNER/REPO --env production_publish --body "<production token>"
gh secret set UV_PUBLISH_TOKEN --repo OWNER/REPO --env test_publish --body "<test token>"
```

| Environment | Secret | Value |
|---|---|---|
| `production_publish` | `UV_PUBLISH_TOKEN` | Production-index account-scoped API token (token fallback only) |
| `test_publish` | `UV_PUBLISH_TOKEN` | Test-index account-scoped API token (token fallback only) |

## 4. Optional: require manual approval for production

To add an approval gate before production releases, configure **Required reviewers** on the
`production_publish` environment (**Settings → Environments → `production_publish` → Required
reviewers**). Releases to `test_publish` remain ungated for fast dry runs.

## 5. Verify

1. Confirm the release GitHub App secrets exist:
   ```bash
   gh secret list --repo OWNER/REPO
   ```
   If you are using the token fallback, also confirm the per-environment token is present:
   ```bash
   gh secret list --repo OWNER/REPO --env production_publish
   gh secret list --repo OWNER/REPO --env test_publish
   ```
   With Trusted Publishing these environment listings are empty — that is expected.
2. Run a dry run: **Actions → Release → Run workflow** with `target = test`. The run should
   publish to the test index **without** creating a tag (test releases are not tagged). If it
   authenticated via OIDC, confirm the test-index Trusted Publisher shows a recent successful publish.
3. For a native project, run a **production** release and confirm the tag push automatically starts
   `release-native.yml`.
