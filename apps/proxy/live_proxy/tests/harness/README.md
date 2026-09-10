# The stage-2a subprocess harness

A real-subprocess, real-fake-upstream, real-Redis harness for stage 2a of the
Phase 2 relay extraction. It gives the backend suite a capability it has
never had before: the first backend tests in this repository that spawn a
process.

## The stated rule

> **Every spawn is real.** The child program is the stand-in when the test's
> subject is the relay's *reaction* to what a process said or did — a stderr
> line, an exit code, an exit moment, a byte rate — because those must be
> exact and a real ffmpeg cannot be made exact on demand. The child program
> is real `ffmpeg` when the test's subject is the *bytes a remuxer produces*.
> It is never a Python object standing in for a process.
>
> **And every line the stand-in writes to stderr came out of a real
> ffmpeg.** The corpus in `harness/fixtures/ffmpeg_stderr/` was captured
> from ffmpeg 8.1.2 against a real upstream, and the stand-in replays it. A
> hand-written progress line is legitimate only for a shape real ffmpeg
> cannot be made to emit on demand, and carries a comment saying which shape
> and why. Without that rule, real-subprocess-throughout collapses straight
> back into the gap `CLAUDE.md` § Testing used to name — "ffmpeg lifecycle
> and stderr parsing run only against hand-written strings there" — with
> rows 1-6 of the parity matrix asserting that our parser parses our own
> fiction.

## How a spawn is reached without a patch

Every spawn in this harness goes through the relay's own **unmodified**
`os.posix_spawn` call sites. What the child *runs* is chosen through two
production mechanisms, not a patch:

1. **`StreamProfile.command` / `parameters` is a database row.**
   `core/models.py:137-160`'s `build_command()` is data-driven, and
   `apps/proxy/live_proxy/input/manager.py:747`'s `os.posix_spawn` (`:793`)
   takes it verbatim. `stand_in_stream_profile()` creates a `StreamProfile`
   whose `command` is the literal string `ffmpeg` — which also selects the
   ffmpeg log parser (`input/manager.py:750-758`), needed for the
   buffering-detector rows.
2. **`PATH`.** `output/fmp4/manager.py:32`'s `FFMPEG_REMUX_CMD` is a module
   constant whose first element is the bare string `"ffmpeg"`, resolved by
   `shutil.which(cmd[0])` inside `posix_spawn_proc`
   (`apps/proxy/live_proxy/utils.py:130`). `StandInBin` writes an executable
   named `ffmpeg` into a temp directory and prepends it to `PATH`, so this
   spawn — and `output/profile/manager.py:88`'s `OutputProfile`-driven spawn
   — resolve to the stand-in too, with no production-code change.

## The composition rule

Drive the relay through its HTTP surface against real dependencies; assert
on observable behaviour (bytes, status fields, events) — never on an internal
call count, and never against mocks of `server.py`'s or `input/manager.py`'s
internals. **The one exception is `test_harness_smoke.py`**, whose subject
is the harness itself: it is the only file allowed to read a spawned
process's pid or reach into `ProxyServer`'s internal dict.

## Writing a test

```python
from .harness.process import StandInBin, stand_in_stream_profile
from .harness.relay import RelayHarnessTestCase


class MyTests(RelayHarnessTestCase):
    def test_something(self):
        with StandInBin():
            profile = stand_in_stream_profile()
            channel = self.make_channel(upstream_url=self.upstream.url, profile=profile)
            with self.tuned(channel) as stream:
                body = stream.read(20 * 188)
                # assert on `body`, or on GET /proxy/ts/status/<uuid>, or on
                # a SystemEvent/WebSocket event -- never on an internal call.
            self.stop_channel(channel)
```

## Driving the control surfaces

```python
from .harness.control import ControlMixin, nginx_headers, open_tune
from .harness.relay import RelayHarnessTestCase


class MyTests(ControlMixin, RelayHarnessTestCase):
    def test_something(self):
        with self.stand_in():
            profile = stand_in_stream_profile()
            channel = self.make_channel(upstream_url=self.upstream.url, profile=profile)
            self.set_proxy_setting(new_client_behind_seconds=0.5)
            with self.tuned(channel):
                _, reader = open_tune(self, channel, headers=nginx_headers(channel, "my-client"))
                reader.read(4 * 188)
                status_code, body = self.status(channel)
                self.change_stream(channel, other.url)
                self.stop_client(channel, "my-client")
                self.stop_channel_over_http(channel)
```

- The admin principal is a real `User` row with an `api_key`, sent as `X-API-Key`, created on first use and gone with the test's flush.
- `nginx_headers()` is nginx's own contract, not a test seam — `X-Dispatcharr-Authorized` carries `HMAC(SECRET_KEY, "relay-trust")` and `resolve_authorization()` trusts `X-Relay-Client` only when it matches, which is the only way to choose a client id because `stream_ts` otherwise mints one.
- `set_proxy_setting()` writes the whole group, clears `TSConfig._proxy_settings_cache` and registers the cleanup that clears it again, because that cache is a class attribute with a 10-second TTL and an override left behind leaks into unrelated tests.
- `open_tune()` is not a context manager, because a test with several simultaneous clients needs them all open at once; the responses are closed by `addCleanup`.

## The fault vocabulary

`e2e-upstream/src/faults.ts` declares twelve faults. Eight are live-TS faults
and are ported to `harness.faults`; four belong to surfaces D1 leaves in
Python and are recorded in `NOT_PORTED` with a reason, so 2c's Go fixtures
can see the whole twelve and why four are missing.

| Fault | Ported | Shape at the upstream | Serves |
|---|---|---|---|
| `dead-air` | yes | headers sent, then nothing; socket stays open | matrix row 2 |
| `slow-trickle` | yes | pace output at `rate` × the nominal byte rate | rows 1, 4 |
| `disconnect` | yes | close after `after_bytes`; `clean` chooses shutdown vs. abrupt | mid-stream truncation |
| `not-found` | yes | 404 before any body | row 3 |
| `auth-failure` | yes | 401 | row 3 |
| `connection-limit` | yes | 429 | row 3 |
| `redirect-chain` | yes | `depth` × 302 then the real body | URL resolution |
| `non-ts-bytes` | yes | 200 with an HTML error page | row 9 (realignment) |
| `xc-auth-envelope` | no | XC `player_api.php` envelope — not a live-TS surface | — |
| `no-tv-archive` | no | XC catch-up advertisement — Phase 3's scope | — |
| `catchup-layout-404` | no | catch-up URL layout — Phase 3's scope | — |
| `range-unsupported` | no | VOD `Range` handling — D1 leaves VOD in Python | — |

## The stderr corpus

Three fixtures under `fixtures/ffmpeg_stderr/`: `normal.stderr` (a healthy
tune), `slow-trickle.stderr` (a genuinely 0.25×-real-time upstream — proof
that `speed=` is a cumulative average taking tens of seconds to arm and
cross below 1.0, parity-matrix row 4), and `truncation.stderr` (a single
progress record in scientific notation, `speed=…e+03x` — the shape behind
[#227](https://github.com/D10Scot/Dispatcharr/issues/227)). **They are
verbatim captures and must never be hand-edited.** Regenerate with
`scripts/capture_ffmpeg_stderr.py`; see `fixtures/ffmpeg_stderr/CAPTURE.md`
for the exact command and provenance.

`harness.ffmpeg_stderr.SYNTHETIC` is the **only** place a hand-written
stderr line may be declared — with the reason real ffmpeg cannot be made to
emit that shape on demand. It is empty today.

## Time

- `buffering_timeout`/`buffering_speed` (`CoreSettings` `proxy_settings`) and
  `BUFFER_CHUNK_SIZE` (a `BaseConfig` class attribute) are compressible
  through the real production levers — write the setting and clear the
  cache, or `patch.object` the config class. `RelayHarnessTestCase` already
  patches `BUFFER_CHUNK_SIZE` down to 1,880 bytes.
- `health_check_interval` and `CONNECTION_TIMEOUT` are compressible with
  `unittest.mock.patch.object`.
- `max_unhealthy_checks = 3`, `action_cooldown = 30` and `stable_time >= 30`
  in `_monitor_health` are **bare literals and cannot be compressed** —
  budget `3 × health_check_interval` for a dead-air test.
- Every wait is a deadline poll: `harness.relay.wait_until(predicate,
  timeout, interval)`. No test sleeps for a fixed duration.
- Stage budget: ≤ 15 s added across all of stage 2a; this PR's own budget is
  ≤ 6 s added to `apps.proxy.live_proxy`.

## Two environment facts that bite

- **ffmpeg needs `LD_LIBRARY_PATH=/usr/local/lib`** in both test containers
  (the hook container and `backend-tests.yml`) — the image carries two
  `librist` and `ld.so.conf` picks the wrong one. `require_real_ffmpeg()`
  and `ffmpeg_env()` handle this; see #226.
- **`manage.py test` is not gevent-monkey-patched.** The patch is applied
  only by `dispatcharr/gevent_patch.py`, imported from the uWSGI ini files.
  The relay's background threads under test are ordinary daemon threads,
  and `gevent.sleep()` inside them still works — gevent creates a hub per
  thread.

## Three traps for the tests that come next

- **`TransactionTestCase` flushes every table after each test, including
  migration-seeded rows.** Once a `RelayHarnessTestCase` has run, the locked
  `ffmpeg` `StreamProfile` and the `CoreSettings` groups are gone for the
  rest of the process. **A harness test creates every row it needs** — do
  not assume a seeded row survives past the first `RelayHarnessTestCase`.
- **Do not reach for `rate=None` on the upstream.** It measured 34 MB/s into
  Redis — see `FakeUpstream`'s docstring. DB 0 is shared with the Celery
  broker and the Django cache, so an unpaced tune held open for a dead-air
  cycle or a buffering window takes the whole test process down with it.
- **A client's read is not throttled to production pacing, even though
  production itself genuinely is.** `FakeUpstream` really does pace its
  writes (`rate * NOMINAL_BYTE_RATE`, `upstream.py`'s `_stream` -- see the
  comment there). What makes an elapsed-time assertion unreliable is one
  layer further in: the relay reads ahead of any client into Redis, and the
  generator serves a client from Redis rather than from the upstream
  connection directly, so a client's read is never throttled by that
  pacing -- it finishes as fast as Redis and the network allow, regardless
  of how recently the chunk was written or how far "behind live" the
  client claims to be positioned. A test whose subject is POSITION rather
  than throughput cannot rely on elapsed read time to show it: a client
  positioned behind live and one positioned exactly at the head can both
  drain a requested amount near-instantly, because both may be reading
  data that already exists. **This is a margin problem more than an
  absolute one, which is worse in a suite, not better**: an under-margined
  timing assertion does not reliably fail *or* reliably pass against a
  broken mechanism -- measured 1 red of 5 runs on one such assertion,
  not 0 and not 5. A test that sometimes shows red still reads as
  "covered" between those runs, which is a harder trap to notice than one
  that is simply always green. Assert on WHAT is delivered instead --
  content, a quantity, a sequence marker -- never on HOW FAST it arrives.
  Content *presence* alone is not enough either if the payload has any
  periodicity: `synthetic_ts()`'s old payload repeated every 256 packets,
  so "this content appeared somewhere earlier" was true even for the
  newest packet. Its `packet_index()` (`harness/asset.py`) embeds each
  packet's true index instead, unambiguous at any distance, which is what
  `test_a_new_client_starts_behind_live` (`test_relay_stream_switch.py`)
  now asserts on -- the quantity of backlog a joining client is handed,
  not the time it takes to receive it.

## What this harness deliberately does not do

No nginx — there is no `auth_request` subrequest, so a tune authorizes
inline through `authorize_stream`. No second process for the control plane —
one Django `LiveServerTestCase` instance serves both `/proxy/ts/stream/...`
and `/api/relay/...` / `/proxy/relay/...`, the same one-process-serves-both
shape `CLAUDE.md` documents for `DISPATCHARR_ENV=dev` under
`manage.py runserver`. No Docker.
