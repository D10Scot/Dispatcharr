# Security Policy

This is a personal fork of [Dispatcharr](https://github.com/Dispatcharr/Dispatcharr)
maintained by [@D10Scot](https://github.com/D10Scot). It tracks upstream's `dev`
branch on `main` and adds fork-specific work; see [CLAUDE.md](CLAUDE.md) for the
current focus.

## Reporting a vulnerability

Please **do not** open a public issue for a security vulnerability — that hands
attackers a head start before a fix exists.

Instead, use
[GitHub's private vulnerability reporting](https://github.com/D10Scot/Dispatcharr/security/advisories/new)
for this repository. That opens a private advisory only the maintainer can see
until a fix is ready.

If the vulnerability is in upstream Dispatcharr itself rather than something
this fork introduced, please report it to
[Dispatcharr/Dispatcharr](https://github.com/Dispatcharr/Dispatcharr/security)
instead, so the fix reaches everyone running upstream, not just this fork.

**Response SLA:** best-effort acknowledgment within 7 days. This is a
single-maintainer fork, not a funded security team — there is no guaranteed
turnaround beyond that.

## Supported tags

| Tag pattern | Rebuilt | Meaning |
| --- | --- | --- |
| `:latest` | Every push to `main`, plus weekly (`ci.yml` schedule) | Rolling — always the current `main`. Gets every base-image OS patch and dependency fix as soon as it's built. |
| `:base` | Every push touching `docker/DispatcharrBase`/`pyproject.toml`/`uv.lock`, plus weekly (`base-image.yml` schedule) | Rolling base image. Not something end users run directly — consumed by `:latest` and versioned release builds. |
| `:<version>` (e.g. `:0.30.0`) | Once, at release time (`release.yml`) | Immutable. **Does not receive patches after release** — pin one of these only if you also have a plan to re-pin on the next release. |
| `:<git-sha>` | Once, per commit to `main` (`ci.yml`) | Immutable, for pinning to an exact build. Same caveat as version tags. |

If you need a tag that keeps receiving security patches without you doing
anything, use `:latest`. If you need reproducibility, use a `:<version>` or
`:<git-sha>` tag and track new releases yourself.

## Verifying an image

Every image this fork publishes to `ghcr.io/d10scot/dispatcharr` is signed
keylessly with [cosign](https://github.com/sigstore/cosign) via GitHub Actions
OIDC, and carries an SBOM and SLSA build provenance attestation. See
[docs/supply-chain.md](docs/supply-chain.md) for the exact verification
commands and what CI identity they're pinned to.

## Known, deliberate deviations

A short list of things a scanner might flag that are already known and
intentional — see [CLAUDE.md](CLAUDE.md) for the full, current list (it's kept
more up to date than this file):

- The container starts as root so `entrypoint.sh` can do PUID/PGID privilege
  drop before running the app — a static non-root `USER` would break that.
- `docker/DispatcharrBase` doesn't pin apt package versions — that would
  defeat the point of `apt-get upgrade` running at every build.
