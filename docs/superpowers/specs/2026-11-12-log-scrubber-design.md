# Central log scrubber for provider-supplied text

- **Status:** draft for internal review.
- **Seed SHA:** `1302b665` (`origin/main`, after #642). Every `file:line` below was read at that SHA; line numbers drift.
- **Authority:** the owner's ruling **R15** (2026-11-12): handle provider-supplied text in log lines with a **central log scrubber**, not by editing each call site to log IDs only. CLAUDE.md (§ Architecture, § Known defects and traps → Security, § Test hooks), the observability spec `docs/superpowers/specs/2026-10-31-observability-design.md` (D8, D9, ruling R-Q17), and the two merged leak fixes it follows: #636 (`0c142c15`, M3U profile search/replace patterns) and #642 (`1302b665`, URLs, record dumps, headers and exception text on the M3U refresh path).
- **Execution:** implement this spec PR by PR with subagents, per CLAUDE.md § Delegation for phase work (`implement-review-escalate`, `pr-merge-gate`). Security-adjacent: reviews run on `fable` from round one.
- **Scope line:** log hygiene. Not a logging rewrite, not structured logging, not a change to what any call site logs.

## 1. Summary

1. One function, `scrub_text`, masks credential carriers in free text: URL userinfo, the values of `username`/`password`/`token`/`api_key` query parameters, and Xtream path credentials (`/live|movie|series|timeshift/<user>/<pass>/…` anywhere, the bare `/<user>/<pass>/<id>` root route when the path starts with `/`). It reuses `redact_url`'s own primitives, so it masks exactly what `redact_url` masks and nothing else.
2. It runs **once per log record, at record creation**, from a chained `logging.setLogRecordFactory` installed by `dispatcharr/__init__.py` before anything else in the package. Every Python process here (uWSGI API and relay, Celery workers and beat, Daphne, `manage.py`) imports that package first, and a record factory sees every record whatever handler later emits it. No `LOGGING` entry is needed, so no handler can be added without it.
3. It rewrites `record.msg`/`record.args` only when the rendered message changed; an untouched record keeps its template and arguments, so the text format stays byte-identical for every line that carries no carrier.
4. Exception tracebacks and `stack_info` are pre-rendered into `record.exc_text` (and `stack_info`) and scrubbed the same way, because a `requests` exception message carries the full request URL, query credentials included (`apps/epg/tasks.py:853`).
5. Every check is linear. The message examined is capped at 16,384 characters (traceback 65,536, tail kept); text past the cap is withheld, never emitted unexamined. Measured worst case at the cap: 1.5 ms (§ 12).
6. If the scrubber raises, the record is still emitted with a fixed placeholder naming only the exception type; the caller never sees an exception and the original text is never logged. A message whose `%` formatting fails is withheld the same way, which also closes `logging`'s own "--- Logging error ---" dump of the raw arguments to stderr.
7. The JSON formatter and the OTLP exporter keep their D9 `redact_text` pass unchanged; the scrubber runs upstream of both and touches no structured attribute. `redact_text` itself has two **super-linear** patterns (measured: 18 s on a 32,000-character line), a live hub-stall when JSON or OTLP logging is on; PR LS-2 makes them linear without changing their output.
8. `_loggable_name` stays where it is (it withholds, which is stronger than masking). The Go relay is out of scope (`relay/redact.Line` already scrubs structurally). Persisted and client-visible text (`M3UAccount.last_message`, `EPGSource.last_message`, WebSocket error payloads) is out of scope and named as a follow-up with evidence.
9. Three PRs: LS-1 moves the URL-redaction primitives into a stdlib-only leaf module (needed because `dispatcharr/utils.py` imports `core.models`); LS-2 makes `redact_text` linear; LS-3 is the scrubber, its installation and its tests.
10. What it cannot catch is listed in § 7: opaque path tokens in non-Xtream URLs, non-standard credential parameter names, scheme-less `user:pass@host`, bare secrets, plugin code that replaces the factory, and every line that never passes through Python `logging` (the uWSGI and nginx request logs carry Dispatcharr users' Xtream credentials today).

## 2. Decisions

| # | Decision | Section |
|---|---|---|
| D1 | The scrubber is a chained `LogRecordFactory`, not a `logging.Filter` on handlers and not a call-site helper | § 4.1 |
| D2 | It masks `redact_url`'s carriers only (userinfo, four query keys, Xtream paths); it does not reduce a URL to its host the way `relay/redact.Line` does | § 4.3, Q1 |
| D3 | It rewrites a record only when the rendered text changed; already-redacted text is a fixed point | § 4.2, § 5 |
| D4 | Fixed caps (16,384 message, 65,536 traceback), not configurable; overflow is withheld with a count | § 4.4, Q2 |
| D5 | On its own failure it emits a placeholder, never the original and never an exception | § 4.5 |
| D6 | Installed in `dispatcharr/__init__.py`; re-asserted after plugin discovery (`apps/plugins/loader.py:65`), which re-wraps a factory a plugin replaced | § 4.6 |
| D7 | `redact_text`'s two super-linear patterns are rewritten to linear equivalents with identical output (LS-2) | § 6.2, Q3 |
| D8 | `_loggable_name`/`_LoggableText` stay in `apps/m3u/tasks.py` unchanged | § 6.3 |
| D9 | Go is out of scope; persisted/client-visible text and the request logs are follow-ups | § 6.4, § 8 |

## 3. Inventory

### 3.1 Method and count

"About 35" was an estimate from #642's review. Re-counted at the seed with a deliberately broad single-line grep (multi-line calls are missed, so this is a floor):

```bash
cd <worktree> && grep -rnE "logger\.(trace|debug|info|warning|warn|error|exception|critical|log)\(" apps core dispatcharr --include='*.py' \
  | grep -v "/tests/\|/migrations/" \
  | grep -E "\b(account|m3u_account|acc|profile|epg_source|source|epg|channel|group|channel_group|stream|category|cat|movie|series|episode|vod|program|programme|obj|instance|user|plugin|logo|recording|rule|event)\.(name|title|channel_name|category_name|tvg_name|tvg_id|display_name)\b|group_title|category_name|\bgroup_name\b|\bstream_name\b|\bchannel_name\b|\btvg_name\b|\btvg_id\b|\bprogram_title\b|\['name'\]|\[\"name\"\]|get\(['\"]name|\bname\}|%s.*\bname\b"
```

It returns **139** lines; the four in `apps/backups/tasks.py` (`:28`, `:30`, `:41`, `:89`) log local backup filenames and carry no provider text, leaving **135** name-bearing sites:

| File | Lines | What they carry | Origin |
|---|---|---|---|
| `apps/epg/tasks.py` | 32 | EPG source name (`:105`, `:517`, `:541`–`:549`, `:616`, `:853`–`:943`, `:2162`–`:2435`), XMLTV `tvg_id` and display name (`:1348`–`:1376`, `:1675`–`:1914`) | operator; provider XMLTV |
| `apps/vod/tasks.py` | 27 | account name (`:64`–`:240`, `:424`, `:811`), category, movie, series and episode names (`:344`, `:380`, `:395`, `:449`–`:457`, `:560`, `:677`, `:835`–`:1047`, `:1398`–`:2038`) | operator; provider XC API |
| `apps/m3u/tasks.py` | 18 | channel group name (`:968`–`:1050`, `:1281`, `:1950`, `:1965`, `:2602`), account name (`:1838`, `:2238`, `:3255`–`:3408`), profile name (`:3253`, `:3446`–`:3453`) | provider M3U; operator |
| `apps/proxy/vod_proxy/views.py` | 16 | movie, episode and series names (`:309`, `:384`, `:423`–`:429`), provider account name (`:325`–`:459`, `:879`), profile name (`:605`) | provider; operator |
| `apps/epg/sd_tasks.py` | 7 | source name, `tvg_id` (`:416`–`:1819`) | operator; provider |
| `apps/output/epg.py` | 5 | channel name (`:173`–`:1041`) | operator or provider-derived |
| `apps/epg/api_views.py` | 5 | channel name (`:526`–`:602`) | operator or provider-derived |
| `apps/channels/tasks.py` | 4 | channel name, `tvg_id` (`:286`, `:407`, `:1496`, `:2145`) | operator or provider-derived |
| `apps/channels/epg_matching.py` | 4 | EPG and channel names (`:457`–`:848`) | provider; operator |
| `apps/proxy/vod_proxy/multi_worker_connection_manager.py` | 3 | profile name (`:1003`, `:1058`, `:1069`) | operator |
| `apps/proxy/next_source.py` | 3 | stream name (`:507`, `:639`), stream profile name (`:662`) | provider; operator |
| `apps/plugins/tasks.py` | 3 | plugin repository name (`:23`–`:33`) | operator |
| `apps/channels/signals.py` | 3 | channel name, `tvg_id` (`:26`, `:189`, `:194`) | operator or provider-derived |
| `apps/epg/signals.py` | 2 | dummy EPG source name (`:66`, `:77`) | operator |
| `apps/channels/api_views.py` | 2 | logo name (`:2609`, `:2796`) | provider-derived |
| `apps/vod/api_views.py` | 1 | series name (`:403`) | provider |

The count is concentrated where #642 said (`apps/m3u/`, `apps/epg/`, `apps/vod/`, the VOD proxy), but it is about four times the estimate, which is itself the argument for R15: a per-site edit would touch 135 lines in 16 files and every future log call.

### 3.2 The larger class: exception text

Names are the class R15 named. The class that actually carries credentials today is **exception text**, which the call-site checker is documented as blind to (`scripts/check_credential_logging.py`'s header; the observability spec D9 repeats it). A `requests.HTTPError` renders as `404 Client Error: Not Found for url: <the full URL>`, query credentials included, and a `ConnectionError` as `… Max retries exceeded with url: <path and query> …`. Sites that interpolate an exception (`{e}`, `str(e)`, `, e)`) or attach a traceback (`exc_info=True`, `logger.exception`), counted at the seed with:

```bash
grep -rnE "logger\.\w+\(.*(\{e\}|\{str\(e\)\}|\{exc\}|\{err\}|\{error\}|str\(e\)|, e\)|, exc\)|, err\))" <dir> --include='*.py' | grep -v /tests/ | wc -l
grep -rnE "logger\.exception\(|exc_info=True" <dir> --include='*.py' | grep -v /tests/ | wc -l
```

| Directory | exception text | traceback |
|---|---|---|
| `apps/proxy` | 63 | 13 |
| `core` | 59 | 5 |
| `apps/epg` | 48 | 24 |
| `apps/channels` | 44 | 3 |
| `apps/vod` | 18 | 0 |
| `apps/output` | 11 | 2 |
| `apps/m3u` | 5 | 1 |
| `apps/plugins` | 4 | 18 |
| `apps/connect` | 0 | 1 |

The example to keep in mind is `apps/epg/tasks.py:853`, `logger.error(f"HTTP Error fetching XMLTV from {source.name}: {e}", exc_info=True)`: the operator's name, then the provider URL with its query credentials twice (in the message and in the traceback's last line). The same shape is at `:902`, `:931` and `:943`. A central scrubber covers this class without touching the call; a per-site "IDs only" edit would not have, because the leak is not in a name.

### 3.3 What each carries, by shape

| Shape | Example (fake) | Masked by the scrubber? |
|---|---|---|
| Absolute URL with userinfo | `http://user:pass@example.invalid/get.php` | yes: `http://***@example.invalid/get.php` |
| Absolute URL with a sensitive query key | `…/xmltv.php?username=user&password=pass` | yes: values become `***` |
| Xtream path, absolute or scheme-less | `example.invalid/live/user/pass/1.ts` | yes: `…/live/***/***/1.ts` |
| XC root route, path starting `/` | `/user/pass/1234.ts` | yes: `/***/***/1234.ts` |
| Scheme-less query string | `get.php?username=user&password=pass` | yes |
| Bare `key=value` token | `password=pass` | yes (one of the four keys) |
| Opaque token in a non-Xtream path | `https://cdn.example.invalid/tok/abc123/index.m3u8` | **no** (§ 7) |
| Non-standard key | `?user=user&pass=pass` | **no** (§ 7, Q4) |
| Scheme-less userinfo | `user:pass@example.invalid` | **no** (§ 7) |
| Name with no carrier | `A&E / HD`, `24/7 News` | untouched |

## 4. Design

### 4.1 Where it sits, and why a record factory (D1)

Three candidates:

- **A `logging.Filter` on every handler**, configured in `LOGGING`. A handler filter sees every record that handler emits, including propagated ones (a logger-level filter does not). But it is configuration, so its coverage is only as good as the list: a handler added later (by a library, by `logging.basicConfig`, by a plugin, by Daphne's CLI before `django.setup()`) is unscrubbed until someone notices. With the two handlers `LOGGING` has today (`console`, and `otel` added by `augment_logging`, `dispatcharr/observability/logs.py:141-163`), each record would be scrubbed twice, and a mutating filter on the first handler changes what the second sees, so the filter would need a marker attribute — which `OtelBridgeHandler._structured_copy` (`dispatcharr/observability/logs.py:114-138`) then has to strip.
- **A helper at call sites.** That is the per-site edit R15 ruled out, and it misses the exception class (§ 3.2).
- **A chained `LogRecordFactory`** (`logging.setLogRecordFactory`). `Logger.makeRecord` calls it for every record that passed the logger's level check, before any filter or handler, whatever the handler list is or later becomes. It runs exactly once per record. The custom TRACE level (`core/apps.py:6-16`) logs through `self._log`, which calls `makeRecord`, so it is covered too. Nothing else in the tree sets a factory (`grep -rn "setLogRecordFactory\|getLogRecordFactory"` is empty at the seed), and the observability work deliberately does not use `LoggingInstrumentor`, which would (observability spec D8).

**Chosen: the record factory.** It is the only placement where "a handler added later is covered" holds by construction rather than by a test that catches the omission. Its costs, stated: it runs for records that no handler then emits (a logger with an enabled level and no handler — none in `LOGGING`), it renders the message one extra time per record, and a record built with `logging.makeLogRecord(dict)` or `logging.LogRecord(...)` directly bypasses it (nothing in the tree logs that way; `dispatcharr/observability/logs.py:20-22` builds one only to read attribute names).

The factory wraps whatever factory was current when it was installed, and calls it first:

```python
def _factory(*args, **kwargs):
    record = _previous(*args, **kwargs)
    _scrub_record(record)      # never raises (§ 4.5)
    return record
_factory.__mino_log_scrubber__ = True
```

### 4.2 What it does to a record (D3)

`_scrub_record(record)`:

1. **Message.** `message = record.getMessage()`. `scrubbed = scrub_text(message)`. If `scrubbed != message`: `record.msg = scrubbed`, `record.args = ()`. Otherwise the record is left exactly as created: template and arguments untouched, so every formatter renders the same bytes it renders today. (`args = ()` rather than `None`: `getMessage` formats only when `args` is truthy, so a scrubbed message containing `%` is never re-formatted.)
2. **Traceback.** If `record.exc_info` holds an exception and `record.exc_text` is empty: `record.exc_text = scrub_tail(formatted)`, where `formatted` is what `logging.Formatter.formatException` produces (`traceback.print_exception` into a buffer, trailing newline stripped). `logging.Formatter.format` uses an existing `exc_text` rather than re-rendering, so the text console prints the scrubbed traceback. `exc_info` itself is kept: the JSON formatter and the OTel bridge render an exception as its type and frame list only (`dispatcharr/observability/logs.py:88-90`, `:131-137`) and need it.
3. **Stack.** If `record.stack_info` is set: `record.stack_info = scrub_tail(record.stack_info)`.
4. Nothing else on the record is read or written. No attribute is added, so no structured field changes and `OtelBridgeHandler`'s copy is unaffected.

Rendering happens inside the logging call, before handlers run, so the text a handler formats is the text that was scrubbed. The one theoretical gap is an argument whose `__str__` is impure (returns different text on the second render) on a record the scrubber left unchanged; no `QueueHandler` or deferred formatting is configured, and `_LoggableText` caches its result (`apps/m3u/tasks.py:89-110`).

### 4.3 What `scrub_text` masks (D2)

Linear in the examined text. Steps:

1. **Cap** (§ 4.4).
2. **Fast path.** If neither `/` nor `=` occurs in the text (two C-level `in` scans), return it unchanged. Every carrier in § 3.3 contains one of them.
3. **Tokenise** with `re.finditer(r"\S+", text)` (one character class with one quantifier: no backtracking). Only tokens containing `/` or `=` are examined. The output is rebuilt from the original separators, and only when at least one token changed; otherwise the original string object is returned.
4. **Per token.** Strip a leading run of `"'(<[{` and a trailing run of `"')>]},;.` (kept aside and restored). In the core:
   - Find every `://` with `str.find` in a loop. For each, walk left over scheme characters (`[A-Za-z0-9+.-]`) but never past the previous `://`'s end, so each character is visited a bounded number of times. Each scheme start opens a URL segment that runs to the next scheme start or the end of the core. Each URL segment goes through `redact_url` unchanged (userinfo, `SENSITIVE_QUERY_KEYS` values in the query and in a query-shaped fragment, Xtream path segments). A redirect-style `…?to=http://user:pass@example.invalid/` is therefore two segments and both are masked.
   - The text before the first scheme start (or the whole core, if it has none) is **scheme-less** and gets: if it contains `?`, `_redact_path` on the part before `?` and `_redact_query` on the part after; otherwise `_redact_path` when it has two or more `/`, and `_redact_query` when it has `=`.
   - `_redact_path` gains one keyword in LS-1, `root_route=True` (default unchanged for `redact_url`). The scrubber passes `root_route=path.startswith("/")`: the bare `/<user>/<pass>/<id>` rule applies to a scheme-less path only when it begins with `/`, which is how a request path for that route always looks. Without this, `2026/11/12` and `3/4/5` would print as `***/***/12`. The prefix-keyed Xtream rule (`live|movie|series|timeshift`, `dispatcharr/utils.py:106`) applies anywhere, so `example.invalid/live/user/pass` is still masked.
5. The mask is `redact_url`'s own `***` (`dispatcharr/utils.py:59`), not observability's `[redacted]` (`dispatcharr/observability/redaction.py:34`): the text sink already prints `***` wherever a call site used `redact_url`, and one mask per sink keeps a reader's grep working.

**What it deliberately leaves.** Hostnames and ports (an operator needs them to tell providers apart, and they are in the account's own configuration — the same reasoning as `relay/redact/redact.go:69-71`). Paths that match no Xtream shape. Channel UUIDs (the observability spec D8 leaves a UUID in a text line out of scope, and this spec does not reopen it). Query keys other than the four. Any text without `/` or `=`.

**Over-masking accepted.** `_redact_path`'s root-route rule, applied to a path starting `/`, masks the first two segments of any three-segment path ending in a number: Django's `Not Found: /api/channels/5/` (from the `django.request` logger) prints `Not Found: /***/***/5/`. This is the trade `redact_url` already documents at `dispatcharr/utils.py:108-114` ("over-masking a log line is the safe direction"); exempting the application's own route prefixes would make the scrubber disagree with `redact_url` about the same string, so it is not done. The test suite pins the example so the cost stays visible.

### 4.4 Bounds (D4)

- **Message cap: 16,384 characters.** A longer rendered message is cut at the last whitespace at or before character 16,384 — never inside a token, because a URL cut before its `@` would no longer parse as userinfo and would leak its first half — and ` [log scrubber: N characters withheld]` is appended. If there is no whitespace before the cap, the whole message is withheld and only the marker remains. The kept prefix is then scrubbed normally. Text past the cap is never emitted.
- **Traceback and stack cap: 65,536 characters, tail kept** (`scrub_tail`). The last line of a traceback is the exception message, which is where the URL is and what an operator needs, so the cut keeps the end: it starts at the first whitespace at or after `len - 65,536`, and `[log scrubber: N characters withheld] ` is prepended.
- **Cost.** One `getMessage()` render per record beyond today's, the two `in` scans, and for a message containing `/` or `=`, one tokenising pass plus a `redact_url` or `_redact_path`/`_redact_query` call per examined token, each linear in the token. All of it is C-level string scanning or bounded Python loops; under gevent it holds the hub for at most the measured worst case of § 12 (1.5 ms at the cap). A level that is off costs nothing: the factory runs only after `isEnabledFor`.

### 4.5 Failure behaviour (D5)

`_scrub_record` never raises and never emits the original:

| Failure | Result |
|---|---|
| `record.getMessage()` raises (bad `%` arguments) | `record.msg = "<log message withheld: formatting failed (<ExceptionType>)>"`, `record.args = ()`. Today `logging` would reach `Handler.handleError`, which prints `Message: <msg>` and `Arguments: <args>` to stderr — the raw arguments. Withholding closes that route. |
| `scrub_text` raises | `record.msg = "<log message withheld: scrubber failed (<ExceptionType>)>"`, `record.args = ()` |
| Rendering or scrubbing the traceback raises | `record.exc_text = "<traceback withheld: scrubber failed (<ExceptionType>)>"`; `exc_info` kept, so the JSON and OTLP sinks still get the type and frames |
| Scrubbing `stack_info` raises | `record.stack_info = "<stack withheld: scrubber failed (<ExceptionType>)>"` |
| Anything else in the factory raises | caught at the outermost level; message withheld as in row 2 |

The type name is the class's `__qualname__` only. The module makes no logging call and imports no module that does at call time (so it cannot re-enter itself); a test pins that by AST.

### 4.6 Installation (D6)

- **`dispatcharr/__init__.py`**, as its first statement, before `from .celery import app` (`:7`): `from .log_scrub import install as _install_log_scrub; _install_log_scrub()`. The relative import keeps `dispatcharr/__init__.py`'s product-name count unchanged.
- Every Python process imports the package before it logs anything of ours: uWSGI loads `dispatcharr.gevent_patch` (`docker/uwsgi.ini:54`) and `dispatcharr.wsgi`; Celery is started as `celery -A dispatcharr` (`docker/supervisord.d/celery-*.conf`); Daphne loads `dispatcharr.asgi:application` (`docker/supervisord.d/daphne.conf`); `manage.py` imports `dispatcharr.settings`; the test runner's `dispatcharr.settings_test` star-imports `dispatcharr.settings` (`dispatcharr/settings_test.py:22`), so tests run with the scrubber on, as production does. The factory is a module global, so Celery's prefork children and uWSGI's workers inherit it across fork.
- `install()` is idempotent: if the current factory carries `__mino_log_scrubber__`, it returns.
- `ensure_installed()` is `install()` plus one WARNING when it had to re-wrap ("the log record factory was replaced; the log scrubber has been re-installed around it"). It is called at the end of `PluginManager.discover_plugins` (`apps/plugins/loader.py:65`), the one function behind all eight discovery call sites (`apps/plugins/apps.py:42`, `:60`, `apps/plugins/api_views.py:129`–`:579`, `apps/plugins/loader.py:546`, and Celery's `worker_process_init`, `dispatcharr/celery.py:57`). Plugins are trusted, unsandboxed, in-process code (CLAUDE.md § Events and plugins); this re-check is a courtesy for a plugin that installs its own factory without chaining, not a boundary.
- **The module is a stdlib-only leaf** (`dispatcharr/log_scrub.py`, importing only `logging`, `re`, `traceback`, `io` and `dispatcharr.url_redaction`). It is imported before Django settings exist, so it cannot import `dispatcharr.utils` (which imports `django.http` and `core.models`, `dispatcharr/utils.py:8-11`) or `dispatcharr.observability.redaction` (which imports the OTel SDK, `:25-30`). That is why LS-1 moves the URL primitives first.

### 4.7 Processes and logging configuration, checked

| Process | How logging is configured | Covered |
|---|---|---|
| uWSGI API and relay | `LOGGING` (`dispatcharr/settings.py:573-649`), `console` + `otel` | yes |
| Celery `default`, `dvr`, beat | `worker_hijack_root_logger=False` (`dispatcharr/celery.py:133`), so `LOGGING`'s `celery*` loggers format; `SuppressFilter` (`:248-261`) matches substrings with `in`, which a rewritten `msg` still satisfies; `print()` inside a task is redirected to the `celery.redirected` logger and becomes a record | yes |
| Daphne | `asgi.py` calls `django.setup()` (`dispatcharr/asgi.py:16`), which applies `LOGGING`; any handler Daphne's CLI added before that is still behind the factory | yes |
| `manage.py`, tests | `LOGGING` via `settings_test`'s star import; `LOGGING` is identical to production's | yes |
| TRACE (level 5) | `core/apps.py:10-16`, via `Logger._log` → `makeRecord` | yes |
| `print()` outside Celery tasks | `dispatcharr/settings.py:561-568`, `dispatcharr/gevent_patch.py`, `dispatcharr/celery.py`'s memory prints | **no** (§ 7) |
| uWSGI request log, nginx, supervisord, Postgres, Redis | not Python `logging` | **no** (§ 7, § 8) |

## 5. Already-redacted output passes through

`scrub_text` is a fixed point on its own output and on `redact_url`'s:

- `***` is not a credential shape: `_redact_path`'s prefix-keyed rule skips a segment already equal to `***` (`dispatcharr/utils.py:149`) and its root-route rule rewrites `/***/***/<id>` to the same bytes, `_redact_query` rewrites `password=***` to the same bytes, and `_redact_netloc` maps `***@host` to `***@host`.
- So `scrub_text(redact_url(u)) == redact_url(u)` and `scrub_text(scrub_text(x)) == scrub_text(x)`. Both are property tests (§ 9, T5).
- A line like `Fetching from URL http://***@example.invalid/live/***/***/1.ts` (the shape `apps/m3u/tasks.py:312` prints) is byte-identical after the scrubber. So are a documentation link (`https://docs.example.invalid/guide`), the relay base URL (`http://127.0.0.1:5658`) and a credential-free deep path; T5 pins each.

Because an unchanged message leaves the record untouched (§ 4.2), these lines keep their template and arguments too.

## 6. Relationship to existing redaction

### 6.1 `redact_url` and friends: reused, moved

`redact_url`, `_redact_netloc`, `_redact_path`, `_redact_query` and their constants (`dispatcharr/utils.py:59-221`) are exactly the carriers R15 asks for, and reusing them means the scrubber and every call-site `redact_url` agree about any string. They cannot be imported where the scrubber must run (§ 4.6), so **LS-1 moves them**, byte for byte apart from the `root_route` keyword, to a stdlib-only `dispatcharr/url_redaction.py`, and `dispatcharr/utils.py` re-exports every moved name (`from dispatcharr.url_redaction import REDACTED, SENSITIVE_QUERY_KEYS, …, redact_url`). Importers (`dispatcharr/urls.py`'s `XC_STREAM_ID_PATTERN`, every `from dispatcharr.utils import redact_url`) are unchanged. `redact_headers` stays in `dispatcharr/utils.py`: the scrubber does not need it.

Where `redact_url` does not fit, the scrubber does not stretch it: it does not mask an opaque token in a non-Xtream path (`/tok/<opaque>/index.m3u8`), and it does not recognise keys outside `SENSITIVE_QUERY_KEYS` (`dispatcharr/utils.py:63`). Both are residuals (§ 7); Q4 asks whether to widen the key set, which would widen `redact_url` everywhere.

### 6.2 `redact_text`: not reused; two patterns made linear

`redact_text` (`dispatcharr/observability/redaction.py:163-173`) is the D9 best-effort body scrubber for the JSON formatter (`dispatcharr/observability/logs.py:79`) and the OTLP log exporter (`dispatcharr/observability/redaction.py:359-370`). It does not fit the text sink for two reasons:

1. **Too broad for text.** It replaces every absolute URL, every scheme-less `/…` path, every UUID, every 32-hex run and every `*password*`/`*token*`/`*auth*`-named value. The observability spec promised `MINO_LOG_FORMAT=text` byte-identical (D8), and channel UUIDs and request paths are what an operator reads a text log for.
2. **Super-linear.** Measured at the seed on CPython 3.13 (§ 12): `_URL_RE` (`:151`) is quadratic on a long run of scheme characters (`"a" * 32000` takes 821 ms), and `_KEY_VALUE_RE` (`:156-159`) is quadratic with a large constant (`"a." * 16000` takes 18.3 s; `"auth" * 8000` 2.2 s). `JsonFormatter.format` runs it inline in the logging call, on the gevent hub, whenever `MINO_LOG_FORMAT=json`; the OTLP exporter runs it on the batch processor's thread, which under early monkey-patching is a greenlet on the same hub. A provider-controlled string of that shape in a logged name stalls every request on that worker for seconds. That is a pre-existing defect in merged work; it is in this spec because the scrubber's cost bound means nothing if the next stage in the same pipeline is quadratic.

**LS-2** rewrites both patterns to linear equivalents with **identical matches**:

- `_URL_RE` → `(?<![A-Za-z0-9+.\-])[A-Za-z][A-Za-z0-9+.\-]*://[^\s"'<>]+`. The lookbehind lets a match start only at the beginning of a run of scheme characters, which is where the old pattern's leftmost match started anyway, so every match is the same and each run is tried once.
- `_KEY_VALUE_RE` → `(?<![\w.-])([\w.-]++)(\s*+[=:]\s*+)("[^"]*+"|'[^']*+'|[^\s,;&]++)` with the keyword test moved into the replacement function (`any(k in group1.lower() for k in …)`; a non-matching key returns the match unchanged). The key group is always the maximal `[\w.-]` run in both versions (neither `=` nor `:` is in that class), so the replaced spans are the same; possessive quantifiers (Python ≥ 3.11; the project requires ≥ 3.13, `pyproject.toml:6`) remove the backtracking. Measured: 0.78 ms on 64,000 characters of each adversarial shape.

The existing policy tests (`tests/test_observability_redaction.py`) must stay green unchanged; LS-2 adds the linearity tests (T8). The scrubber also bounds what reaches `redact_text`: a message is at most 16,384 characters plus the marker once LS-3 lands.

**Order in the pipeline** after LS-3, for one record:

```
logger.info(...) ─► makeRecord ─► [log scrubber: msg/args, exc_text, stack_info]
   ─► logger filters ─► handlers:
        console ─► text formatter (scrubbed text, byte-identical when unchanged)
                └► or JsonFormatter ─► redact_text(getMessage()) (D9, unchanged)
        otel    ─► OtelBridgeHandler._structured_copy ─► LoggingHandler
                ─► BatchLogRecordProcessor ─► RedactingLogExporter: redact_text(body), field allowlist (D9, unchanged)
```

The scrubber runs once, upstream of all three sinks. `redact_text` still runs on the JSON and OTLP bodies: the two layers do different jobs (credential carriers in every sink; D9's broader best-effort classes in the new sinks), and `redact_text` applied to scrubbed text only removes more. Structured fields are untouched: the scrubber adds and changes no attribute other than `msg`, `args`, `exc_text` and `stack_info`, and the bridge already discards `exc_text` and `stack_info` (`dispatcharr/observability/logs.py:132-134`).

### 6.3 `_loggable_name` stays (D8)

`_loggable_name`/`_LoggableText` (`apps/m3u/tasks.py:61-110`) **withhold** a whole name when it is URL-shaped: over 512 characters, `://`, `?` then `=`, or a token with two or more `/`. That is stronger than the scrubber, which masks only known carriers and would let `https://cdn.example.invalid/tok/abc123/x.m3u8` through. It is also lazy, so a per-stream TRACE line on a disabled level costs nothing, and it sits on the hottest log path in the tree (one call per stream in a refresh). It stays, unchanged and unmoved. It is not generalised either: making "withhold if URL-shaped" the scrubber's rule would withhold every intentionally logged `redact_url` output, which § 5 requires to pass through. The scrubber is the floor under every line; `_loggable_name` stays the stricter rule on the lines #642 chose.

### 6.4 Go is out of scope (D9)

Confirmed from the tree: the relay redacts every ffmpeg stderr line structurally, `relay/redact/redact.go:72` (`Line`, which keeps only scheme and host of any URL), every error argument to a formatting or logging call is linted by `relay/internal/credlint`, and its JSON and OTLP sinks sit behind `SafeHandler` and the redacting exporters (observability spec D8, D9). The relay links no Django code and logs no provider-supplied name through Python. Nothing in this spec touches `relay/`.

## 7. Residual leak routes after this spec

Stated plainly; none of these is closed here.

1. **Opaque credentials in a non-Xtream URL path** (`https://cdn.example.invalid/tok/<opaque>/index.m3u8`), and any provider whose credential path prefix is not `live|movie|series|timeshift`.
2. **Non-standard query keys** (`user=`, `pass=`, `u=`, `p=`, `key=`, `auth=`, `sig=`): only `password`, `username`, `token` and `api_key` are masked (Q4).
3. **Scheme-less userinfo** (`user:pass@example.invalid/…`), a credential split across whitespace, a bare password, or an encoded one.
4. **A `print()` outside a Celery task** (`dispatcharr/settings.py:561-568`, `dispatcharr/gevent_patch.py`, `dispatcharr/celery.py`'s memory prints): none prints provider text today.
5. **The uWSGI request log** prints `%(uri)` for every request (`docker/uwsgi.ini:69`, `docker/uwsgi.relay.ini:77`, `disable-logging = false`). The Xtream VOD and catch-up roots it serves (`/movie/<user>/<pass>/…`, `/series/…`, `/timeshift/…`, `/streaming/timeshift.php?username=…&password=…`) therefore print **Dispatcharr users'** Xtream credentials. **nginx** has no `access_log` directive in `docker/nginx.conf`, so it writes its compiled-in default access log with the full request line, live routes included. Neither passes through Python `logging`. This is not provider text and is a separate leak; follow-up F2.
6. **Plugin code** can replace the factory between discovery runs, or log by its own means; plugins are trusted code.
7. **Text past the caps** is withheld rather than leaked, which is a loss of log content, not a leak.
8. **A record built without the factory** (`logging.makeLogRecord(dict)`, a direct `logging.LogRecord(...)`), which nothing in the tree does today.
9. **Persisted and client-visible text** (§ 8).

## 8. Out of scope: persisted and client-visible text (follow-up F1)

Not covered, by default and on purpose: the scrubber is a log-record mechanism, and the surfaces below are database columns and WebSocket payloads, which have their own audiences (the admin UI) and their own fix (build the message from `redact_url(account.server_url)`). Evidence at the seed:

- `apps/m3u/tasks.py:356-368` builds `error_msg` with the raw `account.server_url` (Xtream accounts carry the login in it), `:375` stores it in `M3UAccount.last_message`, and `:377-383` sends it to every admin over the WebSocket with `send_m3u_update(..., error=error_msg)`. The same shape repeats at `:447`, `:528`–`:555`, `:603`–`:651`, each stored and sent at `:453`–`:728`. Several are also logged (`:668`, `:700`, `:726`) — those log lines **are** scrubbed by this spec; the stored and sent copies are not.
- `apps/epg/tasks.py:1542` and `:2445` store `str(e)` in `EPGSource.last_message`; `:832` and `:1544` send it over the WebSocket. A `requests` exception there carries the URL (§ 3.2).
- `SystemEvent` rows written by `log_system_event()` (`core/utils.py`) are persisted text with the same exposure in principle; none is known to carry a provider URL today.

**F1** (new issue, filed by LS-3's PR): build those persisted and sent messages from `redact_url(...)`/`redact_exception(...)` at the four builders. **F2** (new issue, filed by LS-3's PR): the uWSGI and nginx request logs (§ 7 item 5). Neither is in this spec's PRs.

## 9. Tests and break-checks

All new Python tests live in top-level `tests/` (label `tests`) unless stated, register the tree's byte-identical `dispatcharr-ci` Hypothesis profile where they use `@given` (as `tests/test_redaction.py:29-32` does), and are `SimpleTestCase`. Every break-check is applied, the test is run red with the stated message, and the edit is reverted; the PR body records each.

| # | Test | What it proves | Named wrong edit | Must redden with |
|---|---|---|---|---|
| T1 | `tests/test_log_scrub_install.py`, one cold child per entry module (`dispatcharr.wsgi`, `dispatcharr.asgi`, `dispatcharr.celery`, `dispatcharr.settings`), using `tests/otel_rig.py`'s `child_env`/`run_child` (`:200`, `:217`) | After a cold import of the entry module, `logging.getLogRecordFactory()` carries `__mino_log_scrubber__`, and a record logged through a **freshly added bare `StreamHandler` on a fresh logger** comes out with `http://user:pass@example.invalid/` masked | delete the `_install_log_scrub()` line from `dispatcharr/__init__.py` | "scrubber not installed after importing dispatcharr.<module>" |
| T2 | same file, in-process | A handler added after setup, with no configuration, gets scrubbed text; so does a record propagated to the root logger and one at TRACE (level 5) | move the scrubbing into a `logging.Filter` attached to `LOGGING`'s `console` handler and drop the factory | the fresh-handler assertion, naming the unmasked sentinel |
| T3 | same file | `ensure_installed()` re-wraps a foreign factory, logs exactly one WARNING, the foreign factory still runs, and a second call is silent; `discover_plugins` calls it | make `install()` return early whenever any non-default factory is set | "foreign factory not wrapped" |
| T4 | `tests/test_log_scrub.py` property tests | No sentinel user or password survives `scrub_text` in any carrier of § 3.3's masked rows (userinfo; each of the four keys, any case; each Xtream prefix with and without a host and sub-path; the root route with a leading `/`; scheme-less query; bare `key=value`; inside wrapper punctuation; a URL nested in another's query), embedded in surrounding text drawn from an alphabet disjoint from the sentinel's | remove the `_redact_query` call on scheme-less tokens | Hypothesis' falsifying example containing `username=` and the sentinel |
| T5 | same file | Pass-through: `scrub_text(redact_url(u)) == redact_url(u)` and `scrub_text(scrub_text(x)) == scrub_text(x)` (properties); fixed examples byte-identical: `http://***@example.invalid/live/***/***/1.ts`, `https://docs.example.invalid/guide`, `http://127.0.0.1:5658`, `A&E / HD`, `24/7 News`, `2026/11/12`; an unchanged record keeps its original `msg` object and `args`; the accepted over-mask `Not Found: /api/channels/5/` → `Not Found: /***/***/5/` | reduce each URL segment to `scheme://host/…` (the Go behaviour) instead of calling `redact_url` | the `http://***@example.invalid/live/***/***/1.ts` equality, showing the shortened output |
| T6 | same file | Bounds: for each adversarial input of exactly 16,384 characters (`"a" * 16383 + "/"`, `"/" * n`, `"a/" * n`, `"a://" * n`, `"a=&" * n`, `"a." * n + "="`, `"x://u:p@h/live/a/b/1?username=x& " * n`) `scrub_text` returns in under 50 ms (the measured worst case is 1.5 ms, § 12); for a 1,048,576-character input the output is at most 16,384 characters plus the marker; a cut never splits a token (a URL straddling the cap is absent from the output, not half-present) | remove the cap (scan the whole message) | the output-length assertion, naming the length |
| T7 | same file | Failure: with `scrub_text` patched to raise, a log call does not raise, the record is emitted with the placeholder naming the exception type, and the sentinel is absent from the output; `logger.info("%d", "<sentinel>")` emits the "formatting failed" placeholder and writes nothing containing the sentinel to stderr (`logging.raiseExceptions` left `True`); a `logger.exception` whose exception message carries `http://example.invalid/xmltv.php?username=<sentinel>` prints a traceback with `username=***`; a traceback over 65,536 characters keeps its last line | on a scrubber exception, fall back to the unscrubbed `getMessage()`; separately, skip pre-setting `exc_text` | the sentinel in the captured output |
| T8 | `tests/test_observability_redaction.py` (LS-2, added, not edited) | `redact_text` on `"a" * 32000`, `"a." * 16000` and `"auth" * 8000` returns in under 50 ms; a fixed corpus (every existing policy example plus the adversarial shapes at short lengths) gives byte-identical output under the old and new patterns, the old ones kept in the test module as the oracle | restore the original `_KEY_VALUE_RE` | the `"a." * 16000` timing assertion |
| T9 | `tests/test_log_scrub_sinks.py` (cold child with OTLP logs on, as `tests/test_observability_logs.py` does; plus an in-process `MINO_LOG_FORMAT=json` formatter case) | A body `get.php?username=<sentinel>&x=1` — a shape `redact_text` does **not** remove (no leading `/`, and `username` is not in `_KEY_VALUE_RE`'s keywords) — reaches neither the OTLP export nor the JSON line; the exported structured fields are unchanged from the observability tests' expectation | delete the `_install_log_scrub()` line | the sentinel in the exported body |
| T10 | `tests/test_url_redaction_leaf.py` (LS-1) | `dispatcharr/url_redaction.py` and `dispatcharr/log_scrub.py` import only the standard library and each other (AST walk); every moved name in `dispatcharr.utils` **is** the object in `dispatcharr.url_redaction`; `dispatcharr/log_scrub.py` contains no logging call | add `from django.http import JsonResponse` to `dispatcharr/url_redaction.py` | "non-stdlib import: django.http" |

`tests/test_redaction.py` (the existing `redact_url` property suite) must pass unchanged across LS-1; that is the evidence the move changed nothing.

T6's and T8's 50 ms bound is deliberately loose (more than 30 times the measured linear cost) so that CI load cannot redden it, while the quadratic versions take seconds at those lengths (§ 12), so a regression cannot pass it.

**Existing tests that may change.** The test process runs with the scrubber on (§ 4.6). A test whose captured log text contains a carrier would see it masked. A grep at the seed for log-capturing test files asserting a URL, `username=`, `password=` or `/live/` in captured output finds none:

```bash
grep -rlE "assertLogs|caplog|_CapturingHandler|addHandler" --include='*.py' apps core tests dispatcharr \
  | xargs grep -lE "assertIn\(['\"][^'\"]*(://|username=|password=|/live/)"
```

LS-3's implementer runs all fifteen backend labels fresh and lists, with before and after, any test that changed; per the test-modification rule a test changes only if the behaviour it pins is the masking itself.

## 10. PR breakdown

Each PR is small enough for one `sonnet` implementer. Every one touches `dispatcharr/`, which is in `_SHARED_PATH_PREFIXES` (`dispatcharr/test_discovery.py:10-18`), so CI and the commit gate run **all** backend labels for each.

### LS-1 — URL-redaction primitives move to a leaf module

- **Files:** `dispatcharr/url_redaction.py` (new: `REDACTED`, `SENSITIVE_QUERY_KEYS`, `XTREAM_PATH_PREFIXES`, `XC_STREAM_ID_PATTERN`, `_XC_STREAM_ID_RE`, `_redact_netloc`, `_redact_path` with the new `root_route=True` keyword, `_redact_query`, `redact_url`, moved from `dispatcharr/utils.py:59-63`, `:102-221`); `dispatcharr/utils.py` (the definitions replaced by one re-export import; `SENSITIVE_HEADERS`, `URL_VALUED_META_KEYS` and `redact_headers` stay); `tests/test_url_redaction_leaf.py` (new, T10 minus the `log_scrub` half); `scripts/product_name_allowlist.txt` (regenerated with `python3 scripts/check_product_name.py --write`: the moved comment naming `dispatcharr/urls.py` moves one count from `dispatcharr/utils.py` to the new file, and the new test file's `dispatcharr.` imports add an entry).
- **Gates:** product-name ratchet (above). Credential-logging checker: the moved code contains no logging call, and the checker matches `redact_url` by name (`scripts/check_credential_logging.py:141-145`), so call sites stay clear. Gate 2: none of its nine modules (`scripts/coverage_live_path.coveragerc`) changes.
- **Done when:** `tests/test_redaction.py` passes unchanged; T10 passes; all labels green.

### LS-2 — `redact_text` made linear

- **Files:** `dispatcharr/observability/redaction.py` (`_URL_RE`, `_KEY_VALUE_RE` and the `_KEY_VALUE_RE` substitution in `redact_text`, per § 6.2); `tests/test_observability_redaction.py` (T8 added; no existing test edited).
- **Independent of LS-1 and LS-3**; may land first. Its PR files and references the issue for the defect (Q3).
- **Gates:** credential-logging checker unaffected. Product-name: no count change expected.

### LS-3 — the scrubber

- **Files:** `dispatcharr/log_scrub.py` (new: `scrub_text`, `scrub_tail`, `_scrub_record`, `install`, `ensure_installed`, the caps as module constants); `dispatcharr/__init__.py` (install first, relative import); `apps/plugins/loader.py` (`ensure_installed()` at the end of `discover_plugins`, imported inside the function); `tests/test_log_scrub.py`, `tests/test_log_scrub_install.py`, `tests/test_log_scrub_sinks.py` (new, T1–T7, T9, and T10's `log_scrub` half); `scripts/product_name_allowlist.txt` (`--write`, for the new test files); `docs/observability.md` (one short section: what the scrubber masks in every sink, what it leaves, the caps, that it is best effort and not a proof); CLAUDE.md § Known defects and traps → Security (one bullet: the scrubber exists, the residuals of § 7, and the two follow-ups by issue number).
- **Depends on LS-1.** Files F1 and F2 as issues (`gh issue create --repo D10Scot/Dispatcharr`, label `needs-triage`) and names them in the PR body with "Refs #N".
- **Gates:** product-name ratchet (new test files; `dispatcharr/__init__.py` unchanged in count because the import is relative). Credential-logging checker: `dispatcharr/log_scrub.py` has no log call; the `ensure_installed` WARNING in it is the one exception, a fixed literal with no argument, which the checker clears. Gate 2 untouched. The `PostToolUse` hook runs the `tests` package on every edit of a new test file, against whichever tree `dispatcharr-testrunner` is mounted on (CLAUDE.md § Test hooks); re-point it first.
- **Concurrent work:** `credcheck-impl` is widening `scripts/check_credential_logging.py` in `.worktrees/credcheck`. The files are disjoint and neither design depends on the other: the checker stays the call-site lint, and the scrubber is the floor behind it. Whichever lands second rebases and re-runs the checker over its own new files.

## 11. Open questions for the owner

Only the ones that change the design; each has a recommended default that the spec already assumes.

- **Q1. Mask carriers, or reduce every URL to its host?** The Go relay keeps only scheme and host (`relay/redact/redact.go:72`), which also catches opaque path tokens (§ 7 item 1). Doing that here would rewrite every URL a call site already passed through `redact_url`, losing the path operators read today and breaking § 5's pass-through. **Default: mask `redact_url`'s carriers only (D2).**
- **Q2. Caps of 16,384 characters per message and 65,536 per traceback, fixed in code.** Some refresh lines interpolate whole lists of names (`apps/vod/tasks.py:380`) and would be truncated. **Default: yes, fixed, not an environment variable** — a cap an operator can raise is a cap a misconfiguration can remove.
- **Q3. Fix `redact_text`'s super-linear patterns in this programme (LS-2), or file them separately?** It is merged code from the observability work and only bites with `MINO_LOG_FORMAT=json` or OTLP logs on, both opt-in. **Default: LS-2 in this programme, with its own issue**, because a provider-controlled name of the measured shape stalls the hub for seconds on the very path this spec bounds.
- **Q4. Widen `SENSITIVE_QUERY_KEYS` to common non-Xtream credential keys (`user`, `pass`, `passwd`, `pwd`, `key`, `auth`)?** It changes `redact_url` for every call site and every sink, and `key`/`auth` would mask harmless parameters. **Default: no, not here**; a separate issue if a provider shape is seen.

## 12. Measurements

Taken in the session scratchpad on the seed's code, `python3 -I` (CPython 3.13, macOS, arm64), single run each; enough to separate linear from quadratic, not a benchmark.

**`redact_text` patterns at the seed** (`re.sub` over the whole input):

| Input | `_URL_RE` | `_KEY_VALUE_RE` |
|---|---|---|
| `"a" * 8000` / `"a." * 4000` / `"auth" * 2000` | 51.7 ms | 1,109 ms / 139.5 ms |
| `"a" * 16000` / `"a." * 8000` / `"auth" * 4000` | 198.6 ms | 4,467 ms / 563.7 ms |
| `"a" * 32000` / `"a." * 16000` / `"auth" * 8000` | 821.3 ms | 18,289 ms / 2,249 ms |

Each doubling roughly quadruples the time. `_UUID_ANYWHERE_RE`, `_HLS_TOKEN_RE`, `_LONG_HEX_RE` and `_PATH_RE` stayed under 0.5 ms at 32,000 characters on their own adversarial shapes.

**LS-2's replacements:** the lookbehind `_URL_RE` took 0.3 ms on `"a" * 32000`; the possessive key-value pattern 0.78 ms on `"a." * 32000`, 0.91 ms on `"auth" * 16000`, 0.29 ms on `"a=" * 32000` and 1.08 ms on 64,000 `"`, and gave `x password=[redacted] y my_token: [redacted] user=bob` on the sample line.

**A prototype of § 4.3** (tokeniser, scheme walk, `redact_url`/`_redact_path`/`_redact_query` copied from `dispatcharr/utils.py`) at the 16,384-character cap: `"/" * n` 0.33 ms, `"a/" * n` 0.52 ms, `"a://" * n` 1.49 ms, `"a=&" * n` 0.89 ms, a mixed carrier line 0.95 ms; inputs 64 times the cap were bounded by the cut. It produced:

```
Fetching http://user:pass@example.invalid/get.php?username=user&password=pass&type=m3u
  -> Fetching http://***@example.invalid/get.php?username=***&password=***&type=m3u
404 Client Error: Not Found for url: http://example.invalid/xmltv.php?username=user&password=pass
  -> 404 Client Error: Not Found for url: http://example.invalid/xmltv.php?username=***&password=***
Max retries exceeded with url: /live/user/pass/1.ts?token=abc (Caused by X)
  -> Max retries exceeded with url: /live/***/***/1.ts?token=*** (Caused by X)
Account 'provider.example.invalid/live/user/pass' refreshed
  -> Account 'provider.example.invalid/live/***/***' refreshed
group (http://user:pass@h.invalid/x)        -> group (http://***@h.invalid/x)
get.php?username=user&password=pass         -> get.php?username=***&password=***
Fetching from URL http://***@example.invalid/live/***/***/1.ts   (unchanged)
A&E / HD, 24/7 News, see https://docs.example.invalid/guide      (unchanged)
```

and `scrub(scrub(x)) == scrub(x)` held for every line. The prototype applied the root-route rule to scheme-less tokens without the leading-`/` condition; § 4.3's `root_route` keyword is the correction for the date false positive it showed.
