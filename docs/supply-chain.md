# Supply-chain posture

What this fork actually does, end to end, to make sure the image you pull
from `ghcr.io/d10scot/dispatcharr` is the one this repo's CI actually built —
not something swapped in before or after. Modeled on
[`docker-ansible`](https://github.com/D10Scot/docker-ansible)'s
`docs/supply-chain.md`, trimmed and adjusted to what this repo actually needs
as a single-maintainer fork. See [CLAUDE.md](../CLAUDE.md) for the fuller
architectural context this file assumes.

Every claim below is either a workflow file you can read yourself or a
command you can run yourself — nothing here should require taking anyone's
word for it.

## Build integrity & reproducibility

- **Base images pinned by digest.** `docker/DispatcharrBase` pins both its
  `linuxserver/ffmpeg` base and both `astral-sh/uv` `COPY --from` references
  by `@sha256:...`. `docker/Dockerfile` pins `node:24` the same way, and its
  own dynamic base (this repo's own `:base` image) is resolved to a digest
  once per CI run — via a `BASE_IMAGE` build-arg — so every arch in a
  multi-arch build compiles against the exact same base layer instead of a
  tag that could move mid-build.
- **OS patches at build time.** Both stages of `docker/DispatcharrBase` run
  `apt-get upgrade -y` in the same layer as the package install, so a rebuild
  actually picks up patches rather than freezing on whatever was current
  when the base image digest was last bumped.
- **Multi-stage, toolchain stripped.** `docker/DispatcharrBase`'s builder
  stage has the compilers (gcc/g++/gfortran, build-essential); only the
  compiled artifacts (`/dispatcharrpy`, the legacy NumPy wheel, the `comskip`
  binary) are copied into the final stage.
- **Non-root at runtime, deliberately not via a static `USER`.** The
  container starts as root so `entrypoint.sh` can create a user at the
  PUID/PGID the operator supplies (the linuxserver.io self-hosting
  convention) and drop to it before running Django/Celery/nginx/etc. A
  static `USER` line would break that — covered by
  `docker/tests/test-puid-pgid.sh`.
- **Multi-arch built from identical inputs, pushed by digest.** `ci.yml`,
  `docker-build.yml`, `release.yml` and `base-image.yml` each build
  amd64/arm64 from the same pinned Dockerfile and the same resolved base
  digest, then `docker buildx imagetools create` merges the per-arch pushes
  into one multi-arch manifest referenced by digest.

## Dependency integrity

- **Hash-pinned lockfiles.** `uv.lock` is committed (it was previously
  gitignored — every base-image rebuild used to re-resolve from
  `pyproject.toml`'s loose constraints with no record of what actually got
  installed). `frontend/package-lock.json` and `e2e/package-lock.json` are
  committed npm lockfiles, which carry per-package integrity hashes by
  default.
- **Install enforces hash verification.** Every `uv sync` that installs from
  a committed checkout (`docker/DispatcharrBase`,
  `scripts/ci_bootstrap_backend.sh`, `debian_install.sh`) uses `--locked`,
  which fails the build if `uv.lock` and `pyproject.toml` disagree instead of
  silently re-resolving around it. The one deliberate exception is
  `docker/init/99-init-dev.sh` (the interactive dev container) — a developer
  editing `pyproject.toml` locally shouldn't have to regenerate the lockfile
  before their venv picks it up.
- **Lockfiles resolved inside the real target environment.** `uv.lock` is
  generated inside a `linux/amd64` `python:3.13` container, not on a
  developer's host — resolving on the wrong platform can silently pick the
  wrong-arch wheel. To regenerate after a `pyproject.toml` change:

  ```bash
  docker run --rm --platform linux/amd64 -v "$PWD:/work" -w /work \
    ghcr.io/astral-sh/uv:0.12.5-python3.13-trixie-slim uv lock
  ```

## Vulnerability scanning gate

`vuln-scan.yml` runs two independent layers, each with a documented tiered
policy (exact severities/fixability that block vs. just get logged — see the
workflow file's comments for the current line):

- **OSV-Scanner** reads `uv.lock`/`frontend/package-lock.json`/
  `e2e/package-lock.json` directly — no image build needed, runs on every
  relevant push/PR.
- **Trivy** and **Grype** scan the actually-published `:latest`/`:base`
  images against independent CVE databases.

All three scanners run as digest-pinned containers, not marketplace actions.
Image-scan jobs hold **no registry credentials of any kind** — they pull
public GHCR tags anonymously, so there's no publish capability in that
workflow for anything to abuse even if a scanner image were compromised.

## Signing & attestation

Every image `ci.yml`, `docker-build.yml`, `release.yml` and `base-image.yml`
push is, in a `sign-and-attest` job that is the *only* job in each of those
workflows holding `id-token`/`attestations` write:

1. Signed keylessly with [cosign](https://github.com/sigstore/cosign) via
   GitHub Actions OIDC (identity tied to a public Sigstore transparency log
   entry, not a long-lived private key).
2. Given an SPDX SBOM (via [syft](https://github.com/anchore/syft)),
   attached as an OCI attestation.
3. Given SLSA build provenance (source repo, commit SHA, build inputs),
   attached as an OCI attestation.

### Verifying an image yourself

```bash
# Signature — pin the identity to the actual workflow that published the tag
# you're checking. Replace <workflow> with whichever produced it:
#   ci.yml (pushed on every merge to main), release.yml (versioned
#   releases), base-image.yml (the :base image), or docker-build.yml.
cosign verify ghcr.io/d10scot/dispatcharr:latest \
  --certificate-identity-regexp='^https://github\.com/D10Scot/Dispatcharr/\.github/workflows/<workflow>\.yml@refs/.*$' \
  --certificate-oidc-issuer=https://token.actions.githubusercontent.com

# SBOM / build provenance attestations
gh attestation verify oci://ghcr.io/d10scot/dispatcharr:latest \
  --owner D10Scot
```

## Registry & distribution

- **Canonical registry:** `ghcr.io/d10scot/dispatcharr`. This fork does not
  publish to Docker Hub (a past workflow did; that push was removed — see
  git history on `docker-build.yml`/`release.yml`).
- **Tag strategy:** see the table in [SECURITY.md](../SECURITY.md#supported-tags)
  — `:latest`/`:base` are rolling and get rebuilt on every relevant push plus
  a weekly schedule; `:<version>` and `:<git-sha>` are immutable and are not
  patched after the fact.

## CI/CD workflow hardening

Every workflow: `uses:` pinned to a full commit SHA (version as a trailing
comment), `persist-credentials: false` on every `actions/checkout` except
`release.yml`'s tag-pushing step (documented inline with
`# zizmor: ignore[artipacked]`), least-privilege `permissions:` (workflow
level defaults to `contents: read`; anything broader is granted per-job,
narrowly), and `concurrency` groups so a stale run doesn't race a newer one.
Static analysis: [zizmor](https://docs.zizmor.sh/) (workflow security),
actionlint (workflow syntax), hadolint (Dockerfile anti-patterns), gitleaks
(committed secrets, full history), CodeQL's `actions` language pack, and a
weekly [OpenSSF Scorecard](https://github.com/ossf/scorecard) run — see
`lint.yml`, `codeql.yml`, `scorecard.yml`.

## Maintenance & governance

- `renovate.json`: dependency updates get a cooldown before Renovate opens a
  PR (3 days generally, 7 for GitHub Actions specifically, since those touch
  CI credentials); digest pins are enforced on every update, not just the
  initial one; patch/digest bumps automerge after cooldown + green CI,
  minor/major bumps and every Action bump get a human merge.
  **Renovate itself has to be installed on this repo (the GitHub App, or a
  self-hosted runner) for this file to do anything — committing it alone
  changes nothing.**
- `.github/CODEOWNERS`: `@D10Scot` owns everything. On a single-maintainer
  fork this doesn't add a second reviewer, but it's what makes GitHub's
  "require review from Code Owners" branch-protection rule enforceable, and
  it's a precondition for Renovate/anyone else with write access not being
  able to merge without a human involved.
- Scheduled rebuilds: `base-image.yml` (weekly) and `ci.yml` (weekly, a few
  hours later so it picks up the fresh base) rebuild even when nothing in
  this repo changed, so OS-level CVEs fixed upstream still reach published
  images on a bounded cadence.

## Vulnerability response

See [SECURITY.md](../SECURITY.md) for the private disclosure path, response
SLA, and supported-tag matrix.

## What's deliberately not done here

- **No self-hosted vulnerability-DB mirror.** Trivy verifies `trivy-db`'s
  cosign signature before use, and Grype checksums its DB listing, by
  default — both handle "don't trust a poisoned DB update" without this
  fork running its own mirror registry, which is a heavier operational
  commitment than a single-maintainer repo's threat model justifies right
  now. Revisit if that changes.
- **No OpenSSF Scorecard/CodeQL badge enforcement.** Both run and publish
  results; neither blocks a merge. They're signal, not gates, for now.
- **GitHub's native secret scanning / Dependabot are not enabled** at the
  repository-settings level (separate from this repo's own gitleaks/Renovate
  gates, which don't require any account-level toggle) — that's a setting
  only the repo owner can flip, not something this file changes.
