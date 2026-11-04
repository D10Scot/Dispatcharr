# Observability: OpenTelemetry metrics, traces and logs

> **For agentic workers:** implement this plan task by task with subagents, per CLAUDE.md
> § Delegation for phase work. Each PR below goes through `implement-review-escalate`; each
> merges through `pr-merge-gate`. Reviews are on `fable` from round one: every PR here either
> moves a credential boundary or adds an exporter that could carry one.

**Goal.** Make the deployment measurable before anyone designs channel sharding. The owner's test
box is CPU-bound on transcoding, and the next programme may split channels across several relays.
Neither question can be answered from today's tree, which has no metrics and no structured logs
(CLAUDE.md § Known defects, "Operationally"). This spec adds three signals, in both languages:

- **Metrics.** CPU seconds and resident memory for every ffmpeg the relay spawns, labelled by
  channel, by what the process is for and by Output Profile. Also channels, clients by format,
  bytes sent, failovers by trigger, HLS sessions, rewind disk use, provider slots, Django
  request rate, errors and duration, Celery task duration and Celery queue depth.
- **Traces.** One trace per tune, from nginx's authorize hop through `next-source` to the first
  byte a viewer receives, with failovers and operator switches as short spans linked to it.
- **Structured logs.** JSON on stdout when asked for, carrying the trace and span ids, and the
  same records over OTLP.

**What this spec does not do.** It does not design sharding, add dashboards, alerts or a Helm
chart, rewrite any existing log call, adopt structlog, or change any live-path behaviour a
viewer can observe. It is a standalone spec and an ADR, not a numbered phase
(owner ruling, 2026-10-31).

**Seed SHA:** `149678aa3accd82997d523e9747305ccd4c52a46` (`origin/main`, "docs(spec): rename
Dispatcharr to Mino, and stop tracking upstream (#608)"). Every `file:line` below was re-grepped
at this SHA. Line numbers drift; identifiers are the durable part of each citation.

**Authorities.** The owner's rulings of 2026-10-31 (the grilling recorded in the orchestrator's
`rulings.md`; summarised as R1–R14 below and not reopened here). CLAUDE.md, `CONTEXT.md`, ADRs
0005, 0006, 0007, 0009 and 0010, the Phase 2 spec
(`docs/superpowers/specs/2026-09-09-phase2-go-relay-design.md`), the Phase 4 spec
(`docs/superpowers/specs/2026-09-27-phase4-apple-native-live-design.md`, D20 for the coverage
rules), the Mino rename spec (`docs/superpowers/specs/2026-10-28-mino-rename-design.md`) and
`docs/supply-chain.md`. The new ADR is
`docs/adr/0011-the-go-relay-takes-the-opentelemetry-sdk-and-keeps-the-driver-ban.md`.

## The rulings this spec implements

| # | Ruling (2026-10-31) | Where |
|---|---|---|
| R1 | Metrics, traces and structured logs, all three in this pass | D1 |
| R2 | The Go relay takes the official OTel Go SDK; a new ADR supersedes the stdlib-only rule; a direct-dependency allowlist replaces the empty-`go.sum` check; the Postgres/Redis driver ban is **kept**; govulncheck blocks; `go.sum` goes into Trivy, Grype and OSV; Renovate cooldown | D2, D3, ADR 0011 |
| R3 | Relay: OTLP push for all three signals, plus `/metrics` through the OTel Prometheus exporter. Django, Celery and Daphne push OTLP only, no multiprocess Prometheus | D4, D5 |
| R4 | `/metrics` is never routed by nginx (pinned by a test), carries no auth, and a NetworkPolicy is documented | D6 |
| R5 | Labels: numeric `channel_id`, `kind` (`source`/`output`/`fmp4`/`hls`), `profile_id`; never the channel UUID, never a URL | D7 |
| R6 | Logging: stdlib `logging` with a JSON formatter carrying trace and span ids, plus the OTel `LoggingHandler`; relay slog JSON handler; `MINO_LOG_FORMAT=json\|text`; no structlog; no rewrite of existing log calls | D8 |
| R7 | Redaction at every exporter boundary: span and log processors in both languages, URL userinfo and query stripped, credlint and `scripts/check_credential_logging.py` extended to the new sinks, one leak test per signal with an in-memory exporter | D9 |
| R8 | Python: programmatic post-fork init (uWSGI postfork, Celery `worker_process_init`, Daphne startup), five instrumentations (django, celery, psycopg, redis, requests), never `opentelemetry-instrument`, one gevent context-propagation test | D10 |
| R9 | Tune trace = authorize → next-source → first byte; failover and switch as short linked spans; W3C `traceparent` from relay to Django; parent-based ratio sampler | D11 |
| R10 | OTLP is off unless `OTEL_EXPORTER_OTLP_ENDPOINT` is set; the relay's `/metrics` is always on | D12 |
| R11 | Metric catalogue frozen in this spec (the list in the Goal above) | D14, § Metric catalogue |
| R12 | Prefix `mino_`; `service.name` is `mino-relay`, `mino-api` or `mino-worker` | D13 |
| R13 | Standalone spec and ADR, not a numbered phase | header |
| R14 | Deployment scope: a docs page and an example Collector config only; no Helm, no dashboards, no alerts | D15 |
| R-Q17 | (2026-11-01, after round 2) OTLP-exported log **bodies**, the free text of existing log calls, are held to the same standard as stdout: best-effort scrubbing, stated as no stronger than stdout. Allow-by-construction applies to everything new: span attributes and status, metric attributes, the resource, `/metrics`, and structured log **fields** | D9 |
| R-Q18 | (2026-11-01, relayed 2026-11-04) `OTEL_RESOURCE_ATTRIBUTES` is trusted operator configuration, in the same class as `OTEL_EXPORTER_OTLP_HEADERS`. It passes through to the OTLP resource as configured, and our code adds only its fixed attributes. `/metrics` keeps `WithoutTargetInfo` and `WithoutScopeInfo` | D13 |

## Global constraints

1. **No viewer-observable change.** Nothing here changes a byte a viewer receives, a status
   code, a header a client sees, a redirect or a timing. `docs/relay-parity-matrix.md` gains no
   row and loses none. The one new route, the relay's `GET /metrics`, is on the relay's own port
   and never routed by nginx (D6).
2. **Off by default.** With `OTEL_EXPORTER_OTLP_ENDPOINT` unset (the default in every compose
   file at the seed SHA), no OTel SDK provider is installed in any Python process, no exporter
   thread starts and no outbound connection is opened. The relay serves `/metrics` and does
   nothing else new. With `MINO_LOG_FORMAT` unset, every log line is byte-identical to today.
3. **Allow by construction for everything new** (R-Q17). Every exporter in both languages sits
   behind a boundary that the leak tests drive (D9). A key that is not allowlisted, or a value
   whose type or shape fails its rule, is dropped. Nothing new depends on scrubbing.
4. **No channel UUID, no URL and no credential in any label, attribute, span name, status or
   structured log field an exporter sends.** The OTLP resource carries what the operator puts in
   `OTEL_RESOURCE_ATTRIBUTES`, which is trusted configuration (R-Q18), and `/metrics` carries no
   resource. A channel UUID is a capability
   (CLAUDE.md § Auth), and a provider URL is a credential (CLAUDE.md § Known defects). Log
   **bodies** are the one exception: they are scrubbed best effort, no stronger than stdout
   today (R-Q17).
5. **OTel code is confined.** In Go, only `relay/telemetry` and `package main` import
   `go.opentelemetry.io/...` or `github.com/prometheus/...` (depguard, D2). In Python, only
   `dispatcharr/observability/` imports `opentelemetry.sdk` or an exporter; other modules use
   `opentelemetry.trace`/`opentelemetry.metrics` API calls only where this spec names them.
6. **Import-time safety (the boot trap).** `dispatcharr/observability/` imports nothing from
   `apps.*` at module level. Anything it needs from `apps.proxy.internal_auth` or
   `apps.m3u.connection_pool` is imported inside the function that uses it (CLAUDE.md
   § Structural constraints, the `apps/channels/models.py:6` trap).
7. **Subprocess and gevent rules hold.** No new `Popen`, no new `threading.Thread` under
   `apps/proxy/`. The OTel SDK's own worker threads become greenlets under uWSGI's early
   monkey-patch; D10 says what that means and the gevent test pins it.
8. **Every test change is listed** with before and after; additions are listed as additions.
   Every fix and every new guard carries a break-check: a named wrong edit, the red message
   that names the mechanism, revert.
9. **Pins are resolved by a tool at implementation time** (`go get`, `uv lock`, `gh api`), never
   typed from this spec. The versions in § Versions checked are what the planner read on
   2026-10-31; they are floors for the implementer's own resolution, not pins.
10. **Every PR corrects the CLAUDE.md facts it changes, in the same PR, and no others** (the
    rename spec's rule, adopted here).

## Decisions

### D1 — Three signals, measured where they happen (R1)

All three signals land in this pass, in the PR order of § PR sequence. The point of the pass is
the CPU question, so the relay's process metrics (catalogue rows M8, M9) land in the first PR
that links telemetry into the binary (O4), before any Python work.

### D2 — The relay takes the OTel Go SDK behind a direct-dependency allowlist (R2, ADR 0011)

`scripts/check_go_stdlib_only.sh` is deleted and replaced by `scripts/check_go_deps.sh`, which
runs from the module root and fails on any of:

1. **Direct-dependency drift.** The set
   `go list -m -f '{{if not .Indirect}}{{.Path}}{{end}}' all`, minus the main module, differs in
   either direction from the non-comment lines of `relay/go.allowed-deps`. The script prints the
   added and removed paths. The main module's path is read with `go list -m`, never hard-coded,
   so rename PR G1 (the Go module path) does not have to edit this script.
2. **A banned linked package.** `go list -deps .` (the packages the shipped binary links, the
   same question `scripts/coverage_relay_go.sh:101` asks) contains `database/sql` itself; any
   path with a segment matching `(^|/)redis` (case-insensitive, as
   `scripts/check_go_stdlib_only.sh:51` does today); or any path with prefix
   `github.com/lib/pq`, `github.com/jackc/`, `github.com/go-sql-driver/` or
   `github.com/mattn/go-sqlite3`. The script prints each offender. `database/sql/driver` is
   deliberately not banned: `github.com/google/uuid`, which the OTel SDK links, imports it for a
   `Value` method, and it is an interface package that opens nothing (measured, § Go modules).
3. **A dirty tidy.** `go mod tidy -diff` reports a difference (an import added without a tidy,
   the state the old script's `go.sum` check existed to catch).

`relay/go.allowed-deps` is committed with a header comment naming ADR 0011 and this spec. O1
ships it empty, so O1 proves the check against a module with no dependencies; O2 adds the
entries in § Go modules. Appendix A.2 carries the script and the file; the planner ran the
script against the seed tree (exit 0) and against a scratch copy of the module through six
cases: an unlisted direct requirement, a listed one, a stale allowlist line, a linked
`database/sql`, a linked package named for Redis, and an untidy `go.mod` (exits 1, 0, 1, 1, 1, 1,
each printing the offender).

**Confinement.** `.golangci.yml` gains a `depguard` rule set (golangci-lint v2 schema):

- `otel-confined`: files `$all` except `**/relay/telemetry/**` and `**/relay/main.go`; deny
  `go.opentelemetry.io` and `github.com/prometheus`, message "OTel stays in relay/telemetry
  (observability spec D2)".
- `no-drivers`: files `$all`; deny `database/sql`, `github.com/lib/pq`, `github.com/jackc`,
  `github.com/go-sql-driver`, `github.com/redis`, `github.com/gomodule/redigo`, message "ADR
  0011: the relay links no database or Redis driver".

depguard sees the module's own imports; `check_go_deps.sh` sees the linked set. Both are kept
because each catches what the other cannot: depguard names the file and line, the script catches a
driver arriving transitively.

**credlint must learn to import third-party packages.** `relay/internal/credlint/check.go:167-169`
builds its importer with `importer.ForCompiler(fset, "gc", nil)` and resolves everything outside
the module through it (`:174-179`). The gc importer with a nil lookup finds standard-library
export data and cannot find a module-cache package. **Measured**: on a scratch copy of the module with one file importing
`go.opentelemetry.io/otel` (v1.47.0), `go run ./internal/credlint ./...` exits 2 with
`could not import go.opentelemetry.io/otel (can't find import …)`. O1 changes `NewChecker` to
pass `importer.ForCompiler(fset, "gc", lookup)` a lookup built from
`go list -deps -export -f '{{.ImportPath}}\t{{.Export}}' ./...` run in the module directory
`ListPackages` already uses. The planner prototyped exactly that change (stdlib only, about
fifteen lines); the scratch module then type-checked and the checker reported the probe's
`span.RecordError(errors.New("boom"))` as a finding. O1 lands it before any dependency is in
`go.mod`, so O2 does not discover it.

**credlint's new sinks.** `relay/internal/credlint/check.go:75`'s `Sinks` map gains
`(go.opentelemetry.io/otel/trace.Span).RecordError` and `go.opentelemetry.io/otel.Handle`, the two
OTel calls that take an `error`. The interface-method spelling was measured: with it in `Sinks`,
the prototype above reported
`(go.opentelemetry.io/otel/trace.Span).RecordError argument 0 has type error and is not redacted`.
O1 pins both with `check_test.go` cases against stub packages of the same import paths
(`CheckSources` at `:183` takes source text, so the test needs no real dependency). Log calls through the
`otelslog` bridge are `log/slog` calls and are already sinks.

### D3 — Supply chain for the Go modules (R2)

- **govulncheck, blocking.** A new `govulncheck` job in `.github/workflows/go-tests.yml`, in
  `Go result`'s `needs`, runs `go run golang.org/x/vuln/cmd/govulncheck@${GOVULNCHECK_VERSION}
  ./...` from `relay/` on the same `setup-go` as the lint job. Exit 3 (a vulnerability in called
  code) fails the job; govulncheck reports standard-library vulnerabilities too, so a Go
  toolchain with a called CVE fails until `relay/go.mod`'s `go` line moves. The version is a job
  `env:` value, `v1.9.0` in Appendix A.2 (the latest `go list -m -versions golang.org/x/vuln`
  printed on 2026-10-31; the implementer re-resolves it), and `go run pkg@version` is verified
  against the Go checksum database; Renovate keeps it fresh through the custom manager below.
- **OSV-Scanner** reads `relay/go.mod` (`--lockfile=/repo/relay/go.mod`, beside the three
  lockfiles at `.github/workflows/vuln-scan.yml:106` and `:114`), and both path filters
  (`:30-35`, `:45-50`) gain `relay/go.mod` and `relay/go.sum`. OSV-Scanner v2 recognises a
  `go.mod` lockfile by name; that the pinned v2.5.1 image does so was not run locally, and O1's
  first CI run is the check (its informational step prints the scanned sources).
- **Trivy and Grype on the source tree.** A new `go-modules` job in `vuln-scan.yml` mounts
  `relay/` read-only and runs Trivy
  `fs --severity CRITICAL,HIGH --ignore-unfixed --exit-code 1 --scanners vuln /relay` and
  Grype `dir:/relay --fail-on high --only-fixed`, with the same digest-pinned images the image
  jobs use (`:176`, `:213`). It needs no accepted-risk file today (the image job's is empty,
  `:216-233`); if one is ever needed, the image job's write-and-expire steps are copied. The existing image jobs already
  scan `/usr/local/bin/relay-go` through its embedded build info, but only after merge and
  against the published image (`:37-44`); the new job is the pre-merge half.
- **Renovate** (`renovate.json`) gains three rules: `gomod` updates wait 7 days and are never
  automerged, with `gomodTidy`; every `go.opentelemetry.io/**` module is grouped into one update
  (they release together, and a split bump does not build); govulncheck gets the same cooldown;
  and a `customManagers` regex entry that tracks
  `GOVULNCHECK_VERSION` in `go-tests.yml` with the `go` datasource. The hunk is in Appendix A.2.
- **Docs.** `docs/supply-chain.md` § Dependency integrity and § Vulnerability scanning gate say
  what changed, in O1.

### D4 — The relay exports three signals over OTLP/HTTP and serves `/metrics` (R3)

`relay/telemetry` builds one `MeterProvider` with a Prometheus reader (always) and, when D12
enables OTLP, a periodic OTLP/HTTP metric reader as well; a `TracerProvider` and a
`LoggerProvider`, each with a batch processor over a redacting OTLP/HTTP exporter (D9), only when
OTLP is enabled. With OTLP off, the global tracer provider stays the API's no-op, so the span
calls in D11 cost a context lookup and nothing else.

`/metrics` is served by `promhttp.HandlerFor` over a private `prometheus.Registry` that only the
OTel exporter writes to, so the Go runtime collectors client_golang registers by default are not
on it. It is registered in `relay/httpapi/server.go`'s `New` beside `/healthz` and `/readyz`
(`:59-60`), **outside** the `cfg.DevRoutes` block (`:63`), on the same listener and port
(`DISPATCHARR_RELAY_GO_PORT`, 5658). `httpapi.Config` gains a `Metrics http.Handler` field; a nil
handler registers nothing, so every existing test that builds a `Config` is unaffected.

The exporter is built with
`otelprom.New(otelprom.WithRegisterer(reg), otelprom.WithTranslationStrategy(otlptranslator.UnderscoreEscapingWithSuffixes), otelprom.WithoutTargetInfo(), otelprom.WithoutScopeInfo())`.
The translation strategy is **pinned** because v0.69.0's default depends on Prometheus's name
validation mode, and upstream says the default will change (`exporters/prometheus/config.go:107-120`).
`WithoutUnits` and `WithoutCounterSuffixes` are deprecated in its favour. Pinning it makes
`github.com/prometheus/otlptranslator` a direct requirement (§ Go modules). `WithoutTargetInfo`
and `WithoutScopeInfo` keep the resource and scope off the unauthenticated endpoint (D9).
**Measured**: with these four options, the catalogue names render unchanged and the series
carry only their own labels (§ Versions checked).

Only HTTP/protobuf is supported (`otlptracehttp`, `otlpmetrichttp`, `otlploghttp`). No gRPC
exporter is used (ADR 0011 § What stays banned), although `google.golang.org/grpc` is linked
transitively through the OTLP collector packages (§ Go modules, measured).

### D5 — Django, Celery and Daphne push OTLP only (R3)

Python processes export over OTLP/HTTP with `opentelemetry-exporter-otlp-proto-http`. No
Prometheus endpoint and no multiprocess Prometheus directory: four API workers, one relay uWSGI
worker, Celery prefork children and beat would each need a shared-directory collector, which is
what OTLP push avoids. Each process is its own OTel resource, distinguished by
`service.instance.id` (D13).

### D6 — `/metrics` is not routed by nginx, has no auth, and a NetworkPolicy is documented (R4)

`docker/nginx.conf` gains nothing for `/metrics`, and a test pins that it never does (O4, the
sixth test in `e2e/tests/streaming-greybox/nginx-stream-buffering.spec.ts`):

1. **Positive control.** `docker exec <container> curl -fsS http://127.0.0.1:${DISPATCHARR_RELAY_GO_PORT:-5658}/metrics`
   answers 200 and its body contains `# TYPE mino_relay_channels gauge`. Without this the
   assertion below would pass on a relay that serves no `/metrics` at all.
2. **Not through nginx.** `GET <baseURL>/metrics`, `GET <baseURL>/metrics/` and
   `GET <baseURL>/metrics?x=1` through the published nginx port each answer something whose body
   does not contain `mino_relay_` (today: the SPA's HTML from `location /`, `docker/nginx.conf:716`).
3. **No location targets it.** No block from `parseLocationBlocks` whose body proxies to
   `relay_go` has a target that `/metrics` would match: the five Go-bound targets stay exactly
   `PROXY_BOUND_TARGETS` plus `/proxy/relay/` and `/hls/` (an exact sorted `toEqual`).

The relay's port carries no auth for `/metrics`, by ruling. What a scraper learns is bounded by
D7: numeric ids, formats, counts and byte totals, never a UUID or a URL. The docs page (D15)
gives a Kubernetes NetworkPolicy that admits ingress to the relay's port only from the nginx
pods, the Django pods (for `/proxy/relay/…`) and the collector or Prometheus pods.

### D7 — Labels, and the channel's numeric id on the wire (R5)

Metric labels use bare keys: `channel_id`, `kind`, `profile_id`, `format`, `trigger`, `outcome`,
`state`, `queue`, `task`, `m3u_profile_id`, plus the HTTP semantic-convention keys D9 allowlists.
Values are integers rendered as strings, or members of a closed set this spec names.

The relay keys every channel by its UUID string and has never been told the numeric primary key:
`relay/control/release.go:19-23` records that `channel_pk` "is on no contract field". O3 adds it.
`apps/proxy/serializers.py:267`'s `NextSourceResponseSerializer` gains
`channel_pk = serializers.IntegerField(allow_null=True)`, and `apps/proxy/next_source.py`'s
`resolve_source` (`:956`) sets it at each of its returns from the object it already resolved at
`:1037` (`resolved_object.pk` when that is a `Channel`, `None` for a previewed `Stream`). No new
query: `apps/proxy/tests/test_tune_path_query_ledger.py` must pass unchanged, and is O3's
break-check. The relay parses it as `ChannelPK *int` on `NextSourceAnswer`
(`relay/control/nextsource.go:203-245`), records it on the channel when the channel is published,
and renders `channel_id="0"` for a previewed stream or an answer without the field. The release
request keeps not sending it (unchanged, `release.go:19-23`).

`kind` is one of `source` (the Stream Profile's process, `relay/channel/source_transcode.go:183`),
`output` (an Output Profile transcode, `relay/output/profile.go:137`), `fmp4` (the fMP4 remux,
`relay/output/fmp4.go:532` and its retry at `:618`) or `hls` (the HLS pipeline,
`relay/hls/pipeline.go:695` and `:891`). `profile_id` is the Output Profile id for `output` and
for a profiled `fmp4` chain, the HLS Output Profile id for `hls`, and `"0"` otherwise. The HLS
silence generator (`relay/hls/silence.go:123`) and the Quick Sync detector
(`relay/hls/detect.go:184`) are not tracked: they run for seconds and own no channel.

**Cardinality.** Series exist per live channel and per profile in use, which at household scale
is tens. Counters keep a series for every channel ever watched until the relay restarts; the
Go SDK's per-instrument cardinality limit (default 2,000 attribute sets, overflowing into one
`otel.metric.overflow="true"` series) is left at its default and named in the docs page.

### D8 — Logs: JSON on request, trace ids in it, OTLP when enabled (R6)

`MINO_LOG_FORMAT` takes `text` (the default) or `json`. Any other value is treated as `text` and
produces one WARNING naming the variable and the value's length, never the value.

**Python.** `dispatcharr/settings.py`'s `LOGGING` (`:567-638`) gains two formatters and one
handler, and changes nothing else when the variable is unset:

- `json`: `dispatcharr.observability.logs.JsonFormatter`, one object per line with the keys in
  § Log record schema.
- the `console` handler's `formatter` becomes `"json"` when `MINO_LOG_FORMAT=json`, else stays
  `"verbose"`.
- an `otel` handler, class `dispatcharr.observability.logs.OtelBridgeHandler`, added to every
  logger in the dict that has `console` (they all set `propagate: False`, so the root alone
  would miss `apps.*`, `celery.*`, `core.*`). `OtelBridgeHandler.emit` is a no-op until D10's
  post-fork init has installed a `LoggerProvider`, and then forwards to an
  `opentelemetry.instrumentation.logging.handler.LoggingHandler`. That is the ruling's "OTel
  LoggingHandler" at its current home: `opentelemetry-sdk` 1.45.2's own
  `opentelemetry.sdk._logs.LoggingHandler` warns on construction that it "is deprecated. Use the
  handler from `opentelemetry-instrumentation-logging` instead" (read in the installed package,
  `opentelemetry/sdk/_logs/_internal/__init__.py:615-618`). Only the handler class is used;
  `LoggingInstrumentor`, which replaces the log record factory process-wide, is not.
  `LOGGING` is applied at settings import, which in the Celery parent and the
  uWSGI master (when `lazy-apps` is off) is before the fork, so the handler must exist then and
  must not start anything; the shim is how.

No existing log call is rewritten. Celery's own `worker_log_format` and
`worker_task_log_format` (`dispatcharr/celery.py:71-77`) are untouched; with
`worker_hijack_root_logger=False` the `celery*` loggers in `LOGGING` are what format Celery's
records. Lines that never pass through Python `logging` stay text in either mode: uWSGI's request
log (`docker/uwsgi.ini:69`), the `print()` calls in `dispatcharr/celery.py` and
`dispatcharr/gevent_patch.py`, supervisord, nginx, postgres and redis. The docs page says so.

**Go.** `relay/main.go:30-31` keeps `log.SetFlags`/`log.SetPrefix` for the text format. For
`json`, `main` installs `slog.SetDefault(slog.New(handler))` before `config.Load` (`:33`), where
`handler` is a `slog.JSONHandler` on stderr wrapped by `telemetry.ContextHandler`, which adds
`trace_id` and `span_id` from the record's context when it holds a valid span and adds
`service.name`. Every existing `slog.Default()` user and every `log.Printf` (which the slog
default handler then receives) is covered with no call-site change. When OTLP is on, the default
handler is a fan-out over that handler and the `otelslog` bridge handler. Most relay log calls
take no context, so they carry no trace id; the docs page says so, and no call is rewritten to
add one (R6).

**JSON is a new sink, so it gets D9's rules.** Python's `JsonFormatter` passes `msg` through
`redact_text` and renders an exception as its type and frame list (D9). In Go, the JSON handler
sits behind `SafeHandler`, the typed log-field allowlist. The text format is untouched in both
languages, so `MINO_LOG_FORMAT=text` is byte-identical to today. A channel UUID in a text-format
line is today's behaviour and is out of this spec's scope.

### D9 — Redaction at every exporter boundary (R7, R-Q17)

**Two standards, by ruling R-Q17 (2026-11-01).**

1. **Allow by construction**, for everything this spec creates: span names, span attributes,
   span status descriptions, span events, metric attributes, `/metrics`, and **structured log
   fields**. The resource is not on this list: `OTEL_RESOURCE_ATTRIBUTES` is trusted operator
   configuration (R-Q18, D13), and our own resource attributes are fixed by code. Only a value whose key is on an allowlist **and** whose type and
   shape match that key's rule is exported. There is no scrubbing step that a value could slip
   past: what is not provably safe is dropped or replaced by a classification. Round 2 showed
   why denylist scrubbing fails. `ValueError("S3NT1NEL-pw-9d2f")` passes every pattern
   class, and three instrumentations copy exception text into the status description
   (measured below).
2. **Best effort, no stronger than stdout**, for the **bodies** of existing log calls, whether
   they go to the JSON formatter or over OTLP. A log body is the free text a call site already
   writes to stdout today. It is scrubbed by the pattern classes below and is **explicitly not
   claimed to be safe**: an exception message interpolated into a body (Celery's retry and
   failure logging does this) reaches the body as it reaches stdout today. **This is no stronger
   than stdout.** The docs page says so. The safety of a free-text body rests where it rests
   today:
   - on the call-site checks, `scripts/check_credential_logging.py` and `relay/internal/credlint`,
     both extended as below;
   - and on a future structured-logging rewrite, which is out of this spec's scope (R6).

   The scrubbing is **not a proof**. Its tests are **policy tests**: each pattern class the
   scrubber targets is shown to be removed from a body that contains it. They do not show that
   a body holds no secret.

**What the instrumentations actually emit.** Measured with Django 6.0.8, the five
instrumentations at 0.66b2 and `OTEL_SEMCONV_STABILITY_OPT_IN=http`, on a minimal app whose
routes copy `apps/proxy/stream_routes.py:99-107`'s two XC `re_path`s:

| Request or call | Span name | Status | Attributes | Leaks without a boundary |
|---|---|---|---|---|
| `GET /live/user1/<secret>/42?password=<secret>` | `GET ^live/(?P<username>[^/]+)/(?P<password>[^/]+)/(?P<channel_id>[0-9]+)\Z` | unset | `http.request.method`, `http.route` (that same regex: placeholders, not captured values), `http.response.status_code`, `server.port`, `url.scheme` | none |
| `GET /no/such/<uuid>`: a genuine `Resolver404` | `GET` | unset | the same minus `http.route` | none |
| a view raising `ValueError(<secret>)` | `GET boom/` | ERROR, description `ValueError: <secret>` | adds `error.type`; an `exception` event with `exception.message` and `exception.stacktrace` | **status description, event** |
| `requests` call to a credentialled URL, failing in the transport | `GET` | ERROR, description holds urllib3's message with path and query | `url.full`, `user_agent.original`, `network.peer.address`, `network.peer.port`, `server.address`, `server.port`, `error.type` | **status description, `url.full`, event** |
| Celery task raising `ValueError(f"bare {arg}")` | `run/p.t` | ERROR, description `bare <secret>` | `celery.action`, `celery.state`, `celery.task_name`, `celery.hostname`, `celery.delivery_info`, `messaging.message.id` | **status description, event** |

**Python span boundary** (`dispatcharr/observability/redaction.py`,
`RedactingSpanExporter(inner)`). It rebuilds each `ReadableSpan` before `inner.export`, with
these rules:

- **Attributes.** A key survives only if it is on the allowlist and its value passes that key's
  validator. A value that fails is dropped, never rewritten.

  | Key | Validator |
  |---|---|
  | `http.request.method` | one of the HTTP methods or `_OTHER` |
  | `http.response.status_code`, `server.port` | `int` (not `bool`) |
  | `http.route` | `^[\w/<>:^$?()\[\]{}|\\+*.,=-]{1,256}$`, a URL pattern from the resolver, which is code |
  | `url.scheme` | `http` or `https` |
  | `server.address` | hostname charset, at most 253 characters |
  | `error.type`, `celery.action`, `celery.state`, `celery.task_name` | dotted identifier, at most 128 characters |
  | `messaging.message.id` | a UUID |
  | `db.system`, `db.name`, `db.operation.name`, `db.redis.database_index` | identifier, or `int` for the last |

  O5's recorded sample (below) may remove keys from this table, and may add a key only with a
  validator of this kind.
- **Status.** The code is kept. The description is **replaced** by the span's exception type
  (from its `exception` event, validated as an identifier), or set to none. It is never
  scrubbed or kept.
- **Events.** Only `exception` events survive, carrying `exception.type` only.
- **Links.** Their attributes are dropped.
- **Name.** The name is kept only if it is one of these:
  - exactly `http.request.method`;
  - `http.request.method` followed by a space and the validated `http.route`;
  - `run/<ident>` or `apply_async/<ident>`;
  - a SQL verb or Redis command word (`^[A-Z]{2,16}( [A-Z]{2,16})?$`).

  Otherwise it is replaced by the instrumentation scope's name.
- **Route expectations**, measured and pinned by O5:
  - an XC tune's span carries the exact `re_path` regex string from `stream_routes.py:100`
    (or `:105`) as `http.route` and in the name;
  - a genuine `Resolver404` yields the name `GET` with no `http.route`;
  - no raw-path fallback exists.

  These are tested on the real urlconf, not a synthetic span.

**Python metric boundary.** The SDK `View`s (one per catalogue instrument, with
`attribute_keys=` set to its labels, plus the wildcard `DropAggregation` view) cut the keys.
`RedactingMetricExporter(inner)` then validates each point's attribute values with the same
validator table, plus the catalogue's own value rules: `task` is a dotted identifier, `outcome`
and `queue` come from their closed sets, and `m3u_profile_id` is `^\d+$`. A point whose
attribute fails is dropped, and the drop is logged once per instrument. Exemplars are off
(below).

**Python log records** (OTLP `RedactingLogExporter`, and `JsonFormatter` for stdout):

- **Structured fields** are allow by construction:
  - `code.filepath`, `code.function` and `code.lineno`;
  - `exception.type`;
  - `mino.exception.frames`, a list of `"file:line in function"` built from
    `traceback.extract_tb` with `capture_locals` off. It carries no source text, no message and
    no locals.

  Python `extra=` attributes are structured fields, so they are allow by construction too: they
  pass through a typed per-key allowlist with the same validator kinds as the span table. That
  allowlist is **empty** at O5, because no non-test call site passes `extra=` to a logger
  (`git grep -n "extra=" -- 'apps/*.py' 'core/*.py' 'dispatcharr/*.py' ':!*/tests/*'` finds no
  logging call at the seed). Every `extra` key is therefore dropped until a key is given a typed
  rule. Every other attribute is dropped too.
- **Body**, best effort (R-Q17): `redact_text(record.getMessage())`, where `redact_text` applies
  the pattern classes below.

**Go span boundary** (`relay/telemetry`, `redactingSpanExporter` over `otlptracehttp`). Span names
come from a closed set of constants. Attributes are the § Span catalogue's typed keys, recorded
by `relay/telemetry` from typed parameters and validated again at export by the same table.
Events carry `exception.type` only, which is the `%T` of the innermost error that
`errors.Unwrap` reaches. The status description is replaced by that type. No `otelhttp` is used:
two XC routes carry the password in the path (`relay/httpapi/server.go:70-71`).

**Go structured log fields: `SafeHandler`** (finding 1). It is a `slog.Handler` placed in front of
**both** new sinks, the JSON handler and the `otelslog` bridge. The text format is untouched.

1. **Resolve first.** Every value goes through `slog.Value.Resolve()` before it is classified, so
   a `LogValuer` is judged by what it resolves to.
2. **Groups recurse.** A group value, and a `WithGroup` prefix, are walked recursively, and each
   leaf is classified by its own key under the group path.
3. **`WithAttrs` is classified when it is attached.** The handler stores the cleaned attributes,
   not the raw ones. That covers `relay/output/profile.go:130`'s `log.With("channel", …)`, and
   `With` calls from any package, inside or outside the module.
4. **`KindAny` holding an `error`** becomes `<key>.type`, the `%T` of the innermost error. Its
   text is never exported. **Any other `KindAny` value is dropped**: structs, maps, slices and
   pointers have no rule.
5. **Key rules.** A key's rule comes from `relay/telemetry/logkeys.go`. A key with no rule,
   including a computed key, is dropped. Each rule names one class, and a value whose kind or
   shape does not match its class is dropped. **Round 3 (finding 1): a character set is not
   credential exclusion.** A charset rule such as `^[A-Za-z0-9_.:-]{1,64}$` accepts
   `S3NT1NEL-pw-9d2f` and a channel UUID unchanged, so there is no such class. Every retained
   string must be bound to an identity this code controls: a closed inventory of known values,
   a numeric id, or a value this code produced.

   | Class | Accepts | Why it cannot carry a secret |
   |---|---|---|
   | `int` | `KindInt64`, `KindUint64` | a number: stream ids, profile ids, counts, status codes |
   | `bool` | `KindBool` | |
   | `duration` | `KindDuration` | |
   | `enum` | `KindString` **equal to** one member of the rule's closed set, written in `logkeys.go`. Examples: `trigger` ∈ {`health_monitor`, `max_retries_exceeded`, `buffering_timeout`}; `state` ∈ the `channel.State` names; `reason` ∈ the event reasons the relay emits | the set is source code; a value outside it is dropped |
   | `profilekey` | `KindString` matching `^(mpegts\|fmp4\|hls)(:p([1-9][0-9]{0,18}))?$` **and** a suffix that `strconv.ParseInt(…, 10, 64)` accepts as a positive value. This is the domain `output.FormatKey` can produce (`relay/output/profile.go:51-62`, `strconv.Itoa` of an `int`; `ProfileKey` at `:47` calls it) for the ids the relay accepts: positive `int`s parsed with `strconv.Atoi` (`relay/httpapi/stream.go:441-447`), from Django's `BigAutoField` (`dispatcharr/settings.py:369`). That is 1 to 9223372036854775807 on the 64-bit builds the Dockerfile produces, with no leading zero. Round 3's `[0-9]{1,9}` ceiling was wrong (round 4 finding 2): it dropped `mpegts:p1000000000` | a closed prefix and a number in the id domain |
   | `channel` | `KindString` matching the UUID pattern. Emitted as `channel_id`, the numeric id from `telemetry.ChannelIDs`, or `"0"`. **The UUID itself is never emitted** | it is replaced by a number |

   There is no free-text class and no charset class. Keys whose values are free text or
   externally supplied are classed `drop` in `logkeys.go`: client ids (minted from
   `X-Relay-Client`), user agents, addresses, paths and names. **A UUID-shaped string is
   rejected under every key except a `channel`-class key**, before the class is consulted. So an
   `enum` set that wrongly listed a UUID still cannot emit one.
6. **Drop precedence.** The steps above run in that order and stop at the first drop: resolve,
   group recursion, the `error` route, the key rule, UUID rejection, then the class check.
7. **The message** is the log body and is scrubbed best effort (R-Q17) by `scrub`, which is
   `relay/redact.Line` followed by the pattern classes below.

The same validation is applied a second time, authoritatively for OTLP, by the
`redactingLogExporter` that wraps `otlploghttp`. It runs on every `sdklog.Record`: a clone with
`SetAttributes` (the cleaned attributes) and `SetBody` (the scrubbed body). That covers any
record that reached the logger provider without passing `SafeHandler`. OTel's own internal
logging reaches `slog` through `stdr` and the standard `log` package, because `main` calls
`slog.SetDefault`. `relay/telemetry` also installs `otel.SetErrorHandler` with a handler that
logs `"otel error"` with an `error` attribute, so the SDK's own errors leave as a type, not as
text.

The census test (`logkeys_test.go`) is inventory, not enforcement. It fails when a literal key in
the module has no rule, so that new log calls are classified deliberately. Enforcement is the
runtime validation above, which handles computed keys and keys from outside the module by
dropping them.

**Exemplars are off** in both languages: Python
`MeterProvider(exemplar_filter=AlwaysOffExemplarFilter())`, Go
`sdkmetric.WithExemplarFilter(exemplar.AlwaysOffFilter)`.
- With the defaults, a histogram recorded inside a sampled span exported a View-excluded secret
  attribute in the exemplar's `filtered_attributes`. Measured in Python 1.45.2, whose default is
  `TraceBasedExemplarFilter` (`opentelemetry/sdk/metrics/_internal/__init__.py:450`), and in Go
  v1.47.0, whose default is `exemplar.TraceBasedFilter` (`sdk/metric/config.go:81`).
- With the filter off, the same recording exported no exemplar and no secret.
- Both options take precedence over `OTEL_METRICS_EXEMPLAR_FILTER`: Python takes the argument
  before reading the environment (`:450`), and Go applies options after the environment
  (`config.go:84-91`).

**The resource and `/metrics`.** The OTLP resource is our fixed attributes merged over the trusted
`OTEL_RESOURCE_ATTRIBUTES` (R-Q18, D13). `/metrics` carries no `target_info` and no scope labels,
so no resource attribute reaches the unauthenticated endpoint.

**The pattern classes**, used **only** for log bodies (R-Q17): absolute URLs, scheme-less `/…`
paths, UUIDs, HLS media-session tokens (`relay/control/mediasession.go:50-52`'s shape), runs of
32 or more hex digits, and `key=value` secrets. They are documented as best effort.

**The checkers.** `scripts/check_credential_logging.py` gains the telemetry call shapes (a method
in `set_attribute`, `set_attributes`, `add_event`, `record_exception`, `start_as_current_span`,
`start_span`, `set_status`, `add`, `record` or `set`, on a receiver ending in `span`, `tracer`,
`counter`, `histogram`, `gauge` or `meter`). It is a lint at the call site. The boundary does
not depend on it, and it keeps its documented blindness to `str(exception)`
(`scripts/check_credential_logging.py:95-98`). `relay/internal/credlint` gains D2's two OTel
sinks.

**The leak tests** (finding 4). Each test separates **policy assertions**, the invariants (a
prohibited key is absent, a channel maps to its numeric id, a field the rules should keep is
present, there is no `target_info` family), from **leak assertions** (the sentinel appears in no
exported byte). Every test first asserts its export is non-empty and holds the expected item. It
uses deterministic local transports: a mounted `requests` adapter raising urllib3's own message
shape, and an `http.Client` whose `RoundTripper` returns an error. It reports every failed
assertion, not just the first. Each boundary rule has one isolated mutation, chosen so that only
that rule stops the input.

The planner built both boundaries as scratch prototypes on 2026-11-01 (the Python span exporter
over the real Django, `requests` and Celery instrumentations; the Go `SafeHandler`) and ran each
mutation. **Recorded results:**

| Mutation (Python span boundary) | Recorded failure |
|---|---|
| none | `PASS` |
| keep the status description | `LEAK in span 'GET boom/': status`, `LEAK in span 'GET': status`, `LEAK in span 'run/p.t': status` |
| keep `exception.message` on events | `LEAK … 'GET boom/': attr/event`, `LEAK … 'GET': attr/event`, `LEAK … 'run/p.t': attr/event` |
| allow `url.full` with any value | `LEAK in span 'GET': attr/event`, `POLICY key url.full on 'GET'` |
| accept any span name (input: a span the test names with the sentinel, which is the name rule's own unit case; the route expectations above are separately tested on real spans) | `LEAK in span 'S3NT1NEL-pw-9d2f': name` |
| bypass the exporter | every leak above, plus `POLICY key celery.delivery_info`, `celery.hostname`, `network.peer.address`, `network.peer.port`, `url.full`, `user_agent.original` |

| Mutation (Go `SafeHandler`, re-run on 2026-11-01 with the closed-inventory classes and hostile values under **allowed** keys) | Recorded failure |
|---|---|
| none | `ok` |
| `enum` accepts any string (input: `trigger=<sentinel>`, an allowed key) | `LEAK: "S3NT1NEL-pw-9d2f" reached the sink` |
| skip UUID rejection (input: `reason=<uuid>` under a test rule whose enum wrongly lists that UUID) | `LEAK: "5e171e10-0000-4000-8000-00000000d2f0" reached the sink` |
| the `channel` class emits its raw value (inputs: `channel=<uuid>` and `channel=<sentinel>`) | `POLICY: missing "channel_id":"42"`, `LEAK: "S3NT1NEL-pw-9d2f"`, `LEAK: "5e171e10-…"` |
| accept a non-error `KindAny` (a struct holding the sentinel) | `LEAK: "S3NT1NEL-pw-9d2f" reached the sink` |
| export an error's text instead of its type (input: the `*url.Error` from the failing `RoundTripper`) | `POLICY: missing "error.type":…` and `LEAK: "S3NT1NEL-pw-9d2f"` |
| pass `WithAttrs` through unclassified | `POLICY: missing "channel_id":"42"` and `LEAK: "5e171e10-…"` |
| skip `Resolve` | `POLICY: missing "count":7`. The `LogValuer` resolving to 7 is dropped, not leaked, so skipping it fails safe and the policy assertion is what catches it |

The same baseline run also carried these **hostile values under allowed keys**, and every one
was dropped:
- `trigger=<sentinel>`;
- `format="mpegts:<sentinel>"`, which fails `profilekey`;
- `format="mpegts:p9223372036854775808"` (one past `int64`), `"mpegts:p0"` and `"mpegts:p01"`;
- `stream=<sentinel>`, a string under an `int` key;
- `channel=<sentinel>`, not a UUID;
- `count="7"`, a string under an `int` key;
- `reason=<uuid>`.

The allowed values `format="mpegts:p3"` and `reason="degraded_failover"` were kept. That is the
policy assertion the hostile cases sit beside. The `profilekey` domain was measured separately
(2026-11-04, scratch prototype):
- **retained:** the bare formats, `mpegts:p3`, the nine/ten-digit boundary `mpegts:p999999999`
  and `mpegts:p1000000000`, the maximum `mpegts:p9223372036854775807`, and `FormatKey`'s output
  for each of those ids;
- **dropped:** `p9223372036854775808`, `p0`, `p01`, `p-1`, a 20-digit suffix, `avi:p3` and the
  sentinel.

Break-check: restore round 3's `[0-9]{1,9}` suffix. The retained cases redden naming
`mpegts:p1000000000` and `mpegts:p9223372036854775807`. The same mutation also kept `mpegts:p01`,
which the leading-zero rule exists to drop.

Two real existing calls were driven through the prototype, each beside a **control** handler that
must see the carrier first, so a call that never logs cannot make the test pass:
- `relay/channel/failover.go:195` on a channel with no resolver. The control printed
  `"channel":"5e171e10-…"`; `SafeHandler` printed `"channel_id":"42"`.
- `relay/output/fmp4.go:612`'s `p.log.Info("the remux ended")`, logged under the `With` bound at
  `:529` (`log.With("channel", cfg.ChannelID, "format", FormatFMP4)`). The test starts a real
  pipeline through `output.Start` with a stand-in command (`sh -c "exit 0"`, fed the channel's
  ring by the pipeline's own writer) and waits for the record. Control:
  `{"msg":"the remux ended","channel":"5e171e10-…","format":"fmp4"}`. Safe:
  `{"msg":"the remux ended","channel_id":"42","format":"fmp4"}`.

Round 3 (finding 4) showed that `output/profile.go:130`'s `With` cannot serve as such a fixture
as written: `StartProfile` returns at `:132-133` for an empty command before any record is
emitted. The fMP4 pipeline above replaces it.

The implementation PRs re-run each mutation against the real code and record its failure in the
PR body. The tables below give the cases each PR adds.

Python cases (`tests/test_observability_redaction.py`, label `tests`; Postgres and Redis come from
the test container):

| Instrumentation or sink | Case |
|---|---|
| django | the real urlconf: an XC tune URL with credentials and a `password` query; `/proxy/ts/stream/<uuid>`; `/hls/<token>/x.m3u8`; an unrouted path; a view raising with a bare sentinel; header capture set to `.*` with a sentinel header |
| requests | a credentialled URL through the failing adapter; `relay_client.advance` (`apps/proxy/relay_client.py:143`) under instrumentation, whose injected `traceparent` names the `requests` client span (D11) |
| psycopg | `cursor.execute("SELECT 'S3NT1NEL-pw-9d2f' FROM")`, a syntax error echoing the literal |
| redis | `execute_command("NOSUCHCMD", "<sentinel>")`, whose error echoes the argument; `SET <uuid> <sentinel>` |
| celery | `apply(args=[<sentinel>], kwargs={"k": <sentinel>})` raising with the bare argument; a task that retries with the sentinel in its exception. The retry log **body** is R-Q17's best effort and is asserted only for URL, UUID and token classes, not for the bare sentinel |
| log fields | `extra={"secret": …}` and `extra={"count": 3}`, both dropped by the empty allowlist (policy). A test-only rule `count: int` keeps the second and still drops the first (policy and leak). `logger.exception` from a function with a local variable holding the sentinel: frames carry no locals |
| log bodies (policy tests only, R-Q17) | one body per pattern class (URL, scheme-less path, UUID, HLS token, long hex, `password=`), each asserted removed. A bare sentinel in a body is **not** asserted absent, because no class targets it; the test says so in a comment |
| metrics | an excluded attribute recorded inside a sampled span; an uncatalogued counter; a catalogue point whose `task` value is the sentinel URL (fails the identifier rule and is dropped) |

Go cases (`relay/telemetry/*_test.go` in O2; real-call cases in O4):

| Sink | Case |
|---|---|
| spans | `relay.next_source` failing through the `RoundTripper`; the status description and event are the type only |
| logs | O2: computed keys, a nested struct, a `LogValuer`, `With` from a package outside `relay/`, groups, an `error` with the sentinel URL, and `otel.Handle(errors.New(<sentinel>))` through the installed error handler (its error leaves as a type). Body policy tests per pattern class, as in Python, with no claim about a bare secret. O4: the two real calls above (`failover.go:195`; `output/fmp4.go:612` under the `With` at `:529`, through a stand-in pipeline), each with a control handler that must see the UUID first |
| `/metrics` and OTLP metrics | `TestMetricsEndpointCarriesNoResource` (D13): a sentinel in `OTEL_RESOURCE_ATTRIBUTES`, then no sentinel, no `target_info` family and no `otel_scope_*` label in the scrape (two separate mutations, each **measured on its own** on v0.69.0: dropping `WithoutTargetInfo` alone exposes the sentinel and the `target_info` family, and no scope label; dropping `WithoutScopeInfo` alone exposes `otel_scope_*` labels, and neither the sentinel nor `target_info`). Exemplars: M3 recorded inside a sampled span exports no exemplar (mutation: drop the option) |

### D10 — Python init: programmatic, after the fork, five instrumentations (R8)

`dispatcharr/observability/bootstrap.py` exposes `init(service_name: str, program: str)`. It is
idempotent per process: it records `os.getpid()` on success and returns immediately when called
again in the same pid, so calling it from two hooks in one process is harmless and calling it in
a forked child (a new pid) is what makes the child initialise. It never runs
`opentelemetry-instrument` and never reads `OTEL_PYTHON_*` auto-instrumentation switches.

When D12 says OTLP is off it installs nothing and returns. When on, it builds one `Resource`
(D13), a `TracerProvider` with D11's sampler and a `BatchSpanProcessor` over
`RedactingSpanExporter(OTLPSpanExporter())`, a `MeterProvider` with a
`PeriodicExportingMetricReader` over the OTLP metric exporter and D9's views, and a
`LoggerProvider` with a `BatchLogRecordProcessor` over `RedactingLogExporter(OTLPLogExporter())`;
sets them global; sets the global propagator to D11's `TrustedTraceContextPropagator`; then
instruments, in this order, `DjangoInstrumentor`, `CeleryInstrumentor`, `PsycopgInstrumentor`,
`RedisInstrumentor` and `RequestsInstrumentor`.

**The semconv opt-in must contain `http`** (round 3 finding 6). Before any instrumentation is
imported, `init` makes sure the effective `OTEL_SEMCONV_STABILITY_OPT_IN` contains `http`, so
the HTTP instrumentations emit the stable `http.server.request.duration` that catalogue row M10's
view renames:
- it splits the variable on commas and strips each token;
- it keeps every existing token in order;
- it appends `http` unless `http` or `http/dup` is already present (`http/dup` emits both
  conventions and includes the stable one);
- it writes the result back with `os.environ[...] =`.

`setdefault` would not do this. **Measured** with Django 6.0.8 and the Django instrumentation
0.66b2 on a cold import per case:

| Preset value | With `setdefault` | With the merge |
|---|---|---|
| unset | `http`, emits `http.server.request.duration` | `http`, emits `http.server.request.duration` |
| empty string | `""`, emits **only the old `http.server.duration`**, so M10 would vanish | `http`, emits `http.server.request.duration` |
| `database` | `database`, emits **only `http.server.duration`** | `database,http`, emits `http.server.request.duration` |

`tests/test_observability_wsgi_cold_import.py` runs the empty and `database` presets as two more
subprocess cases. Each asserts an M10 point and, for `database`, that the effective value is
`database,http`. Break-check: replace the merge with `setdefault`, and both cases redden with "no
`mino_api_http_server_request_duration` point".

**Init points**, one per process kind. Each calls `init` with its own `program` name:

| Process | Hook | Where | Why it is after any fork |
|---|---|---|---|
| `api-uwsgi`, `relay-uwsgi` | module import of `dispatcharr/wsgi.py`, **before** `get_wsgi_application()` (`:8`), immediately after the `DJANGO_SETTINGS_MODULE` default (`:7`); **and** `uwsgidecorators.postfork` when `uwsgidecorators` imports | `dispatcharr/wsgi.py` | Every uWSGI ini that loads `dispatcharr.wsgi` sets `lazy-apps = true` (`docker/uwsgi.ini:42`, `uwsgi.modular.ini:43`, `uwsgi.relay.ini:48`, `uwsgi.dev.ini:28`), so the module is imported in each worker after the fork. The postfork registration covers a configuration that turns `lazy-apps` off; the pid guard makes the two calls one. O5 adds `tests/test_uwsgi_inis_are_lazy.py`, which fails if any `docker/uwsgi*.ini` naming `dispatcharr.wsgi` lacks `lazy-apps = true`, so the import-time call cannot silently become a pre-fork call |
| `celery-default` (prefork) | `worker_process_init` | `dispatcharr/celery.py:48`'s existing handler, first line | Sent in each prefork child (`celery/concurrency/prefork.py:82` in Celery 5.6.3, read in the base image) |
| `celery-dvr` (threads) | `worker_init`, only when `sender.pool_cls` names the thread pool | new handler in `dispatcharr/celery.py` | `worker_process_init` is sent by the prefork and solo pools only (`concurrency/prefork.py:82`, `concurrency/solo.py:20`); `concurrency/thread.py` sends nothing, and the thread pool does not fork. `worker_init` is sent from `WorkController.setup_instance` (`celery/worker/worker.py:127`) while `pool_cls` still holds the configured name (`:378`), before it is resolved at `:130` |
| `celery-beat` | `beat_init` | new handler in `dispatcharr/celery.py` | Sent by `celery/beat.py:638`; beat does not fork |
| `daphne` | module import of `dispatcharr/asgi.py`, after the `DJANGO_SETTINGS_MODULE` default (`:7`) and **before** `django.setup()` (`:8`) and `get_asgi_application()` (`:13`) | `dispatcharr/asgi.py` | Daphne runs one process and does not fork (`docker/supervisord.d/daphne.conf`), and it has no ASGI lifespan support (django/daphne issue #264, open), so import time is the hook |

**Why before the handler is built** (finding 5). `DjangoInstrumentor().instrument()` works by
inserting its middleware into `settings.MIDDLEWARE`. A handler built earlier has already loaded
its middleware chain and never runs the inserted one. **Measured** with
`opentelemetry-instrumentation-django` 0.66b2 on Django 6.0.8, using a minimal settings module and
one route: instrumenting before `get_wsgi_application()` produced one server span named
`GET ok/<str:x>/`; instrumenting after it produced **no span at all**. That probe also showed
that, without the semconv opt-in, the server span records `http.url` including the query string,
which is one reason D9 keeps no URL key on server spans.

**Tests of the real entry points.**

- `tests/test_observability_wsgi_cold_import.py` runs a subprocess with an allowlisted
  environment. The environment sets `DJANGO_SETTINGS_MODULE=dispatcharr.settings_test` and
  `OTEL_EXPORTER_OTLP_ENDPOINT` pointing at a stdlib `http.server` that the test runs on
  `127.0.0.1:0` and that records the request bodies it receives. The subprocess imports the
  real `dispatcharr.wsgi` (a cold import, so nothing is instrumented beforehand), calls
  `application` with a WSGI environ for an unrouted path, and force-flushes the tracer and meter
  providers. The test decodes the captured `/v1/traces` and `/v1/metrics` bodies with
  `opentelemetry-proto` (a dependency of the exporter) and asserts:
  - one server span;
  - one `mino_api_http_server_request_duration` point;
  - a `service.name` of `mino-api`.

  Break-check: move the `init` call below `get_wsgi_application()`. The span assertion reddens
  with "no server span", which is the mechanism measured above.
- The authorize hop's `X-Relay-Traceparent` is asserted in O6, inside a `TestCase` that
  instruments in `setUpClass` and builds its client after that.
- `tests/test_celery_otel_init.py` exercises the threads-pool hook through Celery's own startup
  path. `app.WorkController(pool="threads", hostname=…)` constructs a real worker without
  consuming, and its constructor sends `worker_init` with `sender.pool_cls == "threads"`.
  **Measured** on Celery 5.6.3: the signal carried `'threads'`, and `'prefork'` for
  `pool="prefork"`, before the pool class was resolved. The test asserts that `init` ran once
  for `threads` and not at all for `prefork`.

`worker_process_shutdown` (prefork children, `prefork.py:90`) and `worker_shutdown` call
`force_flush` with a two-second bound. Telemetry from a uWSGI worker killed by `harakiri` or
recycled by `max-requests` loses at most one batch; that is accepted and stated in the docs page.

**A side finding, recorded and not fixed here.** `dispatcharr/celery.py:44-47` says plugin
discovery runs "in worker_process_init (each prefork child / thread worker)". The thread pool
sends no `worker_process_init`, so the `dvr` worker never runs `discover_plugins`. This spec only
uses the fact; O5's PR body links a new issue for it.

**gevent.** Under uWSGI's `gevent-early-monkey-patch` (`docker/uwsgi.ini:53`), `threading` is
patched before Django loads, so the SDK's batch-processor and periodic-reader workers are
greenlets on the worker's hub, their `Condition.wait(timeout)` is a cooperative sleep, and the
exporters' `requests` sockets are cooperative. What is not cooperative is protobuf encoding of a
batch, which runs on the hub; at the default batch size (512 spans) that is CPU time measured in
milliseconds, the same class as rendering a large DRF response. O5 adds the one gevent test the
ruling asks for, `tests/test_observability_gevent.py`: it runs a subprocess
(`[sys.executable, "-c", …]` with an allowlisted environment: `PATH`, `HOME`, `LANG`,
`PYTHONPATH` set to the repository root, nothing copied from `os.environ`) that calls
`gevent.monkey.patch_all()`, initialises an SDK tracer provider with an in-memory exporter, spawns
two greenlets that each open a span, `gevent.sleep(0)` inside it, open a child, and record
`(greenlet name, parent span id, current span id)`; the parent prints the records as JSON. The
test asserts each child's parent is its own greenlet's span, never the other's. **Measured** with
gevent 26.7.0 and SDK 1.45.2 on Python 3.13: both greenlets' children named their own greenlet's
span. Break-check, also measured: in the subprocess, replace `opentelemetry.context._RUNTIME_CONTEXT`
with a runtime context that keeps one process-global `Context` (a ten-line class with
`attach`/`get_current`/`detach`); the run then reports a child whose parent is not its own
greenlet's span and the second greenlet's record is lost, and the test reddens naming the
mismatched parent. The test runs only the SDK and gevent, not uWSGI; that uWSGI's own gevent loop
gives each request greenlet a fresh context is inferred from gevent's per-greenlet `contextvars`
support, which the probe exercises, and from uWSGI running each request in its own greenlet.

**Fork hooks.** The SDK registers `os.register_at_fork(after_in_child=…)` re-initialisation for
its batch processors and periodic reader (`opentelemetry/sdk/_shared_internal/__init__.py:117-124`,
`opentelemetry/sdk/metrics/_internal/export/__init__.py:531-538`, `opentelemetry/sdk/trace/__init__.py:244-254`
in 1.45.2). This design does not rely on them: uWSGI forks its workers from C, and whether
uWSGI's Python plugin runs Python's at-fork hooks in a worker was not verified. Initialising after
the fork in every process makes the question moot.

### D11 — The tune trace (R9)

```
nginx auth_request ──> Django: GET /_dispatcharr/authorize   [server span, root]
                         └─ response header X-Relay-Traceparent
nginx proxy_pass   ──> relay: relay.tune                      [server span, child]
                         ├─ relay.authorize                   [client; dev shape only]
                         ├─ relay.next_source                 [client]
                         │    └─ Django: POST /api/relay/channels/<id>/next-source [server]
                         └─ ends at the first byte written to this client
later:  relay.failover        [root, linked to the channel's relay.tune]
          └─ relay.next_source └─ Django next-source [server]
Django admin request [server span]
  └─ requests.request in relay_client.py:143 [client span, injects its own traceparent]
       └─ relay.stream_switch [server-side span owned by AdvanceHandler,
                               linked to the channel's relay.tune]
```

**Carrying the authorize hop's context across nginx.** `auth_request` runs before the relay sees
the request, so the relay cannot parent the authorize span; it can be its child. The authorize
view (`apps/proxy/authorize_views.py:287`) sets one more header on its 200 (`:350-361`):
`X-Relay-Traceparent`, the W3C `traceparent` of the current span, from
`dispatcharr.observability.propagation.current_traceparent()`, which returns `None` (and the
header is not set) when the current span context is invalid, which is always the case with OTLP
off. nginx carries it exactly as it carries the other `X-Relay-*` decision headers:
`auth_request_set $relay_traceparent $upstream_http_x_relay_traceparent;` and
`proxy_set_header X-Relay-Traceparent $relay_traceparent;` on the three Go-bound hop locations
(`^~ /proxy/ts/stream/` at `docker/nginx.conf:304`, `^~ /live/` at `:492`, the XC three-segment
regex at `:651`), and the two blanking includes blank it (Appendix A.1). The six uWSGI-bound hop
locations do not forward it: nothing on the Python relay reads it, and a client's own copy that
reaches Django there is inert because no Python code reads `HTTP_X_RELAY_TRACEPARENT`.

**Trust, in both languages.** A client must not be able to choose a trace id or force sampling.

- **Relay.** `relay.tune`'s parent is the context parsed from `X-Relay-Traceparent` **only when
  `control.IsRelayTrusted` accepts `X-Dispatcharr-Authorized`**, the same condition
  `relay/httpapi/stream.go:405-430`'s `identify` applies to every other `X-Relay-*` value. A
  `traceparent` or `tracestate` header on a public route is never extracted. On the internal
  routes (`/proxy/relay/…`, `server.go:94-98`) `traceparent` is extracted only after
  `RequireInternal` accepts the request.
- **Django.** `TrustedTraceContextPropagator` wraps W3C TraceContext. `inject` delegates
  unchanged. `extract` delegates only when the carrier is not a WSGI or ASGI request environment
  (Celery's task headers, which only this deployment's own producers write) or when it is one
  and its `X-Dispatcharr-Internal` header equals `internal_principal_token()`
  (`apps/proxy/internal_auth.py:103`, compared through `_matches`, `:108-116`). Otherwise it
  returns the context unchanged, so the Django span becomes a root. The relay sends the static
  internal header on every control-plane call (`relay/control/nextsource.go:463`, `relay/control/authorize.go:168`), so its
  `traceparent` is honoured; a browser's is not.

**Propagation from the relay.** `relay/control/nextsource.go:451`'s `attempt` and
`relay/control/authorize.go:140`'s `Authorize` inject `traceparent` from their `ctx` into the
outgoing request. The per-request HMAC binds method, path, timestamp and body
(`apps/proxy/internal_auth.py:135-162`), not headers, so adding one changes no signature.
`relay.tune`'s context reaches `startTune` because `StreamHandler` already passes `r.Context()`
(`relay/httpapi/stream.go:277`); the span is put on that context before `authorizeTune` (`:247`).

**Span ownership** (finding 8). Each relay span has exactly one owner, which starts it and
guarantees its end:

- **`relay.tune`** is owned by `StreamHandler` (`relay/httpapi/stream.go:219`).
  - It starts the span at the top of the returned handler (`:228`) as
    `tune := telemetry.StartTune(r.Context(), r)`. That call reads the trusted parent and
    returns a context and a `*Tune`.
  - It replaces `r` with `r.WithContext(ctx)`, so `authorizeTune` (`:247`) and `startTune`
    (`:277`, which already receives `r.Context()`) run under the span.
  - It immediately defers `tune.End()`.
  - `*Tune` holds a `sync.Once` and two methods. `FirstByte()` ends the span with
    `mino.outcome=streaming` and status 200. `Fail(outcome, status)` records the outcome a
    failure branch chose. The deferred `End()` ends the span with whatever was recorded:
    `refused`, `failed`, `redirect` or `draining`, or `abandoned` if the client went away
    before a first byte. `End()` is a no-op once `FirstByte` has run.
  - Each failure branch already writes its own response (`writeAuthorizeFailure`,
    `writeTuneFailure`, `http.Error`, the redirect at `:281-293`) and gains one `tune.Fail(…)`
    call beside it.
  - **The first byte is the first successful body write after stream setup succeeded**
    (round 2 finding 5, round 3 finding 3). `StreamHandler` wraps its `http.ResponseWriter` once,
    before any write, in `telemetry.FirstWriteWriter`.
    - **The wrapper starts disarmed.** While disarmed it only delegates, so an error body cannot
      end the span as `streaming`. Error bodies written before arming include the draining 503
      (`relay/httpapi/stream.go:238`), an authorize denial or failure
      (`relay/httpapi/authorize.go:119-126`), and the fMP4 remux-start 500
      (`relay/httpapi/fmp4.go:55-57`). Each of those branches calls `tune.Fail(outcome, status)`
      beside its existing write, and the deferred `End` ends the span with that outcome.
    - **`Arm()` is called at exactly three points**, each after setup has succeeded and
      immediately before the first media-path write:
      - at the top of `serveClient` (`stream.go:1047`), for TS;
      - after the fMP4 handler's `WriteHeader(http.StatusOK)` (`fmp4.go:66`), once the remux has
        started;
      - in the HLS entry path, immediately before the multivariant write
        (`relay/httpapi/hls.go:428`), once the session exists.
    - **Once armed**, the first `Write` that returns `n > 0` calls `tune.FirstByte()` exactly
      once, even if it also returns an error, because `n` bytes were accepted. `FirstByte` and
      `Fail` share the `sync.Once`, so whichever comes first is terminal.
    - It forwards `Header` and `WriteHeader` unchanged and exposes
      `Unwrap() http.ResponseWriter`, which `http.ResponseController` uses, so `rc.Flush()` and
      the deadlines behave as before. It changes no byte, no header and no status.

    Because it wraps the writer rather than a call site, it marks the first byte whichever path
    writes it:
    - the first chunk inside `writeChunks` (`stream.go:1204`), even when a later chunk in the
      same batch fails;
    - a keepalive packet (`:1125`);
    - the tail read (`:1159`);
    - the final error packet (`:1165`);
    - the fMP4 init segment (`relay/httpapi/fmp4.go:105`);
    - the HLS multivariant playlist (`relay/httpapi/hls.go:428`).

    The span therefore ends **while the viewer is still connected**. The same wrapper carries
    M3's byte counting: once armed, it adds the **returned `n`** of every `Write`, including
    `n > 0` with a non-nil error, so an accepted partial write is counted. Error bodies written
    while disarmed are not client media and are not counted.
- **`relay.authorize` and `relay.next_source`** are owned by `relay/control`. `Authorize`
  (`relay/control/authorize.go:140`) and `NextSource` (`relay/control/nextsource.go:384`)
  start the span from their `ctx`, end it before they return, and inject `traceparent` into each
  attempt (`attempt`, `:451`).
- **`relay.failover`** is owned by `Channel.failover` (`relay/channel/failover.go:190`).
  - It starts the span as a new root, linked to the tune span context the channel stored when
    it was published (the publishing tune's context, carried in `channel.Started`;
    `relay/channel/manager.go:130`).
  - It calls `c.resolver.Next` (`:211`) with the span's context, so `relay.next_source` is its
    child.
  - It ends the span at each return with M4's outcome.
- **`relay.stream_switch`** is owned by `AdvanceHandler` (`relay/httpapi/control.go:235`),
  which is the only place that holds both the request context and the channel.
  - The internal routes extract `traceparent` only after `RequireInternal` accepts the request
    (D11, Trust).
  - `AdvanceHandler` starts the span from `r.Context()`, linked to the channel's stored tune
    context, immediately before its `ch.Advance(…)` call (`:308`), and ends it when that call
    returns, with `mino.outcome` set to `applied` or `unchanged` from `Advance`'s boolean.
  - **`Channel.Advance` is unchanged** (`relay/channel/advance.go:25`): it starts no span and
    needs no context. That reverses round 1's plan to add a `ctx` parameter, which only the
    span would have used.
  - **The immediate parent is Django's `requests` client span, not its server span.**
    `apps/proxy/relay_client.py:143` calls `requests.request`. Under the `requests`
    instrumentation that call opens a client span, child of the admin request's server span,
    and injects the client span's own context. So the chain is: Django server span → `requests`
    client span → `relay.stream_switch`.

**Recording without importing OTel** (finding 7). `otel-confined` (D2) forbids
`go.opentelemetry.io` outside `relay/telemetry/**` and `relay/main.go`, test files included. O2
therefore adds `relay/telemetry/telemetrytest`, which sits inside the exempt path and is
imported only by tests, so it is never linked into the binary. It exposes stdlib-typed helpers:
- `telemetrytest.Install(t) *Recorder` installs a recording `TracerProvider` and a manual
  metric reader for the test's duration, using `t.Cleanup`.
- `(*Recorder).Spans() []Span`, where `Span` is
  `{Name, TraceID, SpanID, ParentSpanID string; Links []string; Attrs map[string]any; Status, Description string; Ended bool}`.
- `(*Recorder).Points(name string) []Point`.
- `(*Recorder).TuneCompletions() int`: the number of times `*Tune`'s completion path ran (round 5).
  `relay/telemetry` counts it in `(*Tune).complete`, the one function that `FirstByte`, `Fail`'s
  terminal path and the deferred `End` all reach. The count is taken **before** `span.End()`, so
  the SDK's idempotent `End` cannot hide a second completion. The counter is an `atomic.Int64`
  on the installed telemetry instance, so production pays one atomic add per tune.
- `telemetrytest.Traceparent(traceID, spanID string) string` builds a W3C header value for a
  request.

Tests in `relay/httpapi`, `relay/channel` and `relay/control` import only this package and the
standard library, so the lint gate holds. Break-check: add `tracetest` to a test in
`relay/httpapi`, and golangci-lint reports `otel-confined`.

**Trace tests** (O4, `relay/httpapi/trace_test.go`). Each uses `telemetrytest` and
`relay/internal/relaytest`'s fake control plane, which records request headers
(`relaytest/controlplane.go:412`):

1. **The whole graph.** A tune carries a valid marker and `X-Relay-Traceparent` naming span P.
   The test asserts four things:
   - `relay.tune`'s parent is P and its trace id is P's;
   - `relay.next_source` is `relay.tune`'s child;
   - the `traceparent` the fake control plane received names `relay.next_source`'s span id in
     the same trace;
   - every span carries the same trace id.
2. **The span ends at the first byte while the viewer stays connected.** The test reads the
   first chunk and, before closing the response body, asserts that `relay.tune` has ended with
   `mino.outcome=streaming`. It then keeps reading. Break-check: call `FirstByte` from the
   handler's return instead, and the assertion reddens with "tune span still open after first
   byte".
2a. **The first byte is a keepalive.** The channel's source produces no data, so the first body
    write is a keepalive packet. The span ends at that write. Break-check: move `FirstByte` to
    after `serveClient`'s first media `writeChunks`, and this case reddens.
2b. **A partial batch.** A `ResponseWriter` stub accepts the first `Write` and fails the second
    in one `writeChunks` call. The span has ended with `streaming` at the first write.
2c. **Only the tail is written.** The channel ends with data that only the final tail read
    delivers (`:1159`), or with no data and an error packet (`:1165`). The span ends at that
    write.
2d. **The response is unchanged.** The wrapped and unwrapped handlers produce byte-identical
    bodies and identical headers and statuses over the same recorded source, and `rc.Flush`
    still reaches the recorder.
2e. **Four outcomes, tested separately** (round 3 finding 3). Each asserts the span's outcome
    and status, and asserts that no first-byte event was recorded unless media was served:
    - an authorize **denial** with a JSON body: `refused`, the denial's status;
    - **draining**, the 503 body: `draining`, 503;
    - an **fMP4 output-start failure**, the 500 JSON body: `failed`, 500;
    - **successful media**: `streaming`, 200.

    **Disarming has its own oracle** (round 4 finding 3): each failure case also asserts that **M3
    did not move**. An error body written while disarmed is not counted, whatever the span says.
    The span outcome alone cannot detect a wrongly armed wrapper, because a correct
    implementation may call `Fail` before or after writing its error body:
    - with `Fail` first, the shared `sync.Once` keeps the outcome right even if the wrapper is
      armed;
    - only with the write first would the outcome flip to `streaming`.

    So each failure case runs **both orderings** (`Fail` then write, and write then `Fail`), and
    asserts M3 = 0 in both.

    Break-check: construct the wrapper armed. **Measured** on a scratch prototype of the wrapper
    and a denial branch:
    - both orderings redden on M3: `M3 counted 10 error-body bytes, want 0`;
    - only the write-first ordering also reddens on the outcome: `outcome="streaming"`.
2f. **M3 counts the returned `n`, and completion happens exactly once.** A stub
    `ResponseWriter` accepts 100 of 188 bytes on each `Write` and returns an error. After two
    armed writes, M3 is 200 and the outcome is `streaming`. The handler then calls a late
    `Fail` and returns, which runs the deferred `End`. At that point
    `(*Recorder).TuneCompletions()` is **exactly 1**.

    **The span record cannot be the oracle** (round 5): the SDK's `End` is idempotent, and a span
    already ended ignores later attribute changes. **Measured** on SDK v1.47.0 with a
    `SpanRecorder`: with `Fail` given its own `sync.Once`, the recorder still held **one** ended
    span with `mino.outcome=streaming`. Only the completion counter saw the second completion.

    Break-checks:
    - Count only writes with a nil error: the case reddens with "0, want 200".
    - Give `Fail` its own `sync.Once` instead of sharing `FirstByte`'s. **Measured** on a
      prototype of `*Tune` with the counter in `complete`: the case reddens with
      `completion invoked 2 times, want 1`, while the span record stays at one end with
      `streaming`.
3. **Failure before the first byte.** next-source is refused (the fake answers 403), so the
   client gets the existing error status. `relay.tune` has ended with `mino.outcome=refused`,
   that status, and no first-byte event.
4. **Untrusted context is ignored.** The same `X-Relay-Traceparent` arrives without a valid
   marker, or a bare `traceparent` arrives. Either way `relay.tune` is a root.
5. **An operator switch.** `POST /proxy/relay/channels/{id}/advance` arrives with valid
   internal headers and a `traceparent` naming span Q (standing for Django's `requests` client
   span), on a channel published by a traced tune T. `relay.stream_switch`'s parent is Q, its
   single link is T, and it ended with `applied` or `unchanged`. A second request without valid
   internal headers is refused before any span starts. O6 tests the Django half of the chain
   (§ O6, Tests).
6. **A failover.** A forced `health_monitor` failover gives `relay.failover` a root with a link
   to T, and a `relay.next_source` child.

The cross-process half is asserted where each part runs:
- O6's `TestCase` shows that the authorize 200 carries `X-Relay-Traceparent` naming the authorize
  request's span.
- O4's nginx test shows that nginx forwards it on the three Go-bound hop locations.
- Test 1 above shows that the relay parents `relay.tune` on it.

No single test spans Django, nginx and the relay. Together the three pin every hop.

**Sampler.** Both languages use `ParentBased(root = TraceIdRatioBased(r))`, with `r` from
`OTEL_TRACES_SAMPLER_ARG` (a float in [0, 1], default 1.0; an unparseable value is 1.0 with one
WARNING). `OTEL_TRACES_SAMPLER` is ignored, and the docs page says so. Because the only remote
parents either language accepts come from this deployment's own processes, the parent-based
half cannot be driven from outside.

### D12 — Off by default; the environment contract (R10)

OTLP is **enabled** in a process if and only if `OTEL_EXPORTER_OTLP_ENDPOINT` is set and
non-empty, and `OTEL_SDK_DISABLED` is not `true`. The relay's `/metrics` does not depend on
either.

| Variable | Read by | Behaviour |
|---|---|---|
| `OTEL_EXPORTER_OTLP_ENDPOINT` | all | Enables OTLP. Base URL for all three signals (`/v1/traces`, `/v1/metrics`, `/v1/logs` appended by the exporters) |
| `OTEL_EXPORTER_OTLP_{TRACES,METRICS,LOGS}_ENDPOINT` | all, through the exporters | Honoured as per-signal overrides; do not enable OTLP on their own |
| `OTEL_{TRACES,METRICS,LOGS}_EXPORTER` | all | `none` switches that one signal off; any other value is ignored (always OTLP) |
| `OTEL_EXPORTER_OTLP_PROTOCOL` (and per-signal) | all | Only `http/protobuf` is supported. Any other value: OTLP stays **off** in that process and one WARNING names the variable and the supported value |
| `OTEL_EXPORTER_OTLP_HEADERS` (and per-signal) | all, through the exporters | Honoured. **A credential**: never logged, in any form. The one INFO line init writes names the endpoint as `scheme://host:port` only |
| `OTEL_EXPORTER_OTLP_TIMEOUT`, `…_CERTIFICATE`, `…_CLIENT_KEY`, `…_CLIENT_CERTIFICATE`, `…_COMPRESSION` | all, through the exporters | Honoured |
| `OTEL_RESOURCE_ATTRIBUTES` | all | **Trusted operator configuration** (R-Q18, D13): passed through to the OTLP resource as configured; never exposed on `/metrics` |
| `OTEL_SERVICE_NAME` | — | Ignored, because one container runs several services. The docs page says so |
| `OTEL_TRACES_SAMPLER_ARG` | all | D11 |
| `OTEL_TRACES_SAMPLER` | — | Ignored (D11) |
| `OTEL_BSP_*`, `OTEL_BLRP_*`, `OTEL_METRIC_EXPORT_INTERVAL`, `OTEL_METRIC_EXPORT_TIMEOUT` | all, through the SDKs | Honoured; SDK defaults otherwise (60 s metric interval) |
| `OTEL_SDK_DISABLED` | all | `true` forces OTLP off |
| `MINO_LOG_FORMAT` | all | D8 |

Supervisord passes its own environment to every program it starts, and every `[program:x]` in
`docker/supervisord.d/` adds to it with `environment=` rather than replacing it, so a variable
set on the container reaches the relay, both uWSGIs, Daphne, both Celery workers and beat. No
compose file sets any of them; the docs page shows how.

### D13 — Names, and how this sequences against the rename (R12)

- **Metric prefix** `mino_`, then the service (`relay`, `api`, `worker`), then the quantity
  (§ Metric catalogue).
- **`service.name`**: `mino-relay` (the Go relay), `mino-api` (`api-uwsgi`, `relay-uwsgi` and
  `daphne`: all three run the Django app and urlconf), `mino-worker` (both Celery workers and
  beat). The process is distinguished by the resource attribute `mino.program`, set to the
  supervisord program name (`relay-go`, `api-uwsgi`, `relay-uwsgi`, `daphne`, `celery-default`,
  `celery-dvr`, `celery-beat`), and `service.instance.id`, a random UUID per process. The
  three-name ruling is kept; `mino.program` is what lets a query separate the VOD relay from the
  API without a fourth name.
- **`OTEL_RESOURCE_ATTRIBUTES` is trusted operator configuration** (owner ruling R-Q18,
  2026-11-01). It is in the same class as `OTEL_EXPORTER_OTLP_HEADERS`: the operator writes it
  into the container's environment, alongside the OTLP credential it already trusts that
  environment with, and anyone who can change it can already change where telemetry goes. So it
  **passes through to the OTLP resource as configured**, in both languages, with no allowlist,
  no value rule and no environment manipulation. Round 2's allowlisted resource and round 3's
  scoped override are withdrawn.

  Our own code adds only fixed attributes, and they win over a same-named environment value:
  - `service.name` (D13 above);
  - `service.version`: `version.py`'s `__version__` in Python; in Go,
    `debug.ReadBuildInfo().Main.Version` when it is not `(devel)`, and omitted otherwise;
  - `mino.program`;
  - `service.instance.id`, a random UUID per process. It is not configuration and carries
    nothing; it is what keeps four uWSGI workers' cumulative counters from merging into one
    series. It is kept beside the three fixed attributes and listed in § Open items.

  The SDK adds its own `telemetry.sdk.*`. `OTEL_SERVICE_NAME` is still ignored (D12), because the
  process's own `service.name` wins.
  - **Python uses the standard merge.**
    `Resource.create({"service.name": …, "service.version": …, "mino.program": …, "service.instance.id": …})`
    reads `OTEL_RESOURCE_ATTRIBUTES` and `OTEL_SERVICE_NAME` and lets the passed attributes win.
    **Measured** on SDK 1.45.2 (round 1) with
    `OTEL_RESOURCE_ATTRIBUTES=service.name=evil,mino.program=evil,foo=bar` and
    `OTEL_SERVICE_NAME=evil2`: the result carried `mino-api`, `api-uwsgi` and `foo=bar`. Building
    `Resource(attrs)` directly is no longer needed: it would discard the operator's attributes,
    which R-Q18 says to pass through. One `Resource` object is passed to the tracer, meter and
    logger providers.
  - **Go uses the SDK's own `WithResource`**, which merges `resource.Environment()` underneath
    the given resource (`sdk/trace/provider.go:393`, `sdk/metric/config.go:118`,
    `sdk/log/provider.go:304` in v1.47.0). **Measured** in round 2: environment keys passed
    through, and the passed `service.name` won over `OTEL_SERVICE_NAME`. That is now the
    intended behaviour. No process environment variable is ever set or unset, so profile
    executables inherit exactly what they inherit today.
- **`/metrics` never carries the resource.** The endpoint is unauthenticated (D6), and operator
  configuration does not belong on it. The exporter keeps `WithoutTargetInfo` and
  `WithoutScopeInfo` (D4). **Measured** on v0.69.0 with
  `OTEL_RESOURCE_ATTRIBUTES=evil.key=S3NT1NEL-pw-9d2f`: with both options the scrape contained
  neither the sentinel nor a `target_info` family; without them it contained both.

  O2 pins this with `TestMetricsEndpointCarriesNoResource`. It sets that sentinel with
  `t.Setenv`, initialises telemetry, records every catalogue instrument and scrapes `/metrics`
  from an `httptest.Server`. It asserts:
  - the sentinel is absent;
  - there is no `target_info` family;
  - there is no `otel_scope_` label.

  There are two separate break-checks, each measured on its own (2026-11-04):
  - Drop `WithoutTargetInfo` only: the test reddens on the sentinel and on `target_info`, while
    the scope assertion stays green.
  - Drop `WithoutScopeInfo` only: the test reddens on `otel_scope_`, while the sentinel and
    `target_info` assertions stay green.
- **Scope names**: `mino/relay`, `mino/api`, `mino/worker`.
- **The new environment variable is `MINO_LOG_FORMAT`**, born under the new prefix. Rename PR E1
  (`2026-10-28-mino-rename-design.md`, C-7/C-8) aliases `DISPATCHARR_<rest>` to `MINO_<rest>`; no
  `DISPATCHARR_LOG_FORMAT` has ever existed, so nothing needs aliasing and E2's refusal cannot
  catch it. This spec introduces no `DISPATCHARR_*` name.

**Sequencing against the rename PRs.** Neither programme waits for the other, and neither
reorders the other. The interactions are mechanical:

| Rename PR | Effect on this spec's PRs |
|---|---|
| R1 (the `dispatcharr` name ratchet, `scripts/check_product_name.py`) | If R1 has merged when an O-PR is cut, every file that PR adds or edits whose count of "dispatcharr" rises (a `from dispatcharr.observability import …` line, the `dispatcharr.observability.*` class paths in `LOGGING`) needs a regenerated `scripts/product_name_allowlist.txt` with the reason in the PR body: the `dispatcharr` Python package is a kept identifier (rename spec C-10). The new Go and docs files avoid the word except where they name a kept path |
| G1 (Go module path) | `relay/go.allowed-deps` holds third-party paths only and `check_go_deps.sh` reads the main module with `go list -m`, so G1 edits neither. G1 rewrites the `import` lines O2 and O4 add, as it rewrites every other. `scripts/coverage_relay_go.sh:102`'s module-path filter is G1's, not this spec's |
| E1/E2 (env vars) | None: no `DISPATCHARR_*` added. The relay still reads `DISPATCHARR_RELAY_GO_PORT` for the `/metrics` port, and E1 renames it with every other |
| W1 (`X-Dispatcharr-*` → `X-Mino-*`) | `X-Relay-Traceparent` is an `X-Relay-*` header, which W1 keeps. D11's trust checks call `IsRelayTrusted`/`_matches` and `internal_principal_token()`, which W1 renames in place. The two nginx includes gain one line each here and W1 edits the same files, so whichever lands second rebases a one-line conflict |
| C1/C2 (prose) | The docs page O7 adds says "Mino" for the product and names kept identifiers literally |
| T1 (dev-loop names) | None |

### D14 — The metric catalogue is frozen (R11)

The table in § Metric catalogue is the whole list. Adding, removing or relabelling an
instrument is an amendment to this spec, not an implementation choice. The views in D9 make an
uncatalogued Python instrument export nothing; in Go, `relay/telemetry`'s
`TestExpositionMatchesTheCatalogue` scrapes `/metrics` after recording every instrument once and
compares the set of `# TYPE` lines and each family's label keys with a literal copy of the
catalogue's Go rows.

### D15 — Deployment scope: one docs page and one example Collector config (R14)

O7 adds `docs/observability.md` and `docs/observability/otel-collector.example.yaml`
(§ Docs page outline). No Helm chart, Grafana dashboard, alert rule or compose change.

### D16 — Celery queue depth and provider slots are observed in beat

Queue depth and provider slots are deployment-wide numbers, and a gauge reported by every Celery
child would produce one stale series per child. They are therefore `ObservableGauge`s registered
only by the beat process (one per deployment, not forked), whose callbacks run on the metric
reader's export interval:

- `mino_worker_queue_depth{queue}`: `LLEN` of each queue in the closed set `celery`, `dvr`
  (`docker/supervisord.d/celery-default.conf`'s `-Q celery`, `celery-dvr.conf`'s `-Q dvr`,
  `dispatcharr/celery.py:80-82`), on the broker connection. Kombu's priority sub-queues are not
  summed; the deployment sets no task priority, and the docs page says so.
- `mino_worker_provider_slots_in_use{m3u_profile_id}` and `…_limit{m3u_profile_id}`: one read of
  active `M3UAccountProfile` rows (`apps/m3u/models.py:245`, `max_streams` at `:260`,
  `is_active` at `:263`) and one `MGET` of `profile_connections:{id}`
  (`apps/m3u/connection_pool.py:22`, `get_profile_connection_count` at `:145` reads one). The
  callback reads; it never writes a counter, so #513's version rule is untouched. It closes its
  database connection after each run.

That reading of "queue depth via beat" (the ruling) is the planner's: observed in the beat
process rather than measured by a beat-scheduled task. A task would run in a worker child and
reintroduce the per-child stale series. It is listed in § Open items for the reviewer to
challenge.

### D17 — Coverage gates

- **Go.** O2 adds `relay/telemetry` and `relay/procstat` **unlinked** (nothing in the binary
  imports them yet). Under ruling R27 (Phase 4 spec D20) O2 shows each package's own coverage,
  ≥ 85%, CI-measured with the gate's flags, with a per-file uncovered listing. O2 also changes
  `relay/go.mod`, so `gomod=` in `scripts/coverage_relay_go.floor` no longer matches: O2 runs
  `--write-floor --shape-only` once and says in its body that this is a shape-only re-baseline
  (the floor's own "HOW TO MOVE" § distinguishes the two moves). `packages=` is unchanged in O2.
  O4 links both packages: it re-baselines `packages=`/`package_count` and may raise `missing` by
  the two listed amounts R27 allows (the packages' uncovered statements as O2 listed them,
  re-measured as the maximum of O4's ≥ 12-round CI census, plus O4's own new or changed uncovered
  statements at ≥ 85% on its additions), declared as `raise_from`/`raise_listed` for
  `scripts/check_floor_raise.sh`. `relay/main.go`'s new init lines are uncovered by construction,
  as 4a-3's were (the floor's provenance block); they are listed, not hidden.
- **Python Gate 2.** Three of the nine `scripts/coverage_live_path.coveragerc` modules are
  edited: `apps/proxy/next_source.py` (O3), and `apps/proxy/authorize_views.py` and
  `apps/proxy/internal_auth.py` (O6; the latter gains one header-name constant). Every new line is
  covered by that PR's tests, `missing` stays 33, and each PR runs
  `scripts/coverage_live_path_isolated.sh` before push (a green label does not imply a green
  gate). O5's propagator calls `internal_auth` functions without editing the module. No other
  Gate 2 module is touched.

## Metric catalogue

Names are OTel instrument names; the Prometheus column is what the relay's `/metrics` (Go rows)
or a Collector's Prometheus exporter (Python rows) renders, given the exporter's unit and
`_total` suffixing. **The Prometheus column is checked by O4's catalogue test for the Go rows;
for the Python rows it is informational**, because the Collector does the translation.

| # | Instrument | Type | Unit | Labels | Prometheus name | Measured at |
|---|---|---|---|---|---|---|
| M1 | `mino_relay_channels` | Int64ObservableGauge | `{channel}` | `state` (the `channel.State` values) | `mino_relay_channels` | `channel.Manager.Snapshot` (`relay/channel/manager.go:626`), `Channel.State` (`relay/channel/channel.go:229`) |
| M2 | `mino_relay_clients` | Int64ObservableGauge | `{client}` | `channel_id`, `format` (`mpegts`/`fmp4`/`hls`), `profile_id` | `mino_relay_clients` | `Channel.ClientSnapshot` (`channel.go:347`), `Client.OutputFormat` (`relay/channel/client.go:57`), `Client.OutputProfileID` (`:62`) |
| M3 | `mino_relay_client_sent` | Int64Counter | `By` | `channel_id`, `format` | `mino_relay_client_sent_bytes_total` | the returned `n` of every body `Write` through an **armed** `telemetry.FirstWriteWriter` (D11), partial writes included. `StreamHandler` and `HLSHandler` install it once per request, and it is armed only once setup has succeeded. `HLSHandler` arms inside its `write` helper (`relay/httpapi/hls.go:589-593`), immediately before a playlist or segment body, so its error answers are not counted. That covers media, keepalive, tail and error packets in `writeChunks` (`relay/httpapi/stream.go:1195-1208`, called at `:1095`, `:1125`, `:1159`, `:1165` and by fMP4), and the HLS playlist and segment writes (`relay/httpapi/hls.go:428`, `:590`). Keepalive packets count, as they do toward `bytes_sent` (`stream.go:1129`) |
| M4 | `mino_relay_failovers` | Int64Counter | `{failover}` | `channel_id`, `trigger` (`health_monitor`/`max_retries_exceeded`/`buffering_timeout`), `outcome` (`switched`/`no_alternate`/`unresolved`/`same_url`/`no_resolver`) | `mino_relay_failovers_total` | each return of `Channel.failover` (`relay/channel/failover.go:190`); the three trigger strings are its callers' (`channel.go:624`, `:635`, `failover.go:322`) |
| M5 | `mino_relay_hls_sessions` | Int64ObservableGauge | `{session}` | none | `mino_relay_hls_sessions` | `session.Table.Len` (`relay/session/table.go:549`; its "for tests" comment is corrected) |
| M6 | `mino_relay_rewind_disk_usage` | Int64ObservableGauge | `By` | none | `mino_relay_rewind_disk_usage_bytes` | `hls.Rewind.Bytes` (`relay/hls/rewind.go:189`) |
| M7 | `mino_relay_rewind_disk_limit` | Int64ObservableGauge | `By` | none | `mino_relay_rewind_disk_limit_bytes` | `hls.Rewind.Cap` (`rewind.go:182`); not observed while the cap is `math.MaxInt64` (unset, `:152`) |
| M8 | `mino_relay_process_cpu` | Float64ObservableCounter | `s` | `channel_id`, `kind`, `profile_id` | `mino_relay_process_cpu_seconds_total` | `relay/procstat` (Linux only), **accumulated over each process's lifetime** (§ M8 accounting below): `utime + stime` (fields 14 and 15 of `/proc/<pid>/stat`, `proc(5)`) of every process whose process group (field 5) is tracked, divided by `AT_CLKTCK` from `/proc/self/auxv` (100 if absent). Groups are registered when `ffmpeg.start` returns (`relay/ffmpeg/spawn.go:218-237`; `Setpgid` makes the leader's pid the group id, `:149-154`) and unregistered when `Process.Wait` returns (`:391`). Grouping is what counts a Streamlink or VLC profile's own ffmpeg child |
| M9 | `mino_relay_process_memory_rss` | Int64ObservableGauge | `By` | `channel_id`, `kind`, `profile_id` | `mino_relay_process_memory_rss_bytes` | the same scan: field 24 (`rss`, pages) × `os.Getpagesize()`, summed over the group |
| M10 | `mino_api_http_server_request_duration` | Histogram | `s` | `http.request.method`, `http.route`, `http.response.status_code` | `mino_api_http_server_request_duration_seconds` | the django instrumentation's `http.server.request.duration`, renamed by a D9 view (rate, errors and duration all come from this one histogram) |
| M11 | `mino_worker_task_duration` | Histogram | `s` | `task` (the registered task name), `outcome` (`SUCCESS`/`FAILURE`/`RETRY`/`REVOKED`, Celery's state) | `mino_worker_task_duration_seconds` | `task_prerun` records a monotonic start keyed by `task_id`; `task_postrun` records the duration with its `state` kwarg. Both handlers already exist (`dispatcharr/celery.py:85`, `:97`); one line is added to each |
| M12 | `mino_worker_queue_depth` | Int64ObservableGauge | `{message}` | `queue` (`celery`/`dvr`) | `mino_worker_queue_depth` | D16, beat only |
| M13 | `mino_worker_provider_slots_in_use` | Int64ObservableGauge | `{slot}` | `m3u_profile_id` | `mino_worker_provider_slots_in_use` | D16, beat only |
| M14 | `mino_worker_provider_slots_limit` | Int64ObservableGauge | `{slot}` | `m3u_profile_id` | `mino_worker_provider_slots_limit` | D16, beat only; `0` means unlimited, as `max_streams=0` does |

**M8 accounting** (finding 7). A sum over the processes alive at collection time would
**decrease** when one child exits while its siblings run on. A backend reads that drop as a
counter reset and computes a wrong rate. `relay/procstat` therefore keeps per-label-set
accumulators instead of reporting a sum:

- **Process identity** is `(pid, starttime)`, where `starttime` is field 22 of
  `/proc/<pid>/stat`. A reused pid has a different start time and is a new identity.
- **Each collection** reads every live member of every tracked group. For each identity it adds
  `cpu_now − cpu_last_seen` to that group's label set and stores `cpu_now`. A new identity's
  `cpu_last_seen` is 0, so its CPU since it started is counted once.
- **When an identity is missing** from a later collection (it exited and was reaped), its
  last-seen value is already in the accumulator, and nothing is subtracted. **What is lost is the
  CPU the identity accrued after its last successful observation** (finding 8). For a process that
  starts and exits between two observations, that is its whole lifetime. The loss is CPU time,
  not wall time: a multithreaded ffmpeg can accrue several CPU-seconds per elapsed second, and a
  slow or failed collection widens the gap. M8 is therefore a **lower bound** on the CPU the
  tracked groups used, exact for long-lived processes and not for short-lived ones. The docs page
  states this, and no numeric bound is claimed.
- **Unregistering** a group (at `Wait`) stops new reads for it. Its label set's accumulated
  value **stays** and keeps being reported. A cumulative counter must not fall, and the series
  lasts until the relay restarts (D7, Cardinality).
- **Several groups with one label set** (two pipelines of the same channel, kind and profile in
  turn) add into one accumulator.
- **The reported value** is the accumulator, so it never decreases.

M9 has no such rule: it is a gauge, and it is the sum of `rss` over the live members.

**Tests** (O2, `relay/procstat/accounting_test.go`). They are driven by an injected `/proc` reader
that returns scripted snapshots, so every expected value is exact:

1. **Overlap.** A tracked group holds a leader and a child: 2 s and 3 s, then 4 s and 5 s. The
   label set reports 5 s, then 9 s.
2. **Departure.** The child disappears in the next snapshot while the leader goes to 6 s. The
   report is 11 s (9 + 2). It is **not** 6 s.
3. **Replacement and pid reuse.** A new identity appears with the departed child's pid and a
   new `starttime` at 1 s. The report is 12 s, not a negative delta against the old 5 s.
4. **Two groups, one label set.** The accumulator is their sum.
5. **`untrack` is pinned directly.** After `untrack()`, the registry holds no entry for the
   group (`Registry.Groups()` is empty), a further snapshot listing its pids adds nothing, and
   the label set still reports its last accumulated value.
6. **A restart is a new counter epoch.**
   - Registry A, under meter provider A, accumulates to 12 s, as in tests 1–3.
   - A fresh registry B, under a fresh meter provider B, stands for a restarted relay. It tracks
     a new group whose first snapshot reads 0.5 s.
   - The test collects B through `telemetrytest` and asserts two things: its first point for the
     label set is **0.5 s**, not 12.5; and that point's start time is after A's last point's
     timestamp.

   That is the reset a backend expects at a process restart: the series starts again, and its
   start time says so. Break-check: make the accumulator package-global, so it survives a new
   `Registry`. Test 6 reddens with "12.5, want 0.5".

The break-checks are run against the same snapshots:
- Report the live sum instead of the accumulator: test 2 reddens with "6, want 11".
- Key identities by pid alone: test 3 reddens with a negative delta.
- Make `untrack` a no-op: test 5 reddens on the non-empty registry.

M8 and M9 are the CPU question. On a non-Linux build (`GOOS=darwin` lint and tests) `relay/procstat`
reports nothing and the two instruments have no points; `procstat_other.go` is a stub, and the
three-GOOS lint in `go-tests.yml` already covers both halves of a build-tag split.

## Span catalogue

Go spans (scope `mino/relay`). Every attribute below is on D9's Go allowlist; nothing else is.

| Span | Kind | Parent / links | Attributes | Starts / ends |
|---|---|---|---|---|
| `relay.tune` | Server | trusted `X-Relay-Traceparent` (D11) or root | `mino.channel_id` (int, once known), `mino.output_format`, `mino.tune.joined` (bool), `mino.outcome` (`streaming`/`redirect`/`refused`/`failed`/`draining`/`abandoned`), `http.route` (the mux pattern), `http.response.status_code` | owned by `StreamHandler`: from its entry (`relay/httpapi/stream.go:228`) to the first successful body write (`FirstWriteWriter`), or to the handler's return on failure or abandonment |
| `relay.authorize` | Client | `relay.tune` | `mino.outcome` (`allowed`/`denied`/`unavailable`), `http.response.status_code` | around `control.Client.Authorize` (`relay/control/authorize.go:140`), dev shape only |
| `relay.next_source` | Client | `relay.tune` or `relay.failover` | `mino.next_source.reason` (`tune`/`failover`/`resume`), `mino.outcome` (`source`/`no_source`/`blocked`/`refused`/`unavailable`), `http.response.status_code` | around `control.Client.NextSource` (`relay/control/nextsource.go:384`) |
| `relay.failover` | Internal | root; link to the channel's `relay.tune` | `mino.channel_id`, `mino.failover.trigger`, `mino.outcome` (M4's set) | `failover.go:190` / each return |
| `relay.stream_switch` | Server | Django's `requests` client span, through the trusted internal route (D11); a link to the channel's `relay.tune` | `mino.channel_id`, `mino.outcome` (`applied`/`unchanged`) | owned by `AdvanceHandler` (`relay/httpapi/control.go:235`): around its `ch.Advance(…)` call (`:308`) |

Python spans are the five instrumentations' own; this spec adds none. The authorize request's
server span is the trace root for a tune behind nginx.

## Log record schema

Both languages, `MINO_LOG_FORMAT=json`, one JSON object per line:

| Key | Python | Go | Notes |
|---|---|---|---|
| `time` | `record.created` as RFC 3339 UTC with microseconds | slog's own (RFC 3339 nano) | |
| `level` | `record.levelname` (`TRACE` for level 5, which the repo uses) | slog's (`DEBUG`/`INFO`/`WARN`/`ERROR`) | |
| `msg` | `redact_text(record.getMessage())` | `scrub(msg)` in `SafeHandler` | |
| `logger` | `record.name` | absent | |
| `service.name` | D13 | D13 | |
| `mino.program` | D13 | `relay-go` | |
| `trace_id`, `span_id` | from `opentelemetry.trace.get_current_span()` when its context is valid, lower-case hex | from the record's context when valid | absent, never empty, when there is no span |
| `exception.type` | `type(exc).__qualname__` with its module | absent (errors are attributes) | |
| `mino.exception.frames` | list of `"file:line in function"`, innermost last; no source text, no message | absent | |
| `channel_id` | absent | from a `channel`-class key (D9) | the numeric id; `"0"` when unknown |
| any other key | absent (`extra=` fields are not serialised) | the call's own attributes as `SafeHandler` classifies them | |

## Versions checked

Read on 2026-10-31. These are floors for the implementer's own tool resolution, not pins
(Global constraint 9).

How each was read: Go module versions with `go list -m -versions <module>` against the module proxy
(Go 1.27.3); Python versions from `https://pypi.org/pypi/<name>/json`; behaviour by installing the
packages into scratch environments and running the probes named in the decisions. "Measured" in
this spec means one of those probes; "read" means the installed source; "inferred" means neither.

| Component | Latest on 2026-10-31 | How it was checked |
|---|---|---|
| `go.opentelemetry.io/otel`, `/otel/sdk`, `/otel/sdk/metric`, `/otel/sdk/log`, `/otel/log`, `/otel/metric`, `/otel/trace` | v1.47.0 | `go list -m -versions`; built and run in a prototype module |
| `go.opentelemetry.io/otel/exporters/otlp/otlptrace/otlptracehttp`, `…/otlpmetric/otlpmetrichttp` | v1.47.0 | same |
| `go.opentelemetry.io/otel/exporters/otlp/otlplog/otlploghttp` | v0.23.0 | same (pre-1.0, so a minor bump may break; Renovate's grouped, human-merged update is the control) |
| `go.opentelemetry.io/otel/exporters/prometheus` | v0.69.0 | same; exposition names below measured |
| `go.opentelemetry.io/contrib/bridges/otelslog` | v0.21.0 | same |
| `github.com/prometheus/client_golang` | v1.25.0 | same |
| `golang.org/x/vuln` (govulncheck) | v1.9.0 | `go list -m -versions` |
| `opentelemetry-api`, `opentelemetry-sdk`, `opentelemetry-exporter-otlp-proto-http` | 1.45.2 (requires Python ≥ 3.10; the repo requires ≥ 3.13, `pyproject.toml:6`) | PyPI JSON; installed and probed |
| `opentelemetry-instrumentation-django`, `-celery`, `-psycopg`, `-redis`, `-requests`, `-logging` | 0.66b2 | PyPI JSON; installed; Django 6.0.8 installed beside it without conflict |
| `protobuf` (new transitive dependency of the OTLP exporter; not in `uv.lock` at the seed) | 7.36.2 | PyPI JSON |
| gevent | 26.7.0 (the repo's pin, `pyproject.toml`) | the gevent probe in D10 |

**What was measured about the Go Prometheus exporter.** The exporter was built with D4's four
options (a private registry, `UnderscoreEscapingWithSuffixes` pinned, `WithoutTargetInfo`,
`WithoutScopeInfo`) and served by `promhttp.HandlerFor`. v0.69.0 rendered:
- `mino_relay_channels{state="active"}` (unit `{channel}`, gauge, no suffix);
- `mino_relay_client_sent_bytes_total{channel_id,format}` (unit `By`, counter);
- `mino_relay_process_cpu_seconds_total{kind}` (unit `s`, observable counter);
- `mino_relay_process_memory_rss_bytes` (unit `By`, gauge).

No series carried an `otel_scope_*` label and there was no `target_info` family. Without the two
`Without…` options, every series also carried `otel_scope_name`, `otel_scope_schema_url` and
`otel_scope_version`, and a `target_info` gauge carried the resource (also measured). That is
why both options are required (D9).

**What was measured about exemplars.** In both languages, with the SDK defaults, a histogram
recorded inside a sampled span exported a View-excluded secret attribute in the exemplar. With
the filter set to always-off, it did not (D9; Python 1.45.2, Go v1.47.0).

**What was measured about late Django instrumentation.** See D10: instrumenting after
`get_wsgi_application()` produced no span.

**What was measured about Celery's `worker_init`.** See D10: `pool_cls` was `'threads'` or
`'prefork'`, unresolved, when the signal fired.

**What upstream sources confirmed** (the research subagent's report, read against source and
docs on 2026-10-31):

- **uWSGI does not run Python's at-fork hooks** in a worker unless `py-call-osafterfork` or
  `py-call-uwsgi-fork-hooks` is set (`unbit/uwsgi` `plugins/python/python_plugin.c:197-198,448-480`).
  None of this repo's inis sets either. D10 does not rely on the hooks.
- **`uwsgidecorators.postfork`** sets `uwsgi.post_fork_hook`, which the Python plugin calls in
  every worker after the fork. Whether a hook registered *during* lazy app loading also fires for
  that same worker was not established. D10 calls `init` directly at import as well, and the pid
  guard makes the two calls one.
- **Daphne has no ASGI lifespan support** (django/daphne #264 and PR #570, both open), so D10
  uses import time.
- **The Django instrumentation covers Django's ASGI HTTP requests but not Channels WebSocket
  consumers**, which never pass through Django middleware. Daphne serves only WebSockets here
  (`docker/supervisord.d/daphne.conf`). Its process is initialised for its log records, outbound
  calls, and database and Redis spans, and WebSocket consumers are not traced.
- **Celery's instrumentation docs** say to initialise in `worker_process_init`.
- **gevent** has given each greenlet its own `contextvars` context since 20.9 (gevent docs). That
  is consistent with D10's measurement.

**What was not verified, and is not relied on.** Only one thing: whether a `postfork` hook
registered during lazy app loading fires for the worker that registered it. D10 designs around it.
Everything else this spec relies on was either measured here or read in upstream source.

## Go modules

**The candidate allowlist.** O2's `relay/go.allowed-deps` is the set of direct requirements
`go mod tidy` leaves once `relay/telemetry` imports what D4, D8 and D11 need, and it must be a
subset of this list. A module outside it is an amendment to this spec and ADR 0011, not an
implementation choice.

```
github.com/prometheus/client_golang
github.com/prometheus/otlptranslator
go.opentelemetry.io/contrib/bridges/otelslog
go.opentelemetry.io/otel
go.opentelemetry.io/otel/exporters/otlp/otlplog/otlploghttp
go.opentelemetry.io/otel/exporters/otlp/otlpmetric/otlpmetrichttp
go.opentelemetry.io/otel/exporters/otlp/otlptrace/otlptracehttp
go.opentelemetry.io/otel/exporters/prometheus
go.opentelemetry.io/otel/log
go.opentelemetry.io/otel/metric
go.opentelemetry.io/otel/sdk
go.opentelemetry.io/otel/sdk/log
go.opentelemetry.io/otel/sdk/metric
go.opentelemetry.io/otel/trace
```

**Measured footprint.** A prototype module (Go 1.27.1 directive, built with 1.27.3) importing the
three OTLP/HTTP exporters, the three SDK providers, the `otelslog` bridge, the Prometheus exporter
and `promhttp`, with the naming strategy pinned, resolved to **12 direct requirements** (the list
above minus `otel/log` and `otel/trace`, which the prototype did not import by name), **116
modules in the graph** and
**34 third-party modules linked** into the binary:

```
github.com/beorn7/perks                 go.opentelemetry.io/otel/exporters/otlp/otlptrace
github.com/cenkalti/backoff/v5          go.opentelemetry.io/otel/exporters/otlp/otlptrace/otlptracehttp
github.com/cespare/xxhash/v2            go.opentelemetry.io/otel/exporters/prometheus
github.com/go-logr/logr                 go.opentelemetry.io/otel/log
github.com/go-logr/stdr                 go.opentelemetry.io/otel/metric
github.com/google/uuid                  go.opentelemetry.io/otel/sdk
github.com/grpc-ecosystem/grpc-gateway/v2  go.opentelemetry.io/otel/sdk/log
github.com/munnerz/goautoneg            go.opentelemetry.io/otel/sdk/metric
github.com/prometheus/client_golang     go.opentelemetry.io/otel/trace
github.com/prometheus/client_model      go.opentelemetry.io/proto/otlp
github.com/prometheus/common            golang.org/x/net
github.com/prometheus/otlptranslator    golang.org/x/sys
go.opentelemetry.io/auto/sdk            golang.org/x/text
go.opentelemetry.io/contrib/bridges/otelslog  google.golang.org/genproto/googleapis/api
go.opentelemetry.io/otel                google.golang.org/genproto/googleapis/rpc
go.opentelemetry.io/otel/exporters/otlp/otlplog/otlploghttp  google.golang.org/grpc
go.opentelemetry.io/otel/exporters/otlp/otlpmetric/otlpmetrichttp  google.golang.org/protobuf
```

Two consequences of that list, both measured:

- **`google.golang.org/grpc` is linked** even though no gRPC exporter is. `go mod why -m
  google.golang.org/grpc` names `otlploghttp` → `go.opentelemetry.io/proto/otlp/collector/logs/v1`
  → `google.golang.org/grpc`: the OTLP collector packages carry their gRPC service stubs.
  ADR 0011 records it; it is in govulncheck's and the scanners' view like every other module.
- **`database/sql/driver` is linked** (through `github.com/google/uuid`); `database/sql` is not.
  Hence D2's ban on `database/sql` exactly.

A program linking only these modules is 24.8 MB for `GOOS=linux GOARCH=amd64`; the relay at the
seed SHA is 12.6 MB for the same target (both without `-s -w`; the Dockerfile strips its build).
The Dockerfile's `relay-builder` stage builds from the module proxy already; O2 restores the
`go mod download` layer its own comment (`docker/Dockerfile:38-43`) asks for with the first
dependency (Appendix A.3).

## PR sequence

Sequential, each off `origin/main` at its own cut, each a draft until its internal review passes.
O1, O3 and O5 depend on nothing and may be cut in any order; O2 needs O1 (the allowlist and the
credlint importer must exist before the first dependency); O4 needs O2 and O3; O6 needs O4 and
O5; O7 needs O6.

| PR | Branch | One line |
|---|---|---|
| O0 | `docs/observability-spec` | This spec and ADR 0011 |
| O1 | `ci/go-deps-gate` | Replace the stdlib-only check with the allowlist and driver ban; credlint imports modules and knows the OTel sinks; govulncheck, OSV, Trivy/Grype on `relay/`, Renovate, depguard |
| O2 | `feat/relay-telemetry-packages` | `relay/telemetry` and `relay/procstat`, unlinked; the OTel modules enter `go.mod` |
| O3 | `feat/next-source-channel-pk` | `channel_pk` on the next-source answer |
| O4 | `migration/relay-observability` | Link telemetry into the relay: `/metrics`, M1–M9, the relay spans, JSON slog, `X-Relay-Traceparent` through nginx |
| O5 | `feat/python-otel-bootstrap` | Python dependencies, `dispatcharr/observability`, post-fork init, five instrumentations, redaction, JSON logs, the trusted propagator, the checker extension |
| O6 | `feat/python-otel-metrics-and-tune-root` | M10–M14, and the authorize view's `X-Relay-Traceparent` |
| O7 | `docs/observability-deploy` | `docs/observability.md`, the example Collector config, CLAUDE.md's operational paragraph |

Every PR below: draft until its internal review passes (`fable` from round one); body ends with the
attribution line the dispatch gives; no closing keyword unless it lands a fix for a named issue;
the CLAUDE.md facts it changes corrected in the same PR. "Hooks" lists what the PR's paths trip
under CLAUDE.md § Test hooks; "CI" lists the aggregates that must be green.

### O1 — the dependency gate, before any dependency

**Changes.** Appendix A.2 in full (byte-exact against the seed): delete
`scripts/check_go_stdlib_only.sh`; add `scripts/check_go_deps.sh` and an empty-bodied
`relay/go.allowed-deps`; `go-tests.yml` runs the new script, adds the `govulncheck` job and puts it in
`Go result`'s `needs`, and its `changes` pattern names the new script; `vuln-scan.yml` adds
`relay/go.mod`/`relay/go.sum` to OSV-Scanner and both path filters, and the `go-modules` job;
`renovate.json` adds the `gomod` rules and the govulncheck custom manager; `.golangci.yml` adds the
two depguard rules; the comment references in `scripts/coverage_relay_go.sh:98`, `relay/hls/doc.go:28`
and `.claude/skills/implement-review-escalate/references/project.md:9` follow the rename. Not in the
appendix, because the implementer writes them: `relay/internal/credlint/check.go`'s `NewChecker`
lookup (D2) and its two new `Sinks`, with `check_test.go` cases; `docs/supply-chain.md`
§ Dependency integrity and § Vulnerability scanning gate, one paragraph each naming the allowlist,
govulncheck and the `go-modules` job; CLAUDE.md, Appendix A.5's six substring replacements.

**Tests and break-checks.**

| Test | Break-check (run, red message recorded in the PR body, reverted) |
|---|---|
| `scripts/tests/test_check_go_deps.sh` (new, bash, run by the `build` job step A.2 adds; `lint.yml` runs `test_check_floor_raise.sh` at `:236` but has no Go toolchain): builds throwaway modules under `mktemp -d` with `go mod init` and a `GOFLAGS=-mod=mod`-free, `GOPROXY=off` environment built from an allowlist (`PATH`, `HOME`, `GOCACHE`, `GOMODCACHE`, `GOTOOLCHAIN=local`, `LANG`), and asserts the six cases the planner ran: clean (0), unlisted direct requirement (1, names it), listed (0), stale allowlist line (1, names it), linked `database/sql` (1), linked package with a `redis` path segment (1). It adds a seventh, **positive control**: a module whose `main` imports only `database/sql/driver` exits 0. That pins the intentional exemption (§ Go modules). The third-party cases use a local `replace` to a module inside the temp directory, so no network is needed | **Remove the `^database/sql$|` alternative from the ban regex outright.** Measured on a scratch module: the real script exits 1 for a `main` importing `database/sql`, and the mutated script exits 0, so the case reddens with "expected exit 1, got 0". Replacing the pattern with `^database/sql/driver$`, round 2's proposal, would **not** kill it (round 3 finding 5): a program importing `database/sql` also links `database/sql/driver`. Also measured: the driver-only positive control passes the real script (`OK: …`). Then drop the `comm -13` half: the stale-line case reddens |
| `relay/internal/credlint/check_test.go`: a source-text case for each new sink (`span.RecordError(err)` on a stub `go.opentelemetry.io/otel/trace` package; `otel.Handle(err)`), each reported; and a case that `NewChecker`'s importer resolves a non-module, non-standard package through the export lookup | Remove `(go.opentelemetry.io/otel/trace.Span).RecordError` from `Sinks`: the RecordError case reddens naming the missing finding |
| depguard: `golangci-lint run` stays at zero findings on the tree | In a scratch commit, add `import _ "go.opentelemetry.io/otel"` to a file in `relay/buffer`: lint reports `import 'go.opentelemetry.io/otel' is not allowed from list 'otel-confined'` (measured by the planner on a scratch copy). Not committed |
| govulncheck: green on the seed module (no dependencies; standard library at the toolchain `relay/go.mod` names) | Not break-checked by edit: a deliberately vulnerable dependency cannot be added without adding a dependency. The PR body records one run's output |
| Renovate: `npx --yes renovate-config-validator renovate.json` passes (run locally; not in CI) | — |

**Hooks.** `.github/workflows/*.yml` (zizmor, blocking: the planner ran zizmor 1.31.1 offline over
both edited workflows, zero findings, and actionlint, whose one finding at `vuln-scan.yml:240` is
pre-existing, SC2013 in the accepted-risk expiry step); `*.go` (the Go hook: build, vet, `test -race`
for `internal/credlint`, credlint, golangci-lint ×3); commit gate: Go section. **CI:** `Go result`
(now including `govulncheck`), `Vulnerability Scan` (its path filter now matches), lint. Go coverage:
`relay/internal/credlint` is not linked, so the floor does not move; `relay/hls/doc.go` is a comment.

**PR description draft.**

> Replaces the relay's stdlib-only check with a dependency allowlist and a driver ban, before any
> dependency arrives (observability spec `docs/superpowers/specs/2026-10-31-observability-design.md`,
> D2 and D3; ADR 0011). `scripts/check_go_deps.sh` fails when `relay/go.mod`'s direct requirements
> differ from `relay/go.allowed-deps` (empty here), when the binary links `database/sql` or a Redis
> or Postgres driver, or when `go.mod` is untidy. credlint learns to type-check module-cache
> packages and to treat `Span.RecordError` and `otel.Handle` as sinks. govulncheck blocks in
> `Go result`; OSV-Scanner, Trivy and Grype read `relay/go.mod`; Renovate holds Go modules for a
> week; depguard keeps OTel in `relay/telemetry`. Tests and break-checks: see below.

### O2 — `relay/telemetry` and `relay/procstat`, unlinked

**Changes.**

- `relay/go.mod`/`relay/go.sum`: the § Go modules requirements, resolved with `go get` at their
  latest versions on the day; `relay/go.allowed-deps` lists exactly the direct set.
- `docker/Dockerfile`: Appendix A.3 (the `go mod download` split its own comment asks for).
- `relay/procstat` (stdlib only): `procstat_linux.go` scans `/proc/[0-9]*/stat` once per call,
  parsing past the last `)` (the command name may contain spaces and parentheses), and sums fields
  14+15 and 24 by field 5 (pgrp) for the registered groups; `AT_CLKTCK` from `/proc/self/auxv`
  (entries are pairs of native-word integers; type 17), falling back to 100. `procstat_other.go`
  returns nothing. A `Registry` with `Track(pgid int, l Labels) (untrack func())`, safe for
  concurrent use.
- `relay/telemetry`: `Config` from the environment (D12), `Init(ctx, Config) (*Telemetry, error)`
  returning the `/metrics` handler, a `Shutdown(ctx)` and typed recorders for M1–M9; the three
  redacting exporters, `SafeHandler` and its classes (D9); the resource with our fixed attributes
  over the standard environment merge (D13);
  `ContextHandler` and the JSON handler (D8); the sampler (D11); `FirstWriteWriter`, the typed
  span API (`StartTune`, `StartFailover`, `InjectTraceparent`, the opaque `Span` and `SpanRef`)
  and its attribute constants (§ Span catalogue); and `CatalogueGo`, the literal rows D14's test
  compares. It imports `relay/redact` and `relay/procstat`. Nothing in the binary imports it yet.
- `relay/telemetry/telemetrytest`: the test-only recording helpers (D11). Tests import it, the
  binary does not, and it sits inside `otel-confined`'s exempt path.
- `scripts/coverage_relay_go.floor`: `--write-floor --shape-only` for the new `gomod=` (shape-only
  move, said in the body); `packages=` unchanged.

**Tests.** `relay/procstat`: parsing fixtures (a `stat` line with `) (` in the name; a group of three
pids, two in the tracked group), the auxv parser on a fixture, and on Linux a live test that spawns
`sleep` with `Setpgid`, tracks it, and sees a non-negative CPU figure and a positive RSS.
`relay/procstat`: the five accounting tests in § M8 accounting. `relay/telemetry`: the Go span,
metric and `/metrics` rows of D9 (the log row's *real-call* cases need the census and the
wiring, so they land in O4; O2 drives `SafeHandler` with synthetic records of each class, `With`,
groups and `KindAny` errors); `TestExpositionMatchesTheCatalogue` (D14);
`TestOTLPOffInstallsNoProvider` (no endpoint ⇒ `otel.GetTracerProvider()` is the no-op and no
goroutine was started, by `runtime.NumGoroutine` before and after); `TestProtocolOtherThanHTTPProtobufStaysOff`;
`TestSamplerArg` (unset ⇒ 1.0; `0.25` ⇒ ratio 0.25; `x` ⇒ 1.0 and one warning); the JSON handler's
keys (§ Log record schema); `TestMetricsEndpointCarriesNoResource` (D13); and
`TestExemplarsOff` (a recording inside a sampled span exports no exemplar).

**Break-checks.** Each of D9's isolated Go mutations for the rows O2 carries, and § M8 accounting's
three. For `TestExpositionMatchesTheCatalogue`:
rename `mino_relay_hls_sessions` to `mino_relay_hls_session` in the instrument constructor; the test
names the missing and the unexpected family. For procstat grouping: read only the leader; the
three-pid fixture reddens with the leader-only figure.

**Coverage (R27).** Both packages are unlinked, so outside the floor's denominator. The PR shows each
package's per-package coverage ≥ 85%, CI-measured with `-count=1 -race -covermode=atomic` (the blocks
are in the CI artifact, reported out of scope), with a per-file uncovered listing that O4 re-measures.

**Hooks.** `*.go` (Go hook), commit gate Go section, `docker/Dockerfile` (no hook; hadolint in
`lint.yml`). **CI:** `Go result`, lint (hadolint), `Vulnerability Scan` (path filter matches
`relay/go.mod`), CodeQL (`relay/**`).

**PR description draft.**

> Adds `relay/telemetry` (the relay's only OpenTelemetry code) and `relay/procstat` (per-process-group
> CPU and memory from `/proc`), not yet linked into the binary (observability spec O2; ADR 0011). The
> OTel Go SDK, its OTLP/HTTP exporters, the Prometheus exporter and the `otelslog` bridge enter
> `relay/go.mod`, each on `relay/go.allowed-deps`. The Dockerfile's relay stage downloads modules in
> its own layer. The coverage floor's `gomod=` is re-baselined (shape only; `missing` unchanged);
> both new packages show ≥ 85% of their own, per ruling R27, listed below.

### O3 — `channel_pk` on the next-source answer

**Changes.** D7's Django half: `NextSourceResponseSerializer.channel_pk`
(`apps/proxy/serializers.py:267`), set at every return of `resolve_source`
(`apps/proxy/next_source.py:956`, the object from `:1037`). The relay half is O4.

**Tests.** `apps/proxy/tests/` (label `apps.proxy.tests`): a channel tune answers
`channel_pk == channel.pk`; a failover answer carries the same; a previewed stream answers `None`;
the OpenAPI schema carries the field. `test_tune_path_query_ledger.py` passes **unchanged**.

**Break-check.** Compute the value as `Channel.objects.get(uuid=identifier).pk`: the ledger test
reddens naming the extra `dispatcharr_channels_channel` query. Then set it only on the initial-tune
return: the failover case reddens.

**Gate 2.** `next_source.py` is one of the nine; every new line is covered by the cases above,
`missing` stays 33, and `scripts/coverage_live_path_isolated.sh --gate` runs before push.

**Hooks.** `*.py` (credential check), `apps/proxy/tests/test_*.py` (whole package). **CI:**
`Backend result`, including `coverage-gate`.

**PR description draft.**

> Adds `channel_pk` to the next-source answer, so the relay can label its metrics by the channel's
> numeric id rather than its UUID (observability spec D7, O3). It is the object `resolve_source`
> already holds, so the tune path runs no new query; the query ledger test is unchanged. `null` for
> a previewed stream. The relay ignores the field until O4.

### O4 — link telemetry into the relay (`migration/relay-observability`)

**Changes.**

- `relay/main.go`: read `MINO_LOG_FORMAT` and install the slog default (D8) before `config.Load`
  (`:33`); `telemetry.Init` after it; pass the handler to `httpapi.New`; after `<-drained` (`:148`),
  `Shutdown` with a 2-second context. The drain's 15 s plus this 2 s stays inside `relay-go.conf`'s
  `stopwaitsecs=20`.
- `relay/httpapi/server.go`: `Config.Metrics`, registered as `GET /metrics` beside `/readyz`
  (`:60`), outside `DevRoutes`.
- `relay/control/nextsource.go`: `ChannelPK *int` on `NextSourceAnswer`; `traceparent` injected in
  `attempt` (`:451`) and in `authorize.go`'s `Authorize` (`:140`).
- `relay/channel`:
  - the channel's numeric id (from the answer at publish) and its publishing tune's span
    context (for links), carried in `Started` (`manager.go:130`);
  - the `telemetry.ChannelIDs` map, filled on publish and emptied on removal (D9);
  - M1 and M2 observed through `Manager.Snapshot` and `ClientSnapshot`;
  - M4 at each return of `failover`, which owns `relay.failover` (D11);
  - `Advance` is **unchanged**. `AdvanceHandler` (`relay/httpapi/control.go:235`) owns
    `relay.stream_switch` around its call at `:308` (D11).
- **Production code uses OTel only through `relay/telemetry`'s own typed API** (finding 7).
  `relay/channel`, `relay/httpapi`, `relay/control` and `relay/ffmpeg` import `relay/telemetry`
  and never `go.opentelemetry.io`. Span handles and stored span contexts are opaque
  `telemetry.Span` and `telemetry.SpanRef` values, and helpers such as
  `telemetry.StartFailover(ctx, link SpanRef) (context.Context, *Span)` and
  `telemetry.InjectTraceparent(ctx, http.Header)` hide the OTel types. `otel-confined` therefore
  holds for production code and, through `telemetrytest`, for tests.
- `relay/telemetry/logkeys.go`: the census-generated key classification table, and `SafeHandler`
  installed in front of the JSON handler and the `otelslog` bridge (D9).
- `relay/ffmpeg/spawn.go`: **the spawn API keeps its signatures** (finding 6). There are three
  exported wrappers, not four: `Start` (`:98`), `StartPiped` (`:113`) and `StartPipedExtra`
  (`:134`), all over the unexported `start` (`:138`). They are unchanged. Tracking is opt-in, by
  a new method:
  - `func (p *Process) Track(l procstat.Labels)` registers the process group (`p.PID()`, which
    `Setpgid` makes the group id) with `procstat.Default`.
  - `Wait` (`:391`) unregisters the group if it was tracked, after `cmd.Wait` returns.
  - An untracked `Process`, the default, behaves exactly as today. Because M8 counts an
    identity's CPU from zero (§ M8 accounting), CPU spent between `start` and `Track` is not
    lost.

  Production call sites, before → after (each gains one line after the start returns without
  error):

  | Site | Before | After |
  |---|---|---|
  | `channel/source_transcode.go:183` | `proc, err := ffmpeg.Start(ctx, s.Command, s.argv())` | unchanged, then `proc.Track(procstat.Labels{ChannelID: …, Kind: procstat.KindSource})` |
  | `output/profile.go:137` | `proc, err := ffmpeg.StartPiped(ctx, cfg.Command, cfg.Argv)` | unchanged, then `proc.Track(… KindOutput, ProfileID: cfg.ProfileID)` |
  | `output/fmp4.go:532` | `proc, err := ffmpeg.StartPiped(ctx, cfg.command(), cfg.argv())` | unchanged, then `proc.Track(… KindFMP4 …)` |
  | `output/fmp4.go:618` | `retry, startErr := ffmpeg.StartPiped(ctx, p.cfg.command(), p.cfg.argvNoBSF())` | unchanged, then `retry.Track(… KindFMP4 …)` |
  | `hls/pipeline.go:695` | `proc, err := ffmpeg.StartPiped(pctx, command, argv)` | unchanged, then `proc.Track(… KindHLS, ProfileID: …)` |
  | `hls/pipeline.go:891` | `proc, err := ffmpeg.StartPipedExtra(actx, command, argv, spawn.Extra)` | unchanged, then `proc.Track(… KindHLS …)` |
  | `hls/silence.go:123`, `hls/detect.go:184` | `ffmpeg.Start(…)` | unchanged, and **not** tracked (D7) |

  Existing test call sites are **unchanged**, call for call, and keep their assertions; none
  tracks, so each runs the default untracked path:
  - `relay/ffmpeg/spawn_test.go:33`, `:252`, `:264` (`Start`) and `:289` (`StartPiped`);
  - `relay/ffmpeg/spawn_linux_test.go:42` (`Start`);
  - `relay/ffmpeg/extra_test.go:35`, `:60`, `:85`, `:94` and `:97` (`StartPipedExtra`).

  The new `relay/ffmpeg/track_test.go` pins tracking:
  - `Track` registers the group;
  - `Wait` unregisters it;
  - a second `Wait` is harmless;
  - an untracked process never touches the registry.

  Break-check: drop the unregister from `Wait`, and the registry case reddens.
- `relay/httpapi`: `relay.tune` with D11's ownership (`StartTune`, `FirstWriteWriter` installed
  once in `StreamHandler`, `Fail` beside each failure branch, a deferred `End`); the same writer
  in `HLSHandler` for M3; the `session.Table.Len` comment.
- `relay/control`: `relay.authorize` and `relay.next_source`, owned by `Authorize` and
  `NextSource`.
- `docker/nginx.conf`, `docker/dispatcharr_api_params.conf`, `docker/dispatcharr_api_params_proxy.conf`:
  Appendix A.1.
- `e2e/tests/streaming-greybox/nginx-stream-buffering.spec.ts`: see the test table.
- `scripts/coverage_relay_go.floor` and `.floor.packages`: re-baselined and raised under R27 (D17).
- CLAUDE.md: § Architecture's `relay-go` paragraph gains `/metrics` beside `/healthz`/`/readyz`;
  § Auth's "six `X-Relay-*` params" becomes seven with the traceparent named.

**Tests.**

| Test | What it pins | Break-check |
|---|---|---|
| `relay/httpapi/server_test.go`: `GET /metrics` answers 200 with `DevRoutes` false; a nil `Metrics` registers nothing (404) | D4: always on, outside the dev flag | Move the registration inside `if cfg.DevRoutes`: the dev-routes-off case reddens with 404 |
| `relay/httpapi/trace_test.go`: D11's trace tests 1–6 and 2a–2f (whole graph; first byte while connected, as a keepalive, in a partial batch, and as tail-only; response unchanged; denial, draining, fMP4 output-start failure and success, each failure in both `Fail` orderings; M3's returned-`n` counting and exactly-once completion; failure before first byte; untrusted context ignored; operator switch parent and link; failover root and link), all through `telemetrytest` | D11 trust, ownership, propagation, first byte, disarming, M3 | Read `X-Relay-Traceparent` without consulting `IsRelayTrusted`: test 4 reddens naming the inherited trace id. Call `FirstByte` at handler return: test 2 reddens. Fire on the first `writeChunks` with media instead of the first write: 2a reddens. Construct the wrapper armed: 2e reddens on M3 in both orderings, and on the outcome in the write-first ordering (measured). Count only nil-error writes: 2f reddens "0, want 200". Give `Fail` its own once: 2f reddens on `TuneCompletions()` = 2 ("completion invoked 2 times, want 1", measured), and not on the span record, which the SDK's idempotent `End` keeps at one end. Start `relay.stream_switch` from `context.Background()`: test 5 reddens on the parent |
| `relay/telemetry/logs_test.go` **real-call cases** (D9's Go log row), each through a tee of a raw control handler and `SafeHandler` in front of **both** sinks, the JSON handler and the OTLP fan-out into an in-memory exporter: (1) `Channel.failover` on a channel with no resolver (`relay/channel/failover.go:195`); (2) a real fMP4 pipeline started with `output.Start` and a stand-in command (`sh -c "exit 0"`), whose logger is bound by the `With` at `relay/output/fmp4.go:529` and which emits `"the remux ended"` at `:612` (the reader returns nil at EOF, `:777-778`, so the record is reached through `generation` and `run`). Each case first asserts that the **control** saw the channel UUID, then that **neither sink** holds it and both hold `channel_id`. The round-2 fixture, an empty-command `StartProfile` (`output/profile.go:130-133`), emits no record and is **not** used | D9 finding 1, round 3 finding 4, round 4 finding 1 | D9's isolated `SafeHandler` mutations, each run against both cases; in each, the control assertion stays green while a sink assertion reddens |
| `relay/telemetry/logkeys_test.go`: re-runs the `go/ast` census over the module's non-test files and fails naming any literal slog key that the table does not classify, with its `file:line` | the allowlist cannot fall behind the code | Add `slog.Info("x", "new_key", 1)` to a scratch file in `relay/buffer`: reddens naming `new_key` and the file |
| `relay/control`: `attempt` and `Authorize` send `traceparent` equal to the ctx's span; the internal-request HMAC still verifies with the header present | D11 propagation, HMAC unchanged | Inject after signing into a copy of the body: the verify case reddens |
| `relay/channel/failover_test.go`: M4 incremented once per return with the right `trigger`/`outcome`; `relay.failover` linked to the tune span | M4, D11 | Count before the `ErrNoAlternate` branch: the outcome case reddens with `switched` where `no_alternate` was expected |
| `relay/channel` + `relay/procstat` on Linux: a transcode source with a real `sleep` argv is tracked with `kind=source` and the channel's numeric id while it runs; after `Wait`, `Registry.Groups()` no longer holds its group and M8's value for its label set has not decreased | M8/M9 wiring, the `Wait` hook | Remove the `untrack` call from `Wait`: reddens on the non-empty registry |
| `nginx-stream-buffering.spec.ts`, **added** assertions: (a) a new `PROXY_FORWARDED_RELAY_HEADERS = ['X-Relay-Traceparent']`, each `PROXY_BOUND_TARGETS` block has `auth_request_set $relay_traceparent` and `proxy_set_header X-Relay-Traceparent $relay_traceparent`; (b) both blanking includes blank it; (c) the sixth test, D6's three parts | D11 nginx half, D6 | Delete A.1's `proxy_set_header X-Relay-Traceparent` from `^~ /live/`: (a) reddens naming `/live/`. Add `location = /metrics { proxy_pass http://relay_go; }`: D6 parts 2 and 3 redden |

**Test changes listed** (finding 6), complete for O4:
- **Existing Go tests whose code changes: none.** The spawn wrappers keep their signatures and
  every existing call is unchanged; the call sites are listed under Changes. `Channel.Advance`
  is unchanged. `httpapi.Config.Metrics` and `NextSourceAnswer.ChannelPK` are additive, and a
  zero value keeps today's behaviour, so no test that builds either changes.
- **Existing e2e assertions: none change.** `nginx-stream-buffering.spec.ts` gains new
  constants and assertions, listed in the table above. One doc comment changes: on
  `RELAY_BOUND_TARGETS`, "the eight `auth_request_set` variables" gains "(nine on the three
  proxy-bound locations)".
- **New test files:** `relay/httpapi/trace_test.go`, `relay/ffmpeg/track_test.go`,
  `relay/telemetry/logs_test.go`'s real-call cases, `relay/telemetry/logkeys_test.go`, and the
  procstat wiring test.
The `guards` project's allowlists need no new line: the file is already on the subprocess allowlist
(`e2e/tests/guards/allowlist.ts:71`).

**Coverage (R27, D17).** Re-baseline `packages=`/`package_count` (12 → 14), and raise `missing` by
(a) `relay/telemetry` + `relay/procstat` uncovered as O2 listed them, re-measured as the maximum of
O4's ≥ 12-round CI census, plus (b) O4's own new or changed uncovered statements at ≥ 85% on its
additions, `relay/main.go`'s init block among them; `raise_from`/`raise_listed` declared.

**Hooks.** `*.go` (Go hook), `e2e/**/*.ts` (`tsc --noEmit`), commit gate Go section; nginx has no
hook. **CI:** `Go result`, `E2E result` (all projects: `migration/**`), `Lifecycle result`.

**PR description draft.**

> Links `relay/telemetry` into the relay (observability spec O4). `GET /metrics` on the relay's own
> port serves the catalogue's M1–M9, including CPU seconds and resident memory per ffmpeg process
> group labelled by channel, kind and Output Profile; nginx routes nothing to it, and a new grey-box
> test pins that. With `OTEL_EXPORTER_OTLP_ENDPOINT` set the relay also pushes metrics, traces and
> logs over OTLP/HTTP, through redacting exporters. A tune is traced from the authorize hop (whose
> context nginx now forwards as `X-Relay-Traceparent`, trusted only beside a valid relay marker)
> through next-source to the first byte; failovers and operator switches are linked spans.
> `MINO_LOG_FORMAT=json` switches the relay's log lines to JSON. Off by default: with neither
> variable set the only change is the new route. Coverage floor re-baselined and raised under R27,
> listed below.

### O5 — the Python bootstrap

**Changes.**

- `pyproject.toml`/`uv.lock`: `opentelemetry-api`, `opentelemetry-sdk`,
  `opentelemetry-exporter-otlp-proto-http`, `opentelemetry-instrumentation-django`, `-celery`,
  `-psycopg`, `-redis`, `-requests`, `-logging`, each pinned `==` to the version `uv lock` resolves
  (they release in lockstep, so the `==` pins move together).
- `dispatcharr/observability/` (new package): `config.py` (D12), `bootstrap.py` (D10),
  `redaction.py` (D9), `logs.py` (D8: `JsonFormatter`, `OtelBridgeHandler`), `propagation.py`
  (D11: `TrustedTraceContextPropagator`, `current_traceparent`), `metrics.py` (views, and the
  M11–M14 instruments O6 records).
- `dispatcharr/wsgi.py`, `dispatcharr/asgi.py`, `dispatcharr/celery.py`: D10's init points and
  flushes; nothing else in `celery.py` moves.
- `dispatcharr/settings.py`: D8's `LOGGING` changes.
- `scripts/check_credential_logging.py`: D9's telemetry call shape and two redactors.
- CLAUDE.md: § Known defects' "no metrics and no structured logs" is corrected in O7, not here;
  § Test hooks' credential-check line names the telemetry sinks.

**Tests** (label `tests` unless stated; all new):

| Test | Pins | Break-check |
|---|---|---|
| `tests/test_observability_redaction.py`: D9's Python rows, every instrumentation and sink with its own carrier cases and non-empty assertions | R7 | D9's isolated mutations, one per sink |
| `tests/test_observability_django6_sample.py`: O5's first task, recording the attribute keys each instrumentation emits on Django 6.0.8 (one request, task, query, Redis command and outbound call) and comparing them with the committed fixture; it doubles as the Django 6 compatibility smoke test (upstream's tox covers Django only up to 5.x) | D9's allowlist rests on a sample, not on memory; P2 | Delete the `DjangoInstrumentor` call: reddens with "no server span recorded" |
| `tests/test_observability_wsgi_cold_import.py` (D10) | init precedes the handler | D10's, measured |
| `tests/test_observability_gevent.py` (D10) | R8's gevent test | D10's, measured |
| `tests/test_observability_bootstrap.py`: endpoint unset ⇒ global providers are the API's proxies and `threading.active_count()` unchanged; set ⇒ SDK providers, and a second `init` in the same pid is a no-op; a fake pid change re-inits; `OTEL_EXPORTER_OTLP_PROTOCOL=grpc` ⇒ off with one WARNING; `OTEL_SDK_DISABLED=true` ⇒ off; the resource carries our four attributes, which win over same-named `OTEL_RESOURCE_ATTRIBUTES` keys and over `OTEL_SERVICE_NAME`, while other keys pass through (R-Q18); `OTEL_METRICS_EXEMPLAR_FILTER=always_on` leaves exemplars off | D10, D12, D13, D9 exemplars | Drop the pid guard: the second-`init` case reddens with two span processors |
| `tests/test_observability_propagation.py`: a WSGI environ with `HTTP_TRACEPARENT` and no internal header extracts nothing; with the valid static internal header extracts the parent; a Celery-shaped carrier extracts | D11 trust | Return `super().extract(...)` unconditionally: the no-header case reddens naming the inherited trace id |
| `tests/test_observability_logs.py`: `MINO_LOG_FORMAT` unset ⇒ `LOGGING` equal to the seed's dict (a literal copy in the test) plus the inert `otel` handler; `json` ⇒ one JSON object per line with § Log record schema's keys and trace ids inside a span; an unknown value ⇒ text and one WARNING without the value | D8 | Make `json` the default: the unset case reddens |
| `tests/test_uwsgi_inis_are_lazy.py` (D10) | lazy-apps assumption | Remove `lazy-apps = true` from a copy of `docker/uwsgi.relay.ini` in a temp dir passed to the test's helper: reddens naming the file |
| `tests/test_celery_otel_init.py`: through Celery's own startup, `app.WorkController(pool="threads", …)` fires `worker_init` and `init` runs once; `pool="prefork"` does not run it; `worker_process_init` runs it (D10, measured) | D10 init points | Invert the pool check: both cases redden |
| `tests/test_credential_logging_guard.py` (the checker's existing tests; cases **added**): `span.set_attribute("url", stream_url)` is reported; `span.set_attribute("url", redact_text(stream_url))` is not | D9 checker | Remove `set_attribute` from the method set: the first case reddens |

**Test changes listed.** None to existing tests. `tests/test_observability_logs.py`'s literal copy
of the seed `LOGGING` is a new pin, not a change.

**Gate 2.** No coveragerc module is edited.

**Hooks.** `*.py` (credential check, on every edited Python file, the checker itself included);
`tests/test_*.py` (whole `tests` package); commit gate: `dispatcharr/` and `pyproject.toml` are in
`_SHARED_PATH_PREFIXES`, so **all fifteen labels** run. **CI:** `Backend result` (full set), lint
(`uv.lock` freshness, credential-logging), `Vulnerability Scan` (`uv.lock` path filter).

**PR description draft.**

> Adds OpenTelemetry to the Django, Celery and Daphne processes (observability spec O5). Each
> process initialises after any fork (each uWSGI worker, each Celery prefork child, the thread-pool
> worker, beat, Daphne), and only when `OTEL_EXPORTER_OTLP_ENDPOINT` is set: then traces, metrics
> and logs go out over OTLP/HTTP through exporters that drop unlisted attributes and redact URLs and
> Xtream path credentials. Five instrumentations: Django, Celery, psycopg, Redis, requests. An
> incoming `traceparent` is honoured only from this deployment's own processes. `MINO_LOG_FORMAT=json`
> switches every Python log line to JSON with trace and span ids. The credential-logging check now
> also polices span and metric calls. Off by default: with neither variable set, nothing changes.

### O6 — Python metrics and the tune trace's root

**Changes.** M11 in `dispatcharr/celery.py`'s existing `task_prerun`/`task_postrun` handlers
(`:85`, `:97`); M12–M14 as beat-only observable gauges registered in the `beat_init` handler (D16);
M10's view (already in O5's view list, now exercised); `apps/proxy/authorize_views.py`'s 200 sets
`X-Relay-Traceparent` (D11) after `:360`; `apps/proxy/internal_auth.py` gains
`HEADER_RELAY_TRACEPARENT` beside the other header names (`:59-70`).

**Tests.** `apps/proxy/tests/`: a `TestCase` that installs an SDK tracer provider with an
in-memory exporter and runs `DjangoInstrumentor().instrument()` in `setUpClass`, before any test
client is built (D10's ordering; `uninstrument` in `tearDownClass`). Its cases: the authorize 200
carries an `X-Relay-Traceparent` naming the exported Django server span for that request (its trace
id and span id); with no SDK provider installed, the header is absent; a 403 never carries it.
The same class pins the switch chain's Django half (D11, test 5). `relay_client.advance`
(`apps/proxy/relay_client.py:464`) is called inside an active server span, with the `requests`
instrumentation on and `requests.adapters.HTTPAdapter.send` patched to capture the prepared
request. `relay_client` calls the module-level `requests.request`, which builds its own
session, so there is nothing to mount an adapter on. The instrumentation wraps `Session.send`,
above the adapter, so it injects before the patched `send` runs. The captured `traceparent`
names the `requests` client span, and that span's parent is the server span. Break-check:
uninstrument `requests` for that case. The captured request then carries no `traceparent`, and
the assertion reports it.
`tests/test_observability_metrics.py`: M11 records one point per task with `task`/`outcome`;
the beat callbacks report `LLEN` per queue against a fake broker client and in-use/limit per active
profile against fixture rows and a fake Redis `MGET`, and close the DB connection.

**Break-checks.** Set the header on the 403 path too: the 403 case reddens. Register the beat gauges
in `worker_process_init` instead of `beat_init`: the "not registered in a worker" case reddens.

**Gate 2.** `authorize_views.py` and `internal_auth.py` are two of the nine; the three header
cases cover every new line (the constant is executed at import);
`missing` stays 33; isolated gate run before push.

**Hooks.** `*.py`, `apps/proxy/tests/test_*.py`, `tests/test_*.py`; commit gate full set
(`dispatcharr/`). **CI:** `Backend result` with `coverage-gate`.

**PR description draft.**

> Records Celery task duration, and from beat the queue depth and provider-slot use and limits
> (observability spec O6, D16). The authorize hop now returns its trace context as
> `X-Relay-Traceparent`, which nginx forwards to the relay (O4), so a tune's trace starts at the
> authorize request. Nothing is recorded or sent unless `OTEL_EXPORTER_OTLP_ENDPOINT` is set.

### O7 — the docs page and the example Collector config

**Changes.** `docs/observability.md` and `docs/observability/otel-collector.example.yaml`
(§ Docs page outline); CLAUDE.md § Known defects' "Operationally: no metrics and no structured logs"
becomes a sentence naming what exists and pointing at the docs page and this spec. Docs only.

**Verification.** The example config parses: `docker run --rm -v "$PWD/docs/observability:/c:ro"
otel/opentelemetry-collector-contrib:<tool-resolved digest> validate --config=/c/otel-collector.example.yaml`
(run once by hand; the result goes in the PR body; nothing is added to CI).
`gh pr view <n> --repo D10Scot/Dispatcharr --json closingIssuesReferences` prints 0.

**PR description draft.**

> Documents the observability added by O1–O6: how to turn OTLP on, what each process exports, the
> metric catalogue and how to scrape the relay's `/metrics`, a NetworkPolicy for the relay's port,
> and an example OpenTelemetry Collector config (observability spec O7). Docs only.

## Docs page outline

`docs/observability.md`, in this order. It describes what O1–O6 built, so O7 writes it against the
merged tree and re-reads every name below there.

1. **What you get.** Three signals; which process exports what (a table: program → `service.name`
   → `mino.program` → signals); that everything but the relay's `/metrics` is off until configured.
2. **Turning it on.** The variables of D12 as a table, a compose snippet setting
   `OTEL_EXPORTER_OTLP_ENDPOINT` and `MINO_LOG_FORMAT=json` on the container, and a Kubernetes
   `env:` snippet. The two ignored variables (`OTEL_SERVICE_NAME`, `OTEL_TRACES_SAMPLER`) and why.
   That `OTEL_EXPORTER_OTLP_HEADERS` is a credential: put it in a secret, not a compose file.
   That `OTEL_RESOURCE_ATTRIBUTES` is exported as configured on every OTLP signal and never on
   `/metrics`, so it should hold labels such as the pod and environment, and never a secret
   (R-Q18).
3. **The metric catalogue.** § Metric catalogue's table, with the Prometheus names, and a worked
   example: "which channel's transcode is using the CPU" as a PromQL
   `topk(5, rate(mino_relay_process_cpu_seconds_total[5m]))` by `channel_id, kind, profile_id`.
   That `channel_id` is the numeric id shown in the channel list, never the UUID.
4. **Scraping the relay.** `/metrics` on the relay's port (5658 by default), never through nginx;
   that `/metrics` carries no `target_info` and no scope labels, by design (D9). **Push or scrape, not both into one backend**: with
   OTLP on, the relay pushes the same instruments it serves, and ingesting both doubles every
   series. The example config scrapes and receives, and comments out one path.
5. **Network exposure.** `/metrics` has no auth; what it reveals (D7); a NetworkPolicy that admits
   ingress to the relay's port from the nginx, Django and collector pods only; in the AIO image the
   port is not published, so only the container's own network sees it.
6. **Traces.** The tune trace diagram (D11); that `X-Relay-Traceparent` is trusted only behind
   nginx's marker; that most relay log lines carry no trace id because they are written without a
   context; sampling with `OTEL_TRACES_SAMPLER_ARG`.
7. **Logs.** `MINO_LOG_FORMAT`; the record schema; which lines stay text (uWSGI's request log,
   supervisord, nginx, postgres, redis, the `print` calls). **The two standards (R-Q17), stated
   plainly:**
   - Structured log **fields** are allowlisted by construction. Python keeps the code location,
     the exception type and the frame list; Go keeps the typed slog fields in `logkeys.go`.
   - Log **bodies**, in JSON and over OTLP, get best-effort scrubbing of URLs, paths, UUIDs, HLS
     tokens, long hex strings and `key=value` secrets. **This is no stronger than stdout.** A body
     can still carry exception text a call site interpolates, such as Celery's failure and retry
     messages.
8. **Limits.** Loss on restart (at most one batch per process, one metric interval); process
   metrics are Linux-only; M8 is a lower bound that loses the CPU a process accrued after its last
   observation, which for a short-lived process can be all of it (§ M8 accounting); a relay
   restart starts every M8 series again; exemplars are off; JSON and OTLP structured fields carry a
   channel's numeric id where the text format carries its UUID; **span status, span events and
   structured exception fields** carry an exception's type, never its message, **but log bodies
   are not so restricted** (item 7); HLS silence and Quick Sync detection processes are not
   tracked;
   Kombu priority sub-queues are not counted; the cardinality limit (D7).

`docs/observability/otel-collector.example.yaml`, contrib distribution, roughly:

```yaml
receivers:
  otlp:
    protocols:
      http:
        endpoint: 0.0.0.0:4318
  prometheus:
    config:
      scrape_configs:
        - job_name: mino-relay
          scrape_interval: 15s
          static_configs:
            - targets: ["mino:5658"]   # the relay's port; never the nginx port
processors:
  memory_limiter:
    check_interval: 1s
    limit_percentage: 80
  batch: {}
exporters:
  debug:
    verbosity: basic
  # otlphttp/backend: { endpoint: https://… }   # the operator's own backend
service:
  pipelines:
    traces:  { receivers: [otlp], processors: [memory_limiter, batch], exporters: [debug] }
    logs:    { receivers: [otlp], processors: [memory_limiter, batch], exporters: [debug] }
    metrics: { receivers: [otlp], processors: [memory_limiter, batch], exporters: [debug] }
    # metrics/scrape: { receivers: [prometheus], processors: [memory_limiter, batch], exporters: [debug] }
    # Enable ONE of the two metrics pipelines for the relay (§ 4 above).
```

The block above is an outline, not a hunk: O7 validates the real file with the Collector's own
`validate` command (O7's verification) and may reshape it to pass.

## Risks

| # | Risk | Mitigation |
|---|---|---|
| K1 | A credential or capability reaches an exporter through a carrier the allowlists did not anticipate | Allow by construction for everything new (D9, R-Q17): unknown keys are dropped; values are checked against a typed rule; status descriptions become exception types; non-error `Any` values are dropped. The leak matrix gives each rule its own mutation, and the planner recorded each one failing. **Accepted residual, by ruling R-Q17:** log **bodies** over OTLP are as safe as stdout today and **no stronger**. That includes exception text a call site interpolates, such as Celery's retry and failure messages. Body scrubbing is best effort, and its tests are policy tests, not a proof. Body safety rests on the call-site checks (`check_credential_logging.py`, credlint) and on a future structured-logging rewrite, which is out of scope |
| K2 | The SDK misbehaves under gevent. (a) Encoding a batch to protobuf runs on a uWSGI worker's gevent hub and stalls its request greenlets. (b) Upstream reports deadlocks: opentelemetry-python #4345 ("Deadlock accessing metric reader storage … gevent workers", open), and #5788 (metric locks not reinitialised in a forked child, open). #3886 and #3897 (`BatchSpanProcessor` under gevent) are closed | (a) Milliseconds per 512-span batch; `OTEL_BSP_MAX_EXPORT_BATCH_SIZE` lowers it. (b) D10 initialises after the fork in every process, which sidesteps #5788's fork path. #4345 is not covered by the context-isolation test. Before OTLP is enabled on the test box, O5's PR body records one soak: a uWSGI worker under the project's own `gevent = 400`, polled for ten minutes, with OTLP on, showing no hung worker. If it hangs, metrics export in uWSGI processes is switched off (`OTEL_METRICS_EXPORTER=none`, D12) and the finding becomes an issue. Off by default |
| K3 | A client forces sampling or picks a trace id | D11: no public route on either side extracts a client's context |
| K4 | The relay's shutdown overruns `stopwaitsecs=20` | Telemetry shutdown is bounded at 2 s after the 15 s drain (O4) |
| K5 | Counters keep a series for every channel ever watched | D7: household scale; the SDK's cardinality limit caps it; a relay restart resets it |
| K6 | Double-counted relay metrics when an operator both scrapes `/metrics` and pushes OTLP into one backend | The docs page's § 4; the example config enables one path |
| K7 | An OTel minor bump changes an exposition name and silently breaks a dashboard | `TestExpositionMatchesTheCatalogue` fails on any name change; Renovate's grouped, human-merged OTel update is where it shows |
| K8 | Unstable logging pieces may change shape. `otlploghttp` is pre-1.0 (`v0.23.0`), although the Go logs API and SDK are stable since v1.47.0. The Python logs SDK is still the underscore module `opentelemetry.sdk._logs` | Confined to `relay/telemetry` and `dispatcharr/observability`; pinned; grouped bumps |
| K13 | Whatever the operator writes into `OTEL_RESOURCE_ATTRIBUTES` is exported on every OTLP signal, unfiltered | Accepted by ruling R-Q18: the variable is trusted operator configuration, set beside `OTEL_EXPORTER_OTLP_HEADERS` and going to the same collector. It never reaches the unauthenticated `/metrics` (`WithoutTargetInfo`, pinned by `TestMetricsEndpointCarriesNoResource`). The docs page says to put no secret in it |
| K12 | The Django instrumentation is untested upstream against Django 6 | O5's sample test runs it on Django 6.0.8 and fails if no server span is recorded |
| K9 | govulncheck blocks a PR for a standard-library CVE that needs a toolchain bump | That is the intended posture (ADR 0011); the fix is a `relay/go.mod` `go` line bump in its own PR |
| K10 | The thread-pool `dvr` worker never ran `worker_process_init` (D10's side finding), and other code may silently rely on it | Recorded as an issue in O5's body; this spec only uses `worker_init` for its own init |
| K11 | The rename's R1 ratchet lands first and every O-PR adding `dispatcharr.observability` fails it | D13's sequencing table: regenerate the allowlist in the same PR with the C-10 reason |

## Open items

Items the planner decided rather than found in a ruling, for the reviewer to challenge:

1. **D16, "queue depth via beat"** read as "observed in the beat process", not "measured by a
   beat-scheduled task". Reason in D16.
2. **D13, `relay-uwsgi` is `mino-api`**, not a fourth service name, with `mino.program`
   distinguishing it. The ruling named three services; this keeps three.
3. **D8, `MINO_LOG_FORMAT` defaults to `text`.** The ruling named the two values, not the default;
   `text` keeps every log line byte-identical until an operator opts in.
4. **D11, the trace root behind nginx is the authorize request's span**, carried by a new
   `X-Relay-Traceparent` decision header. The ruling says the tune trace starts at authorize; this is
   the only way to put authorize in the same trace when nginx runs it before the relay sees the
   request.
5. **D12, `OTEL_TRACES_SAMPLER` and `OTEL_SERVICE_NAME` are ignored**, and an
   `OTEL_EXPORTER_OTLP_PROTOCOL` other than `http/protobuf` turns OTLP off rather than falling back.
6. **D14, the catalogue adds M7 (the rewind disk limit) beside M6 (its use)**, reading "rewind disk"
   as the pair a ratio needs, and adds no tune-duration histogram (traces carry it).
7. **No parity-matrix row** for `/metrics`: it is not on a viewer's path (Global constraint 1). The
   nginx test is its pin.
8. **The research subagent's cross-check arrived after the first commit.** It confirmed several
   things against upstream source and docs:
   - uWSGI calls `PyOS_AfterFork_Child` only under `py-call-osafterfork`;
   - Daphne has no lifespan support;
   - the Django instrumentation covers ASGI HTTP but not Channels consumers;
   - Celery's own docs recommend `worker_process_init`;
   - gevent gives each greenlet its own context from gevent 20.9.

   It changed three things, folded in at round 1: the pinned naming strategy (D4), the Django 6
   sample test (O5), and K2's upstream issues.

9. **`service.instance.id` beside the fixed attributes.** R-Q18 says our code adds only its
   fixed attributes: service name, version and program. The spec also keeps
   `service.instance.id`, a random UUID per process with no configuration in it. Without it,
   prefork children and uWSGI workers of one program would export identical resources, and
   their cumulative counters would collide in the backend. Listed for the reviewer to challenge.

The round-1 reviewer ruled items 1–7 acceptable, items 4 and 5 subject to the D10 and D11
changes made in that round.

## Appendix A — Byte-exact hunks against the seed SHA

Each hunk below was produced by applying the edit to a detached worktree at the seed SHA and
running `git diff`; each applies with `git apply --check` against the seed (verified for A.1–A.3).
The implementer applies them verbatim in the PR named, and writes everything else this spec
describes.

### A.1 — nginx: carry the authorize hop's trace context to the relay (O4)

````diff
diff --git a/docker/dispatcharr_api_params.conf b/docker/dispatcharr_api_params.conf
index bf23b8c1..727a6f84 100644
--- a/docker/dispatcharr_api_params.conf
+++ b/docker/dispatcharr_api_params.conf
@@ -5,7 +5,7 @@
 # Why it exists: uwsgi_pass_request_headers is on by default, so a client's
 # own X-Dispatcharr-Authorized or X-Relay-* header would otherwise reach
 # the application untouched. Since nginx 0.8.40 a *_param whose name begins
-# with HTTP_ overrides the same-named client header, so setting these seven
+# with HTTP_ overrides the same-named client header, so setting these eight
 # to "" is what replaces whatever arrived. On nginx 1.24, setting a
 # HTTP_-prefixed *_param to "" does not forward an empty header: nginx
 # drops the client's header and sends nothing under that name; the relay
@@ -27,3 +27,4 @@ uwsgi_param HTTP_X_RELAY_CLIENT  "";
 uwsgi_param HTTP_X_RELAY_USER    "";
 uwsgi_param HTTP_X_RELAY_OUTPUT_FORMAT "";
 uwsgi_param HTTP_X_RELAY_CLIENT_IP     "";
+uwsgi_param HTTP_X_RELAY_TRACEPARENT   "";
diff --git a/docker/dispatcharr_api_params_proxy.conf b/docker/dispatcharr_api_params_proxy.conf
index 0fc54657..d37bdb1d 100644
--- a/docker/dispatcharr_api_params_proxy.conf
+++ b/docker/dispatcharr_api_params_proxy.conf
@@ -42,3 +42,4 @@ proxy_set_header X-Relay-Client  "";
 proxy_set_header X-Relay-User    "";
 proxy_set_header X-Relay-Output-Format "";
 proxy_set_header X-Relay-Client-IP     "";
+proxy_set_header X-Relay-Traceparent   "";
diff --git a/docker/nginx.conf b/docker/nginx.conf
index cb8715d3..bcf2e710 100644
--- a/docker/nginx.conf
+++ b/docker/nginx.conf
@@ -289,6 +289,8 @@ server {
     # anything else is nginx's own error — including an unreachable API
     # process, which is a 500 here rather than the 502/504 a failed
     # uwsgi_pass would give (amendment S7). The eight auth_request_set lines
+    # (nine on the three Go-bound locations, which also carry the hop's
+    # X-Relay-Traceparent to the relay: observability spec D11)
     # are the only way to read the subrequest's response headers; the
     # uwsgi_param lines
     # re-emit them toward the relay AND override whatever the client sent
@@ -310,6 +312,7 @@ server {
         auth_request_set $relay_user    $upstream_http_x_relay_user;
         auth_request_set $relay_output_format $upstream_http_x_relay_output_format;
         auth_request_set $relay_client_ip $upstream_http_x_relay_client_ip;
+        auth_request_set $relay_traceparent $upstream_http_x_relay_traceparent;
         auth_request_set $authorize_status $upstream_http_x_authorize_status;
         error_page 403 = @authorize_denied;
 
@@ -340,6 +343,7 @@ server {
         proxy_set_header X-Relay-User    $relay_user;
         proxy_set_header X-Relay-Output-Format $relay_output_format;
         proxy_set_header X-Relay-Client-IP     $relay_client_ip;
+        proxy_set_header X-Relay-Traceparent $relay_traceparent;
         # proxy_buffering, NOT uwsgi_buffering: uwsgi_buffering is inert under
         # proxy_pass, and a buffered live TS stream gets spooled to disk. This
         # is CLAUDE.md's historical incident arriving from the opposite
@@ -498,6 +502,7 @@ server {
         auth_request_set $relay_user    $upstream_http_x_relay_user;
         auth_request_set $relay_output_format $upstream_http_x_relay_output_format;
         auth_request_set $relay_client_ip $upstream_http_x_relay_client_ip;
+        auth_request_set $relay_traceparent $upstream_http_x_relay_traceparent;
         auth_request_set $authorize_status $upstream_http_x_authorize_status;
         error_page 403 = @authorize_denied;
 
@@ -528,6 +533,7 @@ server {
         proxy_set_header X-Relay-User    $relay_user;
         proxy_set_header X-Relay-Output-Format $relay_output_format;
         proxy_set_header X-Relay-Client-IP     $relay_client_ip;
+        proxy_set_header X-Relay-Traceparent $relay_traceparent;
         # proxy_buffering, NOT uwsgi_buffering: uwsgi_buffering is inert under
         # proxy_pass, and a buffered live TS stream gets spooled to disk. This
         # is CLAUDE.md's historical incident arriving from the opposite
@@ -657,6 +663,7 @@ server {
         auth_request_set $relay_user    $upstream_http_x_relay_user;
         auth_request_set $relay_output_format $upstream_http_x_relay_output_format;
         auth_request_set $relay_client_ip $upstream_http_x_relay_client_ip;
+        auth_request_set $relay_traceparent $upstream_http_x_relay_traceparent;
         auth_request_set $authorize_status $upstream_http_x_authorize_status;
         error_page 403 = @authorize_denied;
 
@@ -687,6 +694,7 @@ server {
         proxy_set_header X-Relay-User    $relay_user;
         proxy_set_header X-Relay-Output-Format $relay_output_format;
         proxy_set_header X-Relay-Client-IP     $relay_client_ip;
+        proxy_set_header X-Relay-Traceparent $relay_traceparent;
         # proxy_buffering, NOT uwsgi_buffering: uwsgi_buffering is inert under
         # proxy_pass, and a buffered live TS stream gets spooled to disk. This
         # is CLAUDE.md's historical incident arriving from the opposite
````

### A.2 — the dependency gate (O1)

Deletes `scripts/check_go_stdlib_only.sh`; adds `scripts/check_go_deps.sh` and
`relay/go.allowed-deps`; edits `go-tests.yml`, `vuln-scan.yml`, `renovate.json`,
`.golangci.yml`, `scripts/coverage_relay_go.sh`, `relay/hls/doc.go` and the implementer skill's
`references/project.md`. Verified on the scratch tree: `actionlint` (no new finding; the one it
prints, SC2013 at `vuln-scan.yml:240`, is in an unchanged step), `zizmor --offline` 1.31.1 (zero
findings on both workflows), `golangci-lint config verify` (exit 0; golangci-lint 2.15.0 locally,
`go-tests.yml` pins v2.13.2), `golangci-lint run` (no depguard finding on the seed tree), the
renovate JSON parses and its two regexes decode as intended, and `scripts/check_go_deps.sh relay`
exits 0 on the seed with the new empty allowlist. The step A.2 adds to `go-tests.yml` runs
`scripts/tests/test_check_go_deps.sh`, which O1 writes (§ O1's test table).

````diff
diff --git a/.claude/skills/implement-review-escalate/references/project.md b/.claude/skills/implement-review-escalate/references/project.md
index c3ac9f50..05efdd04 100644
--- a/.claude/skills/implement-review-escalate/references/project.md
+++ b/.claude/skills/implement-review-escalate/references/project.md
@@ -6,7 +6,7 @@ Rewrite this file when porting the skill. `SKILL.md` is generic; this file names
 
 - **Python:** labels from `python scripts/ci_backend_test_labels.py` (read its usage). Run in your own container: `DISPATCHARR_TEST_CONTAINER=<name> DISPATCHARR_TEST_DB_VOLUME=<name>-db CLAUDE_HOOK_REPO_ROOT=<worktree> <worktree>/.claude/hooks/start-test-container.sh`, then run labels the way `.claude/hooks/run-affected-tests.sh` does (Redis flushed first, whole package). Run every label once **without** `--keepdb` before pushing: a test on a migration-seeded row passes under keepdb and fails on CI's fresh database. The shared `dispatcharr-testrunner` hook refuses on a mount mismatch; that message is expected in a worktree, and the labels are then run by hand.
 - **Gate 2 (Python coverage ratchet):** if the change touches a module listed in `scripts/coverage_live_path.coveragerc`, run `scripts/coverage_live_path_isolated.sh --gate` (read its header). Floor `missing=33`; no tolerance parameter.
-- **Go:** the `PostToolUse` hook runs build, vet, lint and `test -race` on every `.go` edit. Before pushing: `cd <worktree>/relay && go build ./... && go vet ./... && go test -race ./... && golangci-lint run ./... && GOOS=linux golangci-lint run ./...`, then from `<worktree>`: `scripts/check_go_stdlib_only.sh relay` and `scripts/check_go_credential_logging.sh relay`. The Go coverage ratchet has **no headroom** (floor `missing=589`): `scripts/coverage_relay_go.sh --gate` must pass. A draw above the floor is a finding to investigate, and the fix is a re-measurement PR of its own, never a floor bump on the PR that drew it.
+- **Go:** the `PostToolUse` hook runs build, vet, lint and `test -race` on every `.go` edit. Before pushing: `cd <worktree>/relay && go build ./... && go vet ./... && go test -race ./... && golangci-lint run ./... && GOOS=linux golangci-lint run ./...`, then from `<worktree>`: `scripts/check_go_deps.sh relay` and `scripts/check_go_credential_logging.sh relay`. The Go coverage ratchet has **no headroom** (floor `missing=589`): `scripts/coverage_relay_go.sh --gate` must pass. A draw above the floor is a finding to investigate, and the fix is a re-measurement PR of its own, never a floor bump on the PR that drew it.
 - **Frontend:** `cd <worktree>/frontend && npm ci && npm test`.
 - **E2E specs:** on every edit under `e2e/**` or `e2e-upstream/**`, comments and strings included: `npx tsc --noEmit` and `npx playwright test --project=guards` (static guards: allowlists, tags, string-literal scans, parity-matrix citations). A full Playwright run only when the plan section requires it, on a private stack with a private image tag (see `worktree-per-change`).
 - **Every `.py` edit** runs `scripts/check_credential_logging.py`; keep it clean.
diff --git a/.github/workflows/go-tests.yml b/.github/workflows/go-tests.yml
index 6390bf14..8ed0cd0a 100644
--- a/.github/workflows/go-tests.yml
+++ b/.github/workflows/go-tests.yml
@@ -125,7 +125,7 @@ jobs:
           # already covers. That is the load-bearing half -- a corpus outside
           # `^relay/` would stop triggering this workflow at all, and `Go
           # result` would stay green through its not-required branch.
-          pattern='^(relay/|\.golangci\.yml$|scripts/check_go_stdlib_only\.sh$|scripts/check_go_credential_logging\.sh$|scripts/check_floor_raise\.sh$|scripts/tests/test_check_floor_raise\.sh$|scripts/coverage_relay_go\.|\.github/workflows/go-tests\.yml$)'
+          pattern='^(relay/|\.golangci\.yml$|scripts/check_go_deps\.sh$|scripts/tests/test_check_go_deps\.sh$|scripts/check_go_credential_logging\.sh$|scripts/check_floor_raise\.sh$|scripts/tests/test_check_floor_raise\.sh$|scripts/coverage_relay_go\.|\.github/workflows/go-tests\.yml$)'
           if printf '%s\n' "$changed" | grep -qE "$pattern"; then
             echo "go=true" >> "$GITHUB_OUTPUT"
           else
@@ -248,9 +248,19 @@ jobs:
           path: /tmp/relay-go-coverage
           retention-days: 1
 
-      - name: Assert the module is standard-library only
+      # ADR 0011: the direct requirements equal relay/go.allowed-deps, the
+      # binary links no database/sql and no Redis or Postgres driver, and
+      # go.mod is tidy. Replaced the stdlib-only assertion.
+      - name: Assert the dependency allowlist and the driver ban
         working-directory: .
-        run: scripts/check_go_stdlib_only.sh relay
+        run: scripts/check_go_deps.sh relay
+
+      # The check's own cases, against throwaway modules with no network
+      # (scripts/tests/test_check_go_deps.sh). Here rather than in lint.yml,
+      # beside test_check_floor_raise.sh, because it needs the Go toolchain.
+      - name: Test the dependency check
+        working-directory: .
+        run: bash scripts/tests/test_check_go_deps.sh
 
       # The Go side of the credential-logging rule (lint.yml's
       # credential-logging job is the Python side): every error-typed
@@ -261,6 +271,35 @@ jobs:
         working-directory: .
         run: scripts/check_go_credential_logging.sh relay
 
+  # ADR 0011: a vulnerability in code the relay calls, the Go standard
+  # library included, fails the run. govulncheck runs from the module cache
+  # at a pinned version that `go run` verifies against the Go checksum
+  # database; Renovate bumps GOVULNCHECK_VERSION (renovate.json's custom
+  # manager). A bare runner is enough: govulncheck reads source and the
+  # module graph, and links nothing it scans.
+  govulncheck:
+    name: govulncheck
+    runs-on: ubuntu-latest
+    needs: changes
+    if: needs.changes.outputs.go == 'true'
+    timeout-minutes: 15
+    env:
+      GOVULNCHECK_VERSION: v1.9.0
+    steps:
+      - name: Checkout code
+        uses: actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1 # v7.0.1
+        with:
+          persist-credentials: false
+
+      - name: Set up Go
+        uses: actions/setup-go@b7ad1dad31e06c5925ef5d2fc7ad053ef454303e # v7.0.0
+        with:
+          go-version-file: relay/go.mod
+
+      - name: Run govulncheck
+        working-directory: relay
+        run: go run "golang.org/x/vuln/cmd/govulncheck@${GOVULNCHECK_VERSION}" ./...
+
   lint:
     name: golangci-lint
     runs-on: ubuntu-latest
@@ -388,7 +427,7 @@ jobs:
   go-result:
     name: Go result
     runs-on: ubuntu-latest
-    needs: [changes, build, lint, coverage]
+    needs: [changes, build, lint, coverage, govulncheck]
     if: always()
     timeout-minutes: 5
     steps:
@@ -397,10 +436,11 @@ jobs:
           CHANGES_RESULT: ${{ needs.changes.result }}
           BUILD_RESULT: ${{ needs.build.result }}
           LINT_RESULT: ${{ needs.lint.result }}
+          GOVULNCHECK_RESULT: ${{ needs.govulncheck.result }}
           COVERAGE_RESULT: ${{ needs.coverage.result }}
           GO_REQUIRED: ${{ needs.changes.outputs.go }}
         run: |
-          echo "changes=$CHANGES_RESULT build=$BUILD_RESULT lint=$LINT_RESULT coverage=$COVERAGE_RESULT go-required=$GO_REQUIRED"
+          echo "changes=$CHANGES_RESULT build=$BUILD_RESULT lint=$LINT_RESULT coverage=$COVERAGE_RESULT govulncheck=$GOVULNCHECK_RESULT go-required=$GO_REQUIRED"
           if [ "$CHANGES_RESULT" != "success" ]; then
             echo "Change detection itself failed — cannot prove the Go jobs were unnecessary."
             exit 1
@@ -412,7 +452,7 @@ jobs:
           # `skipped` here means a gated job never ran on a run that needed
           # it, so only an exact `success` may report green.
           for pair in "build:$BUILD_RESULT" "lint:$LINT_RESULT" \
-                      "coverage:$COVERAGE_RESULT"; do
+                      "coverage:$COVERAGE_RESULT" "govulncheck:$GOVULNCHECK_RESULT"; do
             if [ "${pair#*:}" != "success" ]; then
               echo "The Go jobs were required and ${pair%%:*} did not succeed."
               exit 1
diff --git a/.github/workflows/vuln-scan.yml b/.github/workflows/vuln-scan.yml
index ad9408eb..7f414521 100644
--- a/.github/workflows/vuln-scan.yml
+++ b/.github/workflows/vuln-scan.yml
@@ -32,6 +32,8 @@ on:
       - 'pyproject.toml'
       - 'frontend/package-lock.json'
       - 'e2e/package-lock.json'
+      - 'relay/go.mod'
+      - 'relay/go.sum'
       - '.github/workflows/vuln-scan.yml'
   pull_request:
     # Deliberately NOT docker/DispatcharrBase or docker/Dockerfile: the
@@ -47,6 +49,8 @@ on:
       - 'pyproject.toml'
       - 'frontend/package-lock.json'
       - 'e2e/package-lock.json'
+      - 'relay/go.mod'
+      - 'relay/go.sum'
       - '.github/workflows/vuln-scan.yml'
   # zizmor flags workflow_run as "almost always used insecurely" because the
   # common misuse is checking out and building the triggering run's PR head
@@ -103,7 +107,7 @@ jobs:
           # google/osv-scanner v2.5.1
           docker run --rm -v "$PWD:/repo" -w /repo \
             ghcr.io/google/osv-scanner@sha256:8108ae94eadea5a02c9bec6e646909d5b790b44bd62d7f5b7f0b1d6d0ffc7734 \
-            scan source --lockfile=/repo/uv.lock --lockfile=/repo/frontend/package-lock.json --lockfile=/repo/e2e/package-lock.json \
+            scan source --lockfile=/repo/uv.lock --lockfile=/repo/frontend/package-lock.json --lockfile=/repo/e2e/package-lock.json --lockfile=/repo/relay/go.mod \
             --format table || true
 
       - name: OSV-Scanner (blocking — CVSS >= 7.0, i.e. HIGH/CRITICAL)
@@ -111,7 +115,7 @@ jobs:
           # google/osv-scanner v2.5.1
           docker run --rm -v "$PWD:/repo" -w /repo \
             ghcr.io/google/osv-scanner@sha256:8108ae94eadea5a02c9bec6e646909d5b790b44bd62d7f5b7f0b1d6d0ffc7734 \
-            scan source --lockfile=/repo/uv.lock --lockfile=/repo/frontend/package-lock.json --lockfile=/repo/e2e/package-lock.json \
+            scan source --lockfile=/repo/uv.lock --lockfile=/repo/frontend/package-lock.json --lockfile=/repo/e2e/package-lock.json --lockfile=/repo/relay/go.mod \
             --format json --output-file=osv-results.json || true
           python3 -c "
           import json, sys
@@ -260,3 +264,33 @@ jobs:
           docker run --rm -v "$RUNNER_TEMP/grype.yaml:/grype.yaml:ro" \
             anchore/grype@sha256:ddf9e9f204049f3a4a0955ef70873cabab6a31432125ad4f20a490b54950a253 \
             "$IMAGE_REF" --config /grype.yaml --fail-on high --only-fixed -o table
+
+  # ADR 0011: the relay's Go modules, scanned from source on every PR that
+  # touches relay/go.mod or relay/go.sum. The trivy and grype jobs above see
+  # the same modules only inside the PUBLISHED image (/usr/local/bin/relay-go's
+  # embedded build info), after merge; this is the pre-merge half. Same
+  # digest-pinned scanner images and the same CRITICAL/HIGH-with-a-fix
+  # blocking policy as the image jobs.
+  go-modules:
+    name: Trivy and Grype (relay Go modules)
+    if: github.event_name != 'workflow_run'
+    runs-on: ubuntu-latest
+    steps:
+      - uses: actions/checkout@d23441a48e516b6c34aea4fa41551a30e30af803 # v6.1.0
+        with:
+          persist-credentials: false
+
+      - name: Trivy (blocking — CRITICAL/HIGH, fixable only)
+        run: |
+          # aquasecurity/trivy v0.74.0
+          docker run --rm -v "$PWD/relay:/relay:ro" \
+            aquasec/trivy@sha256:62b1e65e8869bc4b4c6aa4fa2b21595256c7c2f6018a9d9ad61caf87187c1969 \
+            fs --severity CRITICAL,HIGH --ignore-unfixed --exit-code 1 --format table --scanners vuln --timeout 8m \
+            /relay
+
+      - name: Grype (blocking — CRITICAL/HIGH, fixable only)
+        run: |
+          # anchore/grype v0.117.0
+          docker run --rm -v "$PWD/relay:/relay:ro" \
+            anchore/grype@sha256:ddf9e9f204049f3a4a0955ef70873cabab6a31432125ad4f20a490b54950a253 \
+            dir:/relay --fail-on high --only-fixed -o table
diff --git a/.golangci.yml b/.golangci.yml
index 96eff11e..123dd0e2 100644
--- a/.golangci.yml
+++ b/.golangci.yml
@@ -20,6 +20,36 @@ linters:
     - noctx          # every outbound request carries a deadline (§ The contract's timeouts)
     - revive
     - unconvert
+    - depguard       # ADR 0011: OTel stays in relay/telemetry; no driver anywhere
+  settings:
+    depguard:
+      rules:
+        otel-confined:
+          files:
+            - $all
+            - "!**/relay/telemetry/**"
+            - "!**/relay/main.go"
+          deny:
+            - pkg: go.opentelemetry.io
+              desc: OTel stays in relay/telemetry (observability spec D2, ADR 0011)
+            - pkg: github.com/prometheus
+              desc: the Prometheus client stays in relay/telemetry (observability spec D2, ADR 0011)
+        no-drivers:
+          files:
+            - $all
+          deny:
+            - pkg: database/sql$
+              desc: ADR 0011 -- the relay links no database driver
+            - pkg: github.com/lib/pq
+              desc: ADR 0011 -- the relay links no database driver
+            - pkg: github.com/jackc
+              desc: ADR 0011 -- the relay links no database driver
+            - pkg: github.com/go-sql-driver
+              desc: ADR 0011 -- the relay links no database driver
+            - pkg: github.com/redis
+              desc: ADR 0011 -- the relay links no Redis client
+            - pkg: github.com/gomodule/redigo
+              desc: ADR 0011 -- the relay links no Redis client
   exclusions:
     generated: lax
     rules:
diff --git a/relay/go.allowed-deps b/relay/go.allowed-deps
new file mode 100644
index 00000000..10d664ed
--- /dev/null
+++ b/relay/go.allowed-deps
@@ -0,0 +1,5 @@
+# The relay's allowed DIRECT Go requirements, one module path per line.
+# scripts/check_go_deps.sh fails when go.mod's direct requirements differ
+# from this list in either direction. Adding a line is adding a dependency:
+# ADR 0011 and docs/superpowers/specs/2026-10-31-observability-design.md
+# (D2, § Go modules) say which modules may appear here.
diff --git a/relay/hls/doc.go b/relay/hls/doc.go
index b63b1f23..d4adcab6 100644
--- a/relay/hls/doc.go
+++ b/relay/hls/doc.go
@@ -24,6 +24,6 @@
 // Store under /hls/ (relay/httpapi's HLS handlers), so it is inside the Go
 // coverage gate's denominator (rulings R27, R34).
 //
-// Everything is in process memory (ADR 0006): no Redis, no Postgres, and the
-// standard library only (scripts/check_go_stdlib_only.sh).
+// Everything is in process memory (ADR 0006): no Redis, no Postgres, and no
+// third-party module (ADR 0011 confines the relay's to relay/telemetry).
 package hls
diff --git a/renovate.json b/renovate.json
index b9896e71..852df58c 100644
--- a/renovate.json
+++ b/renovate.json
@@ -33,6 +33,36 @@
       "matchManagers": ["pep621", "npm"],
       "matchUpdateTypes": ["minor", "major"],
       "automerge": false
+    },
+    {
+      "description": "Go modules (ADR 0011): the relay's only third-party code is the OpenTelemetry SDK and the Prometheus client. A week's cooldown and always a human merge, whatever the update type, because a bump moves relay/go.mod and with it the coverage floor's gomod= hash. postUpdateOptions keeps go.sum tidy for scripts/check_go_deps.sh.",
+      "matchManagers": ["gomod"],
+      "minimumReleaseAge": "7 days",
+      "automerge": false,
+      "postUpdateOptions": ["gomodTidy"]
+    },
+    {
+      "description": "The OpenTelemetry Go modules release together and depend on each other's exact versions; a split bump does not build. One update for all of them.",
+      "matchManagers": ["gomod"],
+      "matchPackageNames": ["go.opentelemetry.io/**"],
+      "groupName": "OpenTelemetry Go"
+    },
+    {
+      "description": "govulncheck, run by go-tests.yml at the version in its GOVULNCHECK_VERSION env (ADR 0011). Same cooldown as the Go modules.",
+      "matchManagers": ["custom.regex"],
+      "matchPackageNames": ["golang.org/x/vuln"],
+      "minimumReleaseAge": "7 days",
+      "automerge": false
+    }
+  ],
+  "customManagers": [
+    {
+      "customType": "regex",
+      "description": "go-tests.yml's govulncheck job pins the tool by version in an env value; `go run pkg@version` verifies it against the Go checksum database.",
+      "managerFilePatterns": ["/^\\.github/workflows/go-tests\\.yml$/"],
+      "matchStrings": ["GOVULNCHECK_VERSION: (?<currentValue>v\\S+)"],
+      "depNameTemplate": "golang.org/x/vuln",
+      "datasourceTemplate": "go"
     }
   ]
 }
diff --git a/scripts/check_go_deps.sh b/scripts/check_go_deps.sh
new file mode 100755
index 00000000..26254b5a
--- /dev/null
+++ b/scripts/check_go_deps.sh
@@ -0,0 +1,56 @@
+#!/usr/bin/env bash
+# The relay's dependency rule (ADR 0011, observability spec D2). Replaced
+# scripts/check_go_stdlib_only.sh. Three checks, each printing what it found:
+#
+#   1. The module's DIRECT requirements equal relay/go.allowed-deps, in both
+#      directions. Indirect modules follow from the direct ones and are
+#      covered by govulncheck, OSV-Scanner, Trivy and Grype instead.
+#   2. The packages the shipped binary LINKS (`go list -deps .`, the question
+#      scripts/coverage_relay_go.sh also asks) include no database/sql and no
+#      Redis or Postgres driver. database/sql/driver is NOT banned: it is an
+#      interface package that github.com/google/uuid (linked by the OTel SDK)
+#      imports for its Value method, and it opens nothing.
+#   3. go.mod and go.sum are tidy, the state the old script's empty-go.sum
+#      check existed to catch.
+set -euo pipefail
+
+MODULE_ROOT="${1:-relay}"
+cd "$MODULE_ROOT"
+
+ALLOWLIST="go.allowed-deps"
+[ -f "$ALLOWLIST" ] || { echo "FAILED: ${MODULE_ROOT}/${ALLOWLIST} is missing (ADR 0011)." >&2; exit 1; }
+
+MAIN="$(go list -m)"
+status=0
+
+direct="$(go list -m -f '{{if not .Indirect}}{{.Path}}{{end}}' all | grep -vxF "$MAIN" | LC_ALL=C sort -u || true)"
+allowed="$(grep -vE '^[[:space:]]*(#|$)' "$ALLOWLIST" | LC_ALL=C sort -u || true)"
+unexpected="$(LC_ALL=C comm -23 <(printf '%s\n' "$direct" | sed '/^$/d') <(printf '%s\n' "$allowed" | sed '/^$/d'))"
+missing="$(LC_ALL=C comm -13 <(printf '%s\n' "$direct" | sed '/^$/d') <(printf '%s\n' "$allowed" | sed '/^$/d'))"
+if [ -n "$unexpected" ]; then
+  echo "FAILED: direct requirements not in ${MODULE_ROOT}/${ALLOWLIST} (ADR 0011):" >&2
+  printf '%s\n' "$unexpected" | sed 's/^/          /' >&2
+  status=1
+fi
+if [ -n "$missing" ]; then
+  echo "FAILED: ${MODULE_ROOT}/${ALLOWLIST} names modules go.mod does not require directly:" >&2
+  printf '%s\n' "$missing" | sed 's/^/          /' >&2
+  status=1
+fi
+
+linked="$(go list -deps .)"
+banned="$(printf '%s\n' "$linked" | grep -iE '^database/sql$|(^|/)redis|^github\.com/(lib/pq|jackc/|go-sql-driver/|mattn/go-sqlite3)' || true)"
+if [ -n "$banned" ]; then
+  echo "FAILED: ${MODULE_ROOT} links a database or Redis package (ADR 0011):" >&2
+  printf '%s\n' "$banned" | sed 's/^/          /' >&2
+  status=1
+fi
+
+if ! tidy="$(go mod tidy -diff 2>&1)"; then
+  echo "FAILED: go.mod/go.sum are not tidy; run 'go mod tidy' in ${MODULE_ROOT}:" >&2
+  printf '%s\n' "$tidy" | sed 's/^/          /' >&2
+  status=1
+fi
+
+[ "$status" -eq 0 ] && echo "OK: ${MODULE_ROOT}'s direct requirements match ${ALLOWLIST}, and it links no database or Redis package."
+exit "$status"
diff --git a/scripts/check_go_stdlib_only.sh b/scripts/check_go_stdlib_only.sh
deleted file mode 100755
index af5cbbf4..00000000
--- a/scripts/check_go_stdlib_only.sh
+++ /dev/null
@@ -1,60 +0,0 @@
-#!/usr/bin/env bash
-# The mechanical half of the phase's "no third-party Go dependencies" rule
-# (spec § Stage 2c, "Third-party Go dependencies: none", line 1731).
-#
-# Two checks, because either alone has a hole. `go list -m all` prints the
-# module graph, which is exactly one line in a zero-dependency module -- it
-# catches a `require` that `go mod tidy` has resolved. The go.sum check
-# catches the state between adding an import and tidying, where go.sum
-# exists and the graph has not been rewritten yet.
-#
-# Also the backstop the spec names for 2c-1's un-mechanised PR-description
-# precondition: a Postgres driver or a Redis client is a third-party module,
-# so it fails here regardless of whether anyone read the punch list.
-set -euo pipefail
-
-MODULE_ROOT="${1:-relay}"
-cd "$MODULE_ROOT"
-
-EXPECTED="github.com/D10Scot/Dispatcharr/relay"
-
-if [ -s go.sum ]; then
-  echo "FAILED: ${MODULE_ROOT}/go.sum is non-empty. This module is stdlib-only;" >&2
-  echo "        a go.sum means a third-party dependency was added." >&2
-  echo "        Spec § Stage 2c: 'This is a rule to defend, not an accident.'" >&2
-  exit 1
-fi
-
-GRAPH="$(go list -m all)"
-if [ "$GRAPH" != "$EXPECTED" ]; then
-  echo "FAILED: the module graph is not stdlib-only." >&2
-  echo "        expected exactly: ${EXPECTED}" >&2
-  echo "        got:" >&2
-  printf '%s\n' "$GRAPH" | sed 's/^/          /' >&2
-  exit 1
-fi
-
-# Spec § Stage 2c's second invariant: "The Go binary links no Redis client."
-#
-# The module-graph check above catches an IMPORTED one and nothing else. This
-# catches the shape it cannot: a Redis client written inside this module, in
-# the standard library, which is entirely possible and would satisfy every
-# other gate in this repo.
-#
-# `go list -deps` and not a text scan, and the difference is not style. The
-# invariant is about what the BINARY LINKS, and a text scan cannot tell that
-# from a comment: several files in relay/ legitimately name Redis while
-# explaining what D2 deleted, and `redis_chunk_ttl` is a settings key that is
-# on the wire and CANNOT be renamed, because D5 is strict parity and a
-# settings key is visible in the UI. A grep would need an exclusion list, and
-# an exclusion that names one string is an exclusion somebody widens.
-if go list -deps ./... | grep -qiE '(^|/)redis'; then
-  echo "FAILED: ${MODULE_ROOT} links a package named for Redis." >&2
-  echo "        Spec § Stage 2c: 'The Go binary links no Redis client.'" >&2
-  echo "        D2 puts the ring buffer in process memory; the live path" >&2
-  echo "        reaches no Redis at all, in any form." >&2
-  go list -deps ./... | grep -iE '(^|/)redis' | sed 's/^/          /' >&2
-  exit 1
-fi
-
-echo "OK: ${MODULE_ROOT} depends on the standard library only."
diff --git a/scripts/coverage_relay_go.sh b/scripts/coverage_relay_go.sh
index 46c7d859..4790ee38 100755
--- a/scripts/coverage_relay_go.sh
+++ b/scripts/coverage_relay_go.sh
@@ -95,7 +95,7 @@ measure() {
   rm -rf "$dir"; mkdir -p "$dir"
 
   # The package list is derived FIRST and from `go list -deps .`, the same
-  # question scripts/check_go_stdlib_only.sh asks: what does the binary link?
+  # question scripts/check_go_deps.sh asks: what does the binary link?
   # Written before the tests run so a failing suite still leaves evidence of
   # what the scope was.
   ( cd "$MODULE_DIR" && go list -deps . ) \
````

### A.3 — the relay build stage downloads modules in its own layer (O2)

````diff
diff --git a/docker/Dockerfile b/docker/Dockerfile
index c16a68bc..7713714e 100644
--- a/docker/Dockerfile
+++ b/docker/Dockerfile
@@ -35,12 +35,14 @@ ARG TARGETOS
 ARG TARGETARCH
 
 WORKDIR /src
-# One COPY, deliberately. The usual "copy go.mod first, download, then copy
-# the source" split exists to cache `go mod download` across source changes;
-# a stdlib-only module downloads nothing, so the split would add a layer
-# that caches an empty step and a comment claiming a benefit it does not
-# deliver. Reinstate it in the same commit as the first dependency, if there
-# ever is one.
+# go.mod and go.sum first, then `go mod download`, then the source: the
+# module download is cached across source-only changes. Reinstated by the
+# observability spec's O2, the commit that gave the relay its first
+# dependencies (ADR 0011); until then the module was stdlib-only and the
+# split cached an empty step. `go mod download` verifies every module
+# against go.sum, so a tampered proxy response fails the build here.
+COPY ./relay/go.mod ./relay/go.sum ./
+RUN go mod download
 COPY ./relay ./
 
 # CGO_ENABLED=0 makes the binary static, so it runs on the final image
````

### A.4 — (reserved)

Renovate's rules are in A.2 (`renovate.json`).

### A.5 — CLAUDE.md (O1)

Each OLD string occurs exactly once in `CLAUDE.md` at the seed SHA (checked with Python's `str.count`, which the implementer re-runs); replace it with NEW. CLAUDE.md's paragraphs are single physical lines of up to several thousand characters, so a unified hunk would repeat each paragraph twice; an exact substring pair is the same byte-exact instruction in a readable size.

**A.5.1**

OLD:

````text
scripts/check_go_stdlib_only.sh relay           # the module must stay stdlib-only
````

NEW:

````text
scripts/check_go_deps.sh relay                  # direct deps = relay/go.allowed-deps; no DB/Redis driver (ADR 0011)
````

**A.5.2**

OLD:

````text
(`relay/internal/credlint`, a `go/types`-aware checker built from stdlib only)
````

NEW:

````text
(`relay/internal/credlint`, a `go/types`-aware checker built from stdlib only, which resolves third-party packages through `go list -export` since ADR 0011)
````

**A.5.3**

OLD:

````text
`log/slog`'s level functions and `*Logger` methods, and `slog.Any` — must pass through `redact.Error`
````

NEW:

````text
`log/slog`'s level functions and `*Logger` methods, `slog.Any`, and since ADR 0011 `trace.Span.RecordError` and `otel.Handle` — must pass through `redact.Error`
````

**A.5.4**

OLD:

````text
It opens no Postgres connection and no Redis connection, and links no driver for either; `scripts/check_go_stdlib_only.sh` is the mechanical backstop, run by `go-tests.yml`.
````

NEW:

````text
It opens no Postgres connection and no Redis connection, and links no driver for either; `scripts/check_go_deps.sh` is the mechanical backstop, run by `go-tests.yml`: since ADR 0011 the relay may depend on the OpenTelemetry SDK and the Prometheus client, named in `relay/go.allowed-deps`, and nothing else, and it may not link `database/sql` or any Redis or Postgres driver.
````

**A.5.5**

OLD:

````text
What "the relay performs zero ORM reads" means now is `scripts/check_go_stdlib_only.sh` plus the empty `go.sum`: the Go binary links no Postgres driver, so the property is structural rather than asserted
````

NEW:

````text
What "the relay performs zero ORM reads" means now is `scripts/check_go_deps.sh`'s driver ban (ADR 0011; until then the stdlib-only check and an empty `go.sum`): the Go binary links no Postgres driver and no `database/sql`, so the property is structural rather than asserted
````

**A.5.6**

OLD:

````text
plus the stdlib-only and credential-logging assertions.
````

NEW:

````text
plus the dependency-allowlist and credential-logging assertions, and since ADR 0011 a blocking `govulncheck` job in `Go result`'s `needs`.
````
