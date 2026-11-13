# Observability: metrics, traces and logs

Mino can export OpenTelemetry metrics, traces and logs, and its relay serves a Prometheus
`/metrics` endpoint. This page says how to turn that on, what each process exports, and what the
limits are. The design and the reasons behind it are in
[`docs/superpowers/specs/2026-10-31-observability-design.md`](superpowers/specs/2026-10-31-observability-design.md)
and [ADR 0011](adr/0011-the-go-relay-takes-the-opentelemetry-sdk-and-keeps-the-driver-ban.md).
A starting Collector configuration is in
[`docs/observability/otel-collector.example.yaml`](observability/otel-collector.example.yaml).

**Everything is off until you configure it, except the relay's `/metrics`.** With none of the
variables below set, no exporter starts, no thread is added and no connection is opened. Logs stay
in the text format they have always had.

## 1. What you get

Each process in the container is its own OpenTelemetry resource. `service.instance.id` is a fresh
random UUID per process start.

| Program (supervisord) | `service.name` | `mino.program` | Signals over OTLP |
|---|---|---|---|
| `relay-go` | `mino-relay` | `relay-go` | metrics M1 to M9, traces, logs; plus `/metrics` |
| `api-uwsgi` | `mino-api` | `api-uwsgi` | M10, traces, logs |
| `relay-uwsgi` (VOD and catch-up) | `mino-api` | `relay-uwsgi` | M10, traces, logs |
| `daphne` | `mino-api` | `daphne` | M10, traces, logs |
| `celery-default` | `mino-worker` | `celery-default` | M11, traces, logs |
| `celery-dvr` (thread pool) | `mino-worker` | `celery-dvr` | M11, traces, logs |
| `celery-beat` | `mino-worker` | `celery-beat` | M11 (none run in beat), M12 to M14, traces, logs |

`service.version` is the application version on the Python processes. On `mino-relay` it comes from Go build info and is normally absent in a Docker build. Any `OTEL_RESOURCE_ATTRIBUTES`
you set are added (section 2).

Python processes use five instrumentations: Django, Celery, psycopg, Redis and `requests`. The
relay records its own spans (section 6).

## 2. Turning it on

OTLP is enabled in a process if and only if `OTEL_EXPORTER_OTLP_ENDPOINT` is set and non-empty and
`OTEL_SDK_DISABLED` is not `true`. Only OTLP over HTTP with protobuf is supported.

> **The K2 gevent soak has been run once, on a shared machine, and no worker hung.** The spec's
> risk K2 asks for one soak before OTLP is turned on anywhere that matters: a uWSGI worker under
> the project's own `gevent = 400`, polled for ten minutes with OTLP on, showing no hung worker.
> Upstream has open reports of deadlocks in the Python metric reader under gevent
> (opentelemetry-python #4345, #5788).
>
> The soak ran on 2026-11-13 against the published image built from `cf40b42e`, digest
> `sha256:38bd0cc633ff8a39d7cdea0c2773065d4313cf3fa3babb1483e06a0d98f4f9bf` (SDK 1.45.2, instrumentations 0.66b2, gevent 26.7.0, uWSGI 2.0.31). It used the
> all-in-one image with `docker/uwsgi.ini` unchanged: four workers and `gevent = 400`. Traces,
> metrics and logs all went to an OpenTelemetry Collector 0.165.0 over OTLP/HTTP. The settings
> were `OTEL_METRIC_EXPORT_INTERVAL=1000` (one export a second rather than one a minute), every
> trace sampled, and the API's `max-requests` raised so that a recycle could not hide a hang.
> The load was 100 concurrent clients through nginx, for 11 minutes, run twice. That is about 25
> requests in flight per worker, not 400: uWSGI's default listen backlog of 100 capped the load,
> and a pilot at 120 clients drew 9,071 502s from nginx. The clients
> requested `/api/core/version/`, an authenticated `/api/core/settings/` and, for one request
> in ten, a 404 that writes a log record.
>
> | | Run 1 | Run 2 |
> |---|---|---|
> | Requests (errors) | 1,153,361 (0) at 1,744/s | 543,052 (0) at 823/s |
> | Collector accepted: spans, metric points, log records (refused) | 2,924,650, 18,721, 115,327 (0) | 1,377,644, 16,661, 54,273 (0) |
> | 1 s poll: p50, p99, max | 0.046 s, 2.1 s, 6.5 s | 0.079 s, 3.6 s, 7.6 s |
> | Longest gap between one worker's metric exports | 6.5 s | 19.8 s |
>
> In both runs the four workers had the same PIDs before and after, with no harakiri and no
> respawn. Every worker exported metrics and served requests in every minute of the run, and the
> collector's counters for all three signals rose in every 30-second scrape. At the end,
> `py-spy dump` showed each worker idle in `Hub.run`, with no thread in the SDK.
>
> **The latency bounds set beforehand were missed.** There were three:
>
> - every poll answers within 5 seconds: missed in both runs (6.5 s and 7.6 s);
> - no gap between polls exceeds 6 seconds: missed in both runs (6.5 s and 7.6 s);
> - no gap between one worker's metric exports exceeds 10 seconds: met in run 1 (6.5 s), missed
>   in run 2 (19.8 s).
>
> The host was saturated by work outside the soak during both runs. Its load-average readings
> were unreliable (macOS's figure wrapped near 1024) and are not quoted. The evidence for
> saturation is how the slowdown spread. All four workers slowed evenly, and so did
> `celery-beat`, which serves no requests. The Go relay's exports kept to time. That fits CPU
> starvation and does not fit a lock, but this soak cannot rule out an SDK stall hidden inside
> it. Repeat it on a quiet machine before OTLP goes on in production. Record CPU idle as well as
> load, and raise uWSGI's `listen` so that each worker carries more greenlets.
>
> Until then, treat OTLP on the Python processes as experimental. If a worker hangs, set
> `OTEL_METRICS_EXPORTER=none` and report it. The relay is Go and is not affected.

| Variable | Behaviour |
|---|---|
| `OTEL_EXPORTER_OTLP_ENDPOINT` | Enables OTLP. Base URL for all three signals; `/v1/traces`, `/v1/metrics` and `/v1/logs` are appended. |
| `OTEL_EXPORTER_OTLP_{TRACES,METRICS,LOGS}_ENDPOINT` | Per-signal overrides. They do not enable OTLP on their own. |
| `OTEL_{TRACES,METRICS,LOGS}_EXPORTER` | `none` switches that one signal off. Any other value is ignored (always OTLP). Write it exactly as `none`: the relay matches that string exactly, while the Python processes trim it and ignore case, so `None` or ` none` switches a signal off in Python but not in the relay. |
| `OTEL_EXPORTER_OTLP_PROTOCOL` (and per-signal) | Only `http/protobuf` is supported. Any other value leaves OTLP **off** in that process and logs one WARNING naming the variable. |
| `OTEL_EXPORTER_OTLP_HEADERS` (and per-signal) | Honoured. **A credential.** Never logged. |
| `OTEL_EXPORTER_OTLP_TIMEOUT`, `..._CERTIFICATE`, `..._CLIENT_KEY`, `..._CLIENT_CERTIFICATE`, `..._COMPRESSION` | Honoured. |
| `OTEL_RESOURCE_ATTRIBUTES` | Exported as configured on every OTLP signal. Never on `/metrics`. |
| `OTEL_SERVICE_NAME` | **Ignored.** One container runs several services, each with its own fixed name. |
| `OTEL_TRACES_SAMPLER` | **Ignored.** The sampler is always parent-based over a ratio. |
| `OTEL_TRACES_SAMPLER_ARG` | The root sampling ratio, 0 to 1. Unset gives 1 (every trace). An unusable value gives 1 with a WARNING. |
| `OTEL_BSP_*`, `OTEL_BLRP_*`, `OTEL_METRIC_EXPORT_INTERVAL`, `OTEL_METRIC_EXPORT_TIMEOUT` | Honoured by the SDKs. The metric interval defaults to 60 seconds. |
| `OTEL_SDK_DISABLED` | `true` forces OTLP off. |
| `MINO_LOG_FORMAT` | `text` (default) or `json` (section 7). |

In the relay, a malformed OTLP header, endpoint, timeout, certificate path, metric interval or
metric timeout keeps OTLP **off** and logs one WARNING naming the variable, never its value.

Three things to get right:

- **`OTEL_EXPORTER_OTLP_HEADERS` is a credential.** Put it in a secret, not in a compose file or a
  manifest you commit.
- **`OTEL_RESOURCE_ATTRIBUTES` is trusted operator configuration.** It goes to the same Collector
  as the headers, unfiltered. Put labels in it such as the pod and the environment, and **never a
  secret**. It is never served on `/metrics`.
- A variable set on the container reaches every program in it. Supervisord passes its environment
  on, and each `[program:x]` adds to it rather than replacing it.

### Compose

In the modular compose file there are three services that run Mino code (`web`, `relay`, `celery`).
Set the same variables on all three. With the all-in-one image there is one service.

```yaml
x-observability: &observability
  OTEL_EXPORTER_OTLP_ENDPOINT: http://otel-collector:4318
  MINO_LOG_FORMAT: json
  OTEL_RESOURCE_ATTRIBUTES: deployment.environment=home
  OTEL_TRACES_SAMPLER_ARG: "0.25"
  # Keep this out of the file: use an env_file or a secret.
  # OTEL_EXPORTER_OTLP_HEADERS: "authorization=Bearer <token>"

services:
  web:
    environment:
      <<: *observability
  relay:
    environment:
      <<: *observability
  celery:
    environment:
      <<: *observability
```

(Merging with `<<:` needs the map form of `environment:`. Convert the list form the shipped file
uses, or add the variables to each list instead.)

### Kubernetes

```yaml
env:
  - name: POD_NAME
    valueFrom: { fieldRef: { fieldPath: metadata.name } }
  - name: POD_NAMESPACE
    valueFrom: { fieldRef: { fieldPath: metadata.namespace } }
  - name: OTEL_EXPORTER_OTLP_ENDPOINT
    value: http://otel-collector.observability.svc:4318
  - name: MINO_LOG_FORMAT
    value: json
  - name: OTEL_RESOURCE_ATTRIBUTES
    value: k8s.namespace.name=$(POD_NAMESPACE),k8s.pod.name=$(POD_NAME)
  - name: OTEL_EXPORTER_OTLP_HEADERS
    valueFrom:
      secretKeyRef:
        name: otlp-credentials
        key: headers
```

Kubernetes expands `$(NAME)` only for variables defined **earlier** in the list, which is why
`POD_NAME` and `POD_NAMESPACE` come first.

### uWSGI must be lazy

Python telemetry starts in each uWSGI worker after the fork. Every `docker/uwsgi*.ini` sets
`lazy-apps = true`, and a test fails if one does not (`tests/test_uwsgi_inis_are_lazy.py`). If you
supply your own uWSGI configuration, keep it. With `lazy-apps` off, uWSGI's master imports
`dispatcharr/wsgi.py` and the workers inherit the loaded application without importing it again, so
no worker exports anything. The master initialises nothing and logs one WARNING:
`telemetry not initialised in the uWSGI master: lazy-apps must be true`
(`tests/test_wsgi_uwsgi_master.py` pins this).

## 3. The metric catalogue

Names below are the Prometheus names the relay's `/metrics` serves, checked by a test against the
code. Python rows are what the SDK records; the name your backend shows depends on its OTLP
translation, so treat the Prometheus column for M10 to M14 as typical, not exact.

`channel_id` is the **numeric id shown in the channel list**, never the channel's UUID. `0` means
the relay did not know it (for instance a previewed stream). `kind` is `source` (the Stream
Profile's process), `output` (an Output Profile transcode), `fmp4` (the fMP4 remux) or `hls` (the
HLS pipeline). `profile_id` is the Output Profile id for `output` and for a profiled `fmp4` chain,
the HLS Output Profile id for `hls`, and `0` otherwise.

| # | Prometheus name | Type | Labels | What it is |
|---|---|---|---|---|
| M1 | `mino_relay_channels` | gauge | `state` | Channels by state. All eight states are always reported, `0` when none; an idle relay still exports the family. |
| M2 | `mino_relay_clients` | gauge | `channel_id`, `format` (`mpegts`/`fmp4`/`hls`), `profile_id` | Connected clients. |
| M3 | `mino_relay_client_sent_bytes_total` | counter | `channel_id`, `format` | Bytes written to clients, keepalive packets included. |
| M4 | `mino_relay_failovers_total` | counter | `channel_id`, `trigger` (`health_monitor`/`max_retries_exceeded`/`buffering_timeout`), `outcome` (`switched`/`no_alternate`/`unresolved`/`same_url`/`no_resolver`) | Failover attempts and how each ended. |
| M5 | `mino_relay_hls_sessions` | gauge | none | HLS sessions. |
| M6 | `mino_relay_rewind_disk_usage_bytes` | gauge | none | Rewind store bytes on disk. |
| M7 | `mino_relay_rewind_disk_limit_bytes` | gauge | none | Rewind disk cap. Not reported while the cap is unset. |
| M8 | `mino_relay_process_cpu_seconds_total` | counter | `channel_id`, `kind`, `profile_id` | CPU time of the relay's child processes, per channel. Linux only. |
| M9 | `mino_relay_process_memory_rss_bytes` | gauge | `channel_id`, `kind`, `profile_id` | Resident memory of the same processes. Linux only. |
| M10 | `mino_api_http_server_request_duration_seconds` | histogram | `http_request_method`, `http_route`, `http_response_status_code` | Request duration in the Django processes. Rate, errors and duration all come from this one histogram. |
| M11 | `mino_worker_task_duration_seconds` | histogram | `task`, `outcome` (`SUCCESS`/`FAILURE`/`RETRY`/`REVOKED`) | Celery task duration. |
| M12 | `mino_worker_queue_depth` | gauge | `queue` (`celery`/`dvr`) | Messages waiting in each Celery queue. Beat only. |
| M13 | `mino_worker_provider_slots_in_use` | gauge | `m3u_profile_id` | Provider slots held, per active M3U profile. Beat only. |
| M14 | `mino_worker_provider_slots_limit` | gauge | `m3u_profile_id` | Provider slot limit; `0` means unlimited. Beat only. |

**Which channel's transcode is using the CPU?**

```promql
topk(5, sum by (channel_id, kind, profile_id) (rate(mino_relay_process_cpu_seconds_total[5m])))
```

A rate of 1.0 is one core. A multithreaded ffmpeg can exceed it.

**Cardinality.** Series exist per live channel and per profile in use, which at household scale is
tens. Counters keep a series for every channel ever watched until the relay restarts. The Go SDK's
per-instrument limit (2,000 attribute sets by default) stays in force; beyond it, new sets fold into
one series labelled `otel.metric.overflow="true"`.

## 4. Scraping the relay

The relay serves `GET /metrics` on its own port, 5658 by default (`DISPATCHARR_RELAY_GO_PORT`),
and always, whether or not OTLP is on. **nginx does not route `/metrics`**, and a test pins that.
Scrape the relay's port directly, never the port you publish for the web UI: a request for
`/metrics` there gets the web app's HTML.

`/metrics` carries no `target_info` and no scope labels, by design: the resource (which can hold
`OTEL_RESOURCE_ATTRIBUTES`) never reaches an unauthenticated endpoint. Series carry only the labels
in section 3.

**Push or scrape, not both into one backend.** With OTLP on, the relay pushes the same instruments
it serves. Ingesting both doubles every series. The example Collector config receives OTLP and
also contains a scrape job; it enables one metrics path and leaves the other commented out.
To scrape the relay and still push everything else, set `OTEL_METRICS_EXPORTER=none` on the relay
and enable both Collector pipelines: the relay's metrics then arrive by scrape only, and its traces
and logs still push. In the all-in-one image one container holds every program and the variable
reaches all of them, so it also turns off the Python metrics M10 to M14 there; with the modular
compose files set it on the `relay` service only.

## 5. Network exposure

`/metrics` has **no authentication**. What it reveals is bounded: numeric ids, formats, counts and
byte totals. It carries no UUID and no URL. It does tell a reader which channels are being watched
and how heavily, so keep it off networks that should not know that.

In the all-in-one image the relay's port is not published; only the container's own network sees
it. In Kubernetes, admit ingress to the relay pod only from the pods that need it. The relay role
runs two listeners: `relay-uwsgi` on 5657 (VOD, catch-up and recordings, reached by nginx) and
`relay-go` on 5658 (live, HLS, `/proxy/relay/` and `/metrics`). nginx needs both. The collector or
Prometheus needs 5658 only. Django's control calls to `/proxy/relay/` go through nginx by default,
not straight to the relay, so no Django pod needs a rule.

```yaml
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: mino-relay-ingress
spec:
  podSelector:
    matchLabels: { app.kubernetes.io/name: mino-relay }
  policyTypes: [Ingress]
  ingress:
    - from:
        - podSelector: { matchLabels: { app.kubernetes.io/name: mino-web } }      # nginx
      ports:
        - { protocol: TCP, port: 5657 }
        - { protocol: TCP, port: 5658 }
    - from:
        - namespaceSelector: { matchLabels: { kubernetes.io/metadata.name: observability } }
          podSelector: { matchLabels: { app.kubernetes.io/name: otel-collector } }
      ports:
        - { protocol: TCP, port: 5658 }
```

Adjust the labels to your own. A Django pod needs a rule on 5658 only if
`DISPATCHARR_RELAY_BASE_URL` points it straight at the relay instead of at nginx.

## 6. Traces

```
nginx auth_request ──> Django: the authorize hop            [server span, root]
                         └─ response header X-Relay-Traceparent
nginx proxy_pass   ──> relay: relay.tune                      [server span, child]
                         ├─ relay.authorize                   [client; dev shape only]
                         ├─ relay.next_source                 [client]
                         │    └─ Django: POST /api/relay/channels/<id>/next-source [server]
                         └─ ends at the first byte written to this client
later:  relay.failover        [root, linked to the channel's relay.tune]
          └─ relay.next_source └─ Django next-source [server]
Django admin request [server span]
  └─ requests.request to the relay [client span, injects its own traceparent]
       └─ relay.stream_switch [linked to the channel's relay.tune]
```

- **The tune trace** starts in Django's authorize hop, because nginx's `auth_request` runs before
  the relay sees the request. Django returns its context in the `X-Relay-Traceparent` response
  header and nginx forwards it to the relay.
- **`X-Relay-Traceparent` is trusted only behind nginx's authorization marker.** A client cannot
  choose a trace id or force sampling: no public route extracts a client's `traceparent` or
  `tracestate`, on either side. `tracestate` is dropped everywhere in the relay.
- The header's trace flags are `03`: sampled (`01`) plus the W3C Level 2 random-trace-id flag
  (`02`). A parser that rejects flags other than `00` and `01` will reject it.
- `relay.tune` ends at the first byte written to the client. A keepalive or error packet counts as
  that byte.
- **Most relay log lines carry no trace id.** Most relay log calls are written without a context,
  and none was rewritten to add one. Spans, not log correlation, are the supported way to follow a
  tune.
- Sampling is parent-based over `OTEL_TRACES_SAMPLER_ARG` (section 2).

## 7. Logs

`MINO_LOG_FORMAT=text` is the default and is byte-identical to what Mino has always logged.
`MINO_LOG_FORMAT=json` writes one JSON object per line from the Python processes and from the
relay. Any other value is treated as `text`, with one WARNING giving the value's length and never
the value.

Record keys:

| Key | Python | Go (relay) |
|---|---|---|
| `time` | RFC 3339 UTC, microseconds | RFC 3339 UTC, milliseconds |
| `level` | `TRACE`, `DEBUG`, `INFO`, `WARNING`, `ERROR`, `CRITICAL` | `DEBUG`, `INFO`, `WARN`, `ERROR` |
| `msg` | the message, scrubbed | the message, scrubbed |
| `logger` | logger name | absent |
| `service.name`, `mino.program` | section 1 | `mino-relay`, `relay-go` |
| `trace_id`, `span_id` | present only inside a valid span | same |
| `exception.type`, `mino.exception.frames` | exception class and a `file:line in function` list, innermost last; no message, no source | absent (errors appear as `<key>.type` fields) |
| `channel_id` | absent | the numeric id; `0` when unknown |

**Lines that stay text** whatever the setting, because they never pass through the logging
frameworks: uWSGI's request log, supervisord, nginx, PostgreSQL, Redis and the `print` calls in the
process start-up files.

### Two standards, stated plainly

- **Structured log fields are allowlisted by construction.** Python keeps the code location, the
  exception type and the frame list, and drops anything passed as `extra=`. The relay keeps only
  the typed fields listed in `relay/telemetry/logkeys.go`; an unlisted key is dropped.
- **Log bodies, in JSON and over OTLP, get best-effort scrubbing** of URLs, paths, UUIDs, HLS
  tokens, long hex strings and `key=value` secrets. **This is no stronger than stdout.** A body can
  still carry exception text a call site interpolates, such as Celery's failure and retry messages.
  Do not send logs to a backend you would not send your stdout to.

### The log scrubber (Python processes)

Every Python process (the two uWSGI processes, Celery, beat, Daphne, `manage.py`) installs a log
record factory when it imports the Django project package (`log_scrub.py`, in that package). It runs when
a record is created, so it protects the text format, JSON and OTLP alike, and a handler added later
needs no configuration to benefit. It is **best effort, not a proof**.

- **What it masks.** Per whitespace-delimited token: URL userinfo (`http://user:pass@host` becomes
  `http://***@host`); and, from the first credential position to the **end of the token**, the value
  after a `username`, `password`, `token` or `api_key` assignment (any case, raw or percent-encoded
  name, in a query, a fragment or a bare assignment), the segments after `live/`, `movie/`,
  `series/` or `timeshift/`, and the path of a `/<user>/<pass>/<digits>` route. The OIDC parameter
  names (`code`, `state`, `id_token`, `client_secret`, and the other members of
  `SENSITIVE_QUERY_KEYS`) are masked where they follow `?`, `&` or `#`, by name equality; `id_token`, `access_token` and `refresh_token` are covered by the `token` rule anywhere. A bare `client_secret=abc` or `state=x` in free text is not masked. It also masks the same
  carriers in a traceback and in `stack_info`, which is where a `requests` exception carries the
  provider URL.
- **It over-masks on purpose.** `Not Found: /api/channels/5/` prints as `Not Found: /***`,
  `get.php?username=u&page=2` as `get.php?username=***`, `csrf_token=abc` as `csrf_token=***`, and a
  call site's own `redact_url` output `.../live/***/***/1.ts` as `.../live/***`. Text it does not
  match is left byte-identical.
- **Limits.** The scan reads at most 16,384 characters of a message and 65,536 of a traceback (the
  tail is kept); longer text is cut at whitespace with a `[log scrubber: truncated from N
  characters]` marker. If the scrubber itself fails, the record is still emitted with the text
  replaced by a placeholder naming only the exception type.
- **What it cannot catch:** opaque path tokens in non-Xtream URLs, credentials under other
  parameter names (`user=`, `pass=`, `key=`), scheme-less `user:pass@host`, a credential split by
  whitespace (`/live/user/my pass/1.ts`), `key: value`, JSON and dict forms, the relative
  `user/pass/123.ts` route with no leading slash, a bare query string or form body whose first
  parameter is an equality key (`code=S&state=T` leaks the code), bare secrets, handlers
  that serialise exception objects or `extra=` themselves, plugin code that replaces the record
  factory (the scrubber re-installs itself after plugin discovery), `print` calls, and every line
  that never passes through Python `logging`: the uWSGI and nginx request logs, and the text
  persisted in `last_message` columns or sent over the WebSocket, which are separate follow-ups.
- **Celery.** Its noise filter now drops only records at INFO or below, so a rewritten error can
  never be suppressed.

### Known quirks

- **Text format with OTLP logs on.** In the relay, with `MINO_LOG_FORMAT=text`, lines written
  through Go's `log.Printf` do **not** reach OTLP; lines written through `slog` reach both. The
  alternative deadlocks, because the slog default handler writes back through package `log`. JSON
  mode is unaffected: there, `log.Printf` lines go through the JSON handler and the OTLP bridge.
  If you want OTLP logs from the relay, use `MINO_LOG_FORMAT=json`.
- **A torn-down channel's last log lines show `channel_id` as 0.** The relay maps a UUID to its
  numeric id in memory and deletes the mapping with the channel, so a line written after teardown
  cannot be mapped. This is the safe direction: the UUID is never emitted instead.
- In JSON and OTLP output the relay's start-up line naming the export endpoint reads
  `http://host:port/[redacted]`; the text format shows `http://host:port`.

## 8. Limits

- **Loss on restart.** A process loses at most one unsent batch of spans and logs, and at most one
  metric interval of points. The relay flushes with a two-second budget after its drain, and Celery
  processes flush with the same budget on shutdown; no flush hook is installed in the uWSGI
  or Daphne processes. Data produced while the collector is unreachable is dropped,
  not queued.
- **Process metrics are Linux only.** On other platforms M8 and M9 have no points.
- **M8 is a lower bound.** It is accumulated per process identity and never decreases, but it loses
  the CPU a process accrued after its last observation, which for a short-lived process can be all
  of it. A multithreaded ffmpeg can accrue several CPU-seconds per second, and a slow collection
  widens the gap. A process that leaves its process group and later rejoins has the CPU it used
  while outside credited to the group when it rejoins; ffmpeg, VLC and Streamlink do not do this.
  The relay forgets an identity after eight consecutive snapshots that do not list it, which bounds
  memory; its CPU stays in the total.
- **A relay restart starts every M8 series again** (a counter reset, with a new start time).
- **M9 after a failed `/proc` read.** If a procstat snapshot fails, M9 emits no point for that
  collection rather than a false zero, and the relay logs one rate-limited WARNING naming the error
  type only. M8 keeps reporting its accumulator.
- **M11 uses the SDK's default histogram buckets**, which run from 0 to 10,000 seconds. Every task
  that finishes in under 5 seconds lands in one bucket, so quantiles for fast tasks are
  meaningless. Use the sum and count for averages. Celery's `IGNORED` and `REJECTED` outcomes are
  not recorded.
- **M12 to M14 come from beat only**, one process per deployment. Kombu priority sub-queues are not
  counted in M12.
- **M1 reports 0 for every state** on an idle relay.
- **Exemplars are off.**
- **JSON and OTLP structured fields carry a channel's numeric id** where the text format carries
  its UUID.
- **Span status, span events and structured exception fields carry an exception's type, never its
  message. Log bodies are not so restricted** (section 7).
- **HLS silence and Quick Sync detection processes are not tracked** by M8 and M9. They run for
  seconds and own no channel.
- **The OpenTelemetry auto SDK warns at start-up about a bad limit variable.** The relay links
  `go.opentelemetry.io/auto/sdk`, which writes a warning at package initialisation, before
  `main` runs and even with OTLP off, with the raw value of any `OTEL_*_LIMIT` variable it cannot
  parse (the span, event, link and attribute limits). These are numeric limits, not credentials,
  and Mino cannot suppress the warning.
- **The Python OTLP path has had no gevent soak** (section 2). Do not enable it on a production
  instance until that is done.
- **The dvr worker's plugin discovery gap** (#632) is separate from telemetry and is not fixed by
  it. The dvr worker's telemetry starts from `worker_init`, because the thread pool never sends
  `worker_process_init`.
