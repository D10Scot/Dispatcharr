# 11. The Go relay takes the OpenTelemetry SDK, and keeps the driver ban

Date: 2026-10-31

## Status

Accepted. Supersedes, in part, the Phase 2 spec's rule "Third-party Go
dependencies: none"
(`docs/superpowers/specs/2026-09-09-phase2-go-relay-design.md:1746`) and the
empty-`go.sum` half of `scripts/check_go_stdlib_only.sh`. The other half of
that script, the ban on linking a Redis client, is kept and widened to
Postgres drivers. [ADR 0006](0006-the-go-relay-keeps-its-state-in-memory-and-the-cutover-is-hard.md)
and [ADR 0007](0007-phase-3-is-closed-because-phase-2-met-its-charter.md) are
unchanged. The design that uses this decision is
`docs/superpowers/specs/2026-10-31-observability-design.md`.

## Context

The Go relay has been standard-library only since stage 2c-1. The Phase 2
spec made that a rule to defend rather than an accident. Its reason was
supply-chain surface: every module added is a module Trivy, Grype,
OSV-Scanner and Scorecard must then cover, and the relay's job (copy bytes,
parse ffmpeg stderr, speak two small JSON contracts) needed nothing the
standard library lacks. Two checks hold the rule. `go list -m all` must print
the main module alone, and `relay/go.sum` must be empty. A third check in the
same script refuses any linked package whose import path names Redis.

That reason still holds for the relay's job. It does not hold for the next
piece of work. The owner's test box is CPU-bound on transcoding, and the next
programme after this one may shard channels across several relays. Neither
can be judged without numbers: CPU seconds and resident memory per ffmpeg
process, labelled by channel and by what the process is for; channels,
clients and bytes; failovers by trigger; and traces of a tune from the
authorize hop to the first byte. The cluster it will run in already collects
OpenTelemetry.

The relay could produce all of that in the standard library. It would need
an OTLP encoder (protobuf over HTTP), a Prometheus text encoder, a trace
context implementation, span batching with retry and backoff, and a log
record pipeline. That is a second implementation of a specification the
OpenTelemetry project already maintains, with its own conformance and
security fixes. A hand-written protobuf encoder is a larger and less
reviewed surface than the upstream one, so the stdlib rule would no longer be
buying what it was written to buy.

The owner was asked on 2026-10-31 whether the driver ban should go with the
stdlib rule, since a dependency allowlist would already refuse a driver. The
ruling is to keep it. ADR 0006 keeps the relay's state in memory, and ADR
0007 closed Phase 3 on the finding that what Redis still holds on the
streaming surfaces is coordination, not data path. A relay that can open a
database or a Redis connection would undo both, and the ban states that
boundary in a check rather than leaving it to review.

## Decision

**The relay may depend on the official OpenTelemetry Go SDK and on the
modules it needs, named in a committed allowlist. Everything else stays
banned.**

1. **A direct-dependency allowlist replaces the empty-`go.sum` check.**
   `relay/go.allowed-deps` names, one per line, every module path the relay's
   `go.mod` may `require` directly. A new script, `scripts/check_go_deps.sh`,
   replaces `scripts/check_go_stdlib_only.sh`. It compares the set of direct
   requirements (`go list -m -f '{{if not .Indirect}}{{.Path}}{{end}}' all`,
   minus the main module) with the allowlist and fails on any difference in
   either direction. Indirect modules are not allowlisted one by one: they
   follow from the direct ones, and govulncheck and the scanners below cover
   them. Adding a direct dependency is therefore a reviewed edit to a named
   file, not a side effect of an import. The script also fails when
   `go mod tidy -diff` reports a difference, the state between adding an
   import and tidying that the old script's `go.sum` check existed to catch.
2. **The driver ban is kept and widened.** The same script fails when
   `go list -deps .` from `relay/` (the packages the shipped binary links)
   contains `database/sql` itself, any import path with a `redis` segment, or
   any path under `github.com/lib/pq`, `github.com/jackc/`,
   `github.com/go-sql-driver/` or `github.com/mattn/go-sqlite3`. It checks the
   linked set, not the module graph, because the invariant is about what the
   binary can do. `database/sql` is in the standard library, so the old script
   could not have seen it. The ban is on `database/sql` and not on its
   `driver` subpackage, deliberately: `github.com/google/uuid`, which the OTel
   SDK links, imports `database/sql/driver` for its `Value` method, and that
   package is an interface with no connection in it (measured on a prototype
   module, 2026-10-31).
3. **OpenTelemetry stays in one package.** Only `relay/telemetry` and the
   `main` package may import `go.opentelemetry.io/...` or
   `github.com/prometheus/...`. A golangci-lint `depguard` rule enforces it,
   so the rest of the relay keeps its existing shape and a reviewer reads one
   package to see what the dependency touches.
4. **govulncheck blocks.** A new `go-tests.yml` job runs govulncheck over the
   module and fails on any vulnerability in code the relay calls, the Go
   standard library included. OSV-Scanner reads `relay/go.mod` beside the
   Python and npm lockfiles, and Trivy and Grype scan `relay/` as a directory
   on every pull request that changes `relay/go.mod` or `relay/go.sum` (the
   workflow's path filter), on every push to `main` that does, and nightly.
   A pull request that edits only Go source does not trigger them, because
   source alone cannot change the module set; govulncheck runs on every
   relay change. Until now the scanners saw the relay only inside the
   published image, after merge.
5. **Renovate holds Go modules for seven days and never automerges them.**
   The OpenTelemetry modules release together and are grouped into one update.

## Consequences

- The relay's `go.mod` gains about a dozen direct requirements and `go.sum`
  becomes non-empty. Statements elsewhere that "the relay has no third-party
  dependency" become historical, including ADR 0007's evidence row and the
  Phase 2 spec's "Met" row (`2026-09-09-phase2-go-relay-design.md:4798`).
  Both are records and are not edited. CLAUDE.md is corrected in the PR that
  replaces the script.
- The binary links the OTLP protobuf stack and the Prometheus client library.
  Measured on a prototype module linking exactly the allowlisted modules at
  their 2026-10-31 versions: 12 direct requirements, 116 modules in the
  graph, 34 third-party modules linked, and **`google.golang.org/grpc` among
  them**, because the HTTP exporters import the OTLP collector packages,
  whose generated code carries the gRPC service stubs. A program linking only
  those modules is 24.8 MB for linux/amd64, against the relay's 12.6 MB at
  the seed SHA. Transitive modules are not allowlisted individually, so a
  minor bump that adds one does not fail the allowlist check; govulncheck and
  the scanners are what see them.
- `relay/internal/credlint` type-checks third-party packages for the first
  time. Its importer resolves the standard library from gc export data and
  module packages from source, and it cannot resolve a module-cache package:
  measured on a scratch copy of the module with one OTel import, it exits 2
  with `can't find import: "go.opentelemetry.io/otel"`. Giving the gc
  importer a lookup built from `go list -deps -export` fixes it (also
  measured). That change lands with the allowlist script, before any
  dependency arrives.
- `scripts/coverage_relay_go.sh`'s denominator is unchanged in kind: it
  already filters `go list -deps .` to the module's own import paths, so
  third-party packages never enter it. `gomod=` in the floor changes when
  `go.mod` does, which is a shape-only re-baseline.
- The relay can export its log records over OTLP. Structured log fields are
  exported only through a typed allowlist. Log **bodies** are the free text
  the relay already writes to stderr. They are exported with best-effort
  scrubbing and are **no stronger than stdout**, by owner ruling R-Q17
  (2026-11-01). Their safety rests on credlint at the call site and on a
  future structured-logging rewrite, which is out of scope.
- The relay can now fail a build because an upstream module has a published
  vulnerability. That is the point of govulncheck blocking, and it is the
  same posture the Python and npm lockfiles already have.

## What stays banned, and why

- **Postgres drivers and `database/sql`.** The relay asks Django for every
  row it needs, over `next-source` and the authorize hop. ADR 0005 put
  authorization in Django; Phase 2 Gate 1 made "the relay performs no ORM
  read" structural by linking no driver. Linking one would turn that back
  into a convention.
- **Redis clients.** ADR 0006 moved every piece of live channel state into
  process memory and ADR 0007 closed Phase 3 on that basis. A Redis client
  in the relay is the first step back to the leased, unfenced ownership that
  stage 2d-4 deleted.
- **Any module not on the allowlist.** That includes OpenTelemetry
  contributions beyond the ones the observability spec names (no `otelhttp`,
  whose server spans record the request path, and the XC routes carry a
  password in the path) and the gRPC exporters. gRPC is linked transitively
  either way; a gRPC exporter would add a second transport and a long-lived
  HTTP/2 connection for nothing the HTTP exporters do not already do.
