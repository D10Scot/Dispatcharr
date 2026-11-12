# Central log scrubber for provider-supplied text

- **Status:** draft for internal review, round 2 (§ 14 lists what changed after round 1).
- **Seed SHA:** `1302b665` (`origin/main`, after #642). Every `file:line` below was read at that SHA; line numbers drift.
- **Authority:** the owner's ruling **R15** (2026-11-12): handle provider-supplied text in log lines with a **central log scrubber**, not by editing each call site to log IDs only. CLAUDE.md (§ Architecture, § Known defects and traps → Security, § Test hooks), the observability spec `docs/superpowers/specs/2026-10-31-observability-design.md` (D8, D9, ruling R-Q17), and the two merged leak fixes it follows: #636 (`0c142c15`, M3U profile search/replace patterns) and #642 (`1302b665`, URLs, record dumps, headers and exception text on the M3U refresh path).
- **Execution:** implement this spec PR by PR with subagents, per CLAUDE.md § Delegation for phase work (`implement-review-escalate`, `pr-merge-gate`). Security-adjacent: reviews run on `fable` from round one.
- **Scope line:** log hygiene. Not a logging rewrite, not structured logging, not a change to what any call site logs.

## 1. Summary

1. One function, `scrub_text`, masks credential carriers in free text, token by token, by handing each whitespace-delimited token to `redact_url`'s own component parsing: URL userinfo, the values of `username`/`password`/`token`/`api_key` in a query or a query-shaped fragment, Xtream path credentials (`/live|movie|series|timeshift/<user>/<pass>`), the bare `/<user>/<pass>/<id>` root route when the token starts with `/`, and a bare `password=…`-style token. It masks what `redact_url` masks and nothing else.
2. It runs **once per log record, at record creation**, from a chained `logging.setLogRecordFactory` installed by `dispatcharr/__init__.py` before anything else in the package. Every Python process here (uWSGI API and relay, Celery workers and beat, Daphne, `manage.py`) imports that package first, and a record factory runs whatever handler later emits the record.
3. It rewrites `record.msg`/`record.args` only when the rendered message changed; an untouched record keeps its template and arguments, so the text format stays byte-identical for every line that carries no carrier.
4. It also scrubs the record's text caches: a pre-existing `exc_text`, a traceback it renders itself from `exc_info`, and `stack_info`. This matters because a `requests` exception message carries the full request URL with its query credentials (`apps/epg/tasks.py:853`).
5. Every scan is linear, and the scan examines at most 16,320 characters of a message and 65,472 of a traceback (whose tail is kept). Text past the limit is withheld, never emitted unexamined. What is bounded is the scan of retained text. Rendering the full message and traceback is already done by every formatter today, and is not bounded by this spec.
6. If scrubbing fails, the record is still emitted. Every text field (message, `exc_text`, `stack_info`) is set to a fixed placeholder naming only the exception type. The scrubber adds no new way for a logging call to raise. A message whose `%` formatting fails is withheld the same way, which also closes `logging`'s own "--- Logging error ---" dump of the raw arguments to stderr.
7. The JSON formatter and the OTLP exporter keep their D9 `redact_text` pass; the scrubber runs upstream of both and touches no structured attribute. `redact_text` itself has **three** super-linear patterns (measured: 18 s on an 18-character-alphabet line of 32,000 characters). That is a live hub stall when JSON or OTLP logging is on. LS-2 replaces them with linear scanners whose output is identical to the regular expressions', which a differential property test holds them to.
8. `_loggable_name` stays where it is: it withholds, which is stronger than masking. The Go relay is out of scope (`relay/redact.Line` already scrubs structurally). Persisted and client-visible text (`M3UAccount.last_message`, `EPGSource.last_message`, WebSocket error payloads) is out of scope and named as follow-up F1 with evidence.
9. Three PRs: LS-1 moves the URL-redaction primitives into a stdlib-only leaf module (needed because `dispatcharr/utils.py` imports `core.models`); LS-2 makes `redact_text` linear; LS-3 adds the scrubber, its installation, the Celery filter's level guard, and the tests. It also keeps the stronger call-site tests from going hollow.
10. What it cannot catch is listed in § 7. Notably:
    - opaque path tokens in non-Xtream URLs
    - credentials under non-standard parameter names
    - scheme-less `user:pass@host`
    - bare secrets
    - handlers that serialise exception objects or extra attributes themselves
    - plugin code that replaces the factory
    - every line that never passes through Python `logging`. The uWSGI and nginx request logs carry Dispatcharr users' Xtream credentials today.

## 2. Decisions

| # | Decision | Section |
|---|---|---|
| D1 | The scrubber is a chained `LogRecordFactory`, not a `logging.Filter` on handlers and not a call-site helper | § 4.1 |
| D2 | Per token, it reuses `redact_url`'s component parsing (scheme-less tokens included); it does not reduce a URL to its host the way `relay/redact.Line` does | § 4.3, Q1 |
| D3 | It rewrites a record only when the rendered text changed; its own output is a fixed point | § 4.2, § 5 |
| D4 | Fixed caps with a reserved margin for the marker, not configurable; overflow is withheld with a count | § 4.4, Q2 |
| D5 | On its own failure it sanitises every text field and emits the record; it adds no raise path | § 4.5 |
| D6 | Installed in `dispatcharr/__init__.py`; re-asserted in a `finally` around `PluginManager.discover_plugins`, re-wrapping a factory a plugin replaced | § 4.6 |
| D7 | `redact_text`'s three super-linear patterns are replaced by linear scanners with identical output, held to the old regexes by a differential property test (LS-2) | § 6.2, Q3 |
| D8 | `_loggable_name`/`_LoggableText` stay in `apps/m3u/tasks.py` unchanged | § 6.3 |
| D9 | Go is out of scope; persisted/client-visible text and the request logs are follow-ups | § 6.4, § 8 |
| D10 | Celery's `SuppressFilter` suppresses only records at INFO or below, so a rewritten message can no longer turn an error into a suppressed one | § 4.7 |
| D11 | Tests whose policy is stronger than the scrubber capture records with the scrubber bypassed, so they cannot go hollow | § 9.2 |

## 3. Inventory

### 3.1 Method and count

"About 35" was an estimate from #642's review. Re-counted at the seed with a deliberately broad single-line grep. The counts are approximate and the classes overlap: multi-line calls are missed, and one line can match two patterns. They size the problem; they are not a complete inventory of provider text.

```bash
cd <worktree> && grep -rnE "logger\.(trace|debug|info|warning|warn|error|exception|critical|log)\(" apps core dispatcharr --include='*.py' \
  | grep -v "/tests/\|/migrations/" \
  | grep -E "\b(account|m3u_account|acc|profile|epg_source|source|epg|channel|group|channel_group|stream|category|cat|movie|series|episode|vod|program|programme|obj|instance|user|plugin|logo|recording|rule|event)\.(name|title|channel_name|category_name|tvg_name|tvg_id|display_name)\b|group_title|category_name|\bgroup_name\b|\bstream_name\b|\bchannel_name\b|\btvg_name\b|\btvg_id\b|\bprogram_title\b|\['name'\]|\[\"name\"\]|get\(['\"]name|\bname\}|%s.*\bname\b"
```

It returns **139** lines. The four in `apps/backups/tasks.py` (`:28`, `:30`, `:41`, `:89`) log local backup filenames and carry no provider text, which leaves **135** name-bearing sites:

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

The count is concentrated where #642 said (`apps/m3u/`, `apps/epg/`, `apps/vod/`, the VOD proxy), but it is about four times the estimate. That is itself the argument for R15: a per-site edit would touch at least 135 lines in 16 files, and every future log call.

### 3.2 The larger class: exception text

Names are the class R15 named. The class that actually carries credentials today is **exception text**, which the call-site checker is documented as blind to (`scripts/check_credential_logging.py`'s header; the observability spec D9 repeats it). A `requests.HTTPError` renders as `404 Client Error: Not Found for url: <the full URL>`, query credentials included. A `ConnectionError` renders as `… Max retries exceeded with url: <path and query> …`. The table counts sites that interpolate an exception (`{e}`, `str(e)`, `, e)`) or attach a traceback (`exc_info=True`, `logger.exception`). These are syntactic, overlapping counts, made at the seed with:

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
| **total** | **252** | **67** |

The example to keep in mind is `apps/epg/tasks.py:853`, `logger.error(f"HTTP Error fetching XMLTV from {source.name}: {e}", exc_info=True)`. It logs the operator's source name, then the provider URL with its query credentials twice: once in the message and once in the traceback's last line. The same shape is at `:902`, `:931` and `:943`. A central scrubber covers this class without touching the call. A per-site "IDs only" edit would not have, because the leak is not in a name.

### 3.3 What each carries, by shape

| Shape | Example (fake) | Masked? |
|---|---|---|
| Absolute URL with userinfo | `http://user:pass@example.invalid/get.php` | yes: `http://***@example.invalid/get.php` |
| Absolute URL with a sensitive query key | `…/xmltv.php?username=user&password=pass` | yes: values become `***` |
| Sensitive key in a query-shaped fragment, absolute or relative | `/play.html#username=user` | yes |
| Xtream path, absolute or scheme-less, with or without a fragment | `example.invalid/live/user/pass/1.ts#t` | yes: `…/live/***/***/1.ts#t` |
| XC root route, token starting `/`, with or without a fragment | `/user/pass/1234.ts#t` | yes: `/***/***/1234.ts#t` |
| Scheme-less query string | `get.php?username=user&password=pass` | yes |
| Bare `key=value` token, any value, punctuation included | `password=pass`, `password=)))` | yes: `password=***` |
| URL nested in another URL's parameter | `…?to=http://user:pass@example.invalid/` | yes (each scheme starts its own segment) |
| Opaque token in a non-Xtream path | `https://cdn.example.invalid/tok/abc123/index.m3u8` | **no** (§ 7) |
| Non-standard key | `?user=user&pass=pass` | **no** (§ 7, Q4) |
| Key nested in another key's value | `x=token=pass` | **no** (§ 7) |
| Scheme-less userinfo | `user:pass@example.invalid` | **no** (§ 7) |
| Name with no carrier | `A&E / HD`, `24/7 News`, `2026/11/12` | untouched |

## 4. Design

### 4.1 Where it sits, and why a record factory (D1)

There are three candidates.

- **A `logging.Filter` on every handler**, configured in `LOGGING`. A handler filter sees every record that handler emits, including propagated ones (a logger-level filter does not). But it is configuration, so its coverage is only as good as the list. A handler added later (by a library, by `logging.basicConfig`, by a plugin, by Daphne's CLI before `django.setup()`) stays unscrubbed until someone notices. With the two handlers `LOGGING` has today (`console`, and the `otel` handler that `augment_logging` adds, `dispatcharr/observability/logs.py:141-163`), each record would be scrubbed twice. A mutating filter would also need a marker attribute, which `OtelBridgeHandler._structured_copy` (`dispatcharr/observability/logs.py:114-138`) then has to strip.
- **A helper at call sites.** That is the per-site edit R15 ruled out, and it misses the exception class (§ 3.2).
- **A chained `LogRecordFactory`** (`logging.setLogRecordFactory`). `Logger.makeRecord` calls it for every record that passed the logger's level check, before any filter or handler runs. It runs exactly once per record, however many handlers there are. The custom TRACE level (`core/apps.py:6-16`) logs through `self._log`, which calls `makeRecord`, so it is covered too. Nothing else in the tree sets a factory (`grep -rn "setLogRecordFactory\|getLogRecordFactory"` is empty at the seed). The observability work deliberately does not use `LoggingInstrumentor`, which would set one (observability spec D8).

**Chosen: the record factory.** It is the only placement where a handler added later receives scrubbed message text without being configured for it. Its costs:

- It runs for records that no handler then emits. No logger in `LOGGING` has an enabled level and no handler.
- It renders the message one extra time per record.
- `logging.makeLogRecord(d)` calls the factory with empty fields and then overwrites the record's attributes from `d`, so whatever `d` carries is not scrubbed. A record constructed with `logging.LogRecord(...)` directly never reaches the factory at all. Nothing in the tree logs either way: `dispatcharr/observability/logs.py:20-22` builds one record only to read attribute names.

**What "every handler" means, narrowly.** The scrubber sanitises the record's **text**: `msg`/`args` when they rendered a carrier, `exc_text` and `stack_info`. It does not change `exc_info` (the exception object itself), arguments of a message it left unchanged, or attributes passed with `extra=` or added later. A handler that formats those objects itself, for example by serialising `exc_info[1]` or by dumping the record's `__dict__`, is not protected. The two non-text sinks in the tree today already avoid this: the JSON formatter and the OTel bridge render an exception as its type and frame list only (`dispatcharr/observability/logs.py:88-90`, `:131-137`) and drop every extra attribute (`:128-130`).

The factory wraps whatever factory was current when it was installed, and calls it first:

```python
def _factory(*args, **kwargs):
    record = _previous(*args, **kwargs)   # a raise here propagates, as it does today without the scrubber
    _scrub_record(record)                 # never raises (§ 4.5)
    return record
_factory.__mino_log_scrubber__ = True
```

### 4.2 What it does to a record (D3)

`_scrub_record(record)`:

1. **Message.** `message = record.getMessage()`, then `scrubbed = scrub_text(message)`. If `scrubbed != message`: set `record.msg = scrubbed` and `record.args = ()`. Otherwise the record is left exactly as it was created: template and arguments untouched, so every formatter renders the same bytes it renders today. `args` is set to `()` rather than `None` because `getMessage` formats only when `args` is truthy, so a scrubbed message containing `%` is never re-formatted.
2. **Traceback.** If `record.exc_text` is already set (a chained factory set it), it is replaced by `scrub_tail(record.exc_text)`. Otherwise, if `record.exc_info` holds an exception, `record.exc_text = scrub_tail(formatted)`, where `formatted` is what `logging.Formatter.formatException` produces (`traceback.print_exception` into a buffer, trailing newline stripped). `logging.Formatter.format` uses an existing `exc_text` rather than re-rendering, so the text console prints the scrubbed traceback. `exc_info` itself is kept: the JSON formatter and the OTel bridge need it for the type and frame list.
3. **Stack.** If `record.stack_info` is set: `record.stack_info = scrub_tail(record.stack_info)`.
4. Nothing else on the record is read or written. No attribute is added.

Rendering happens inside the logging call, before handlers run, so the text a handler formats is the text that was scrubbed. The one gap is an argument whose `__str__` returns different text on a second render, on a record the scrubber left unchanged. No `QueueHandler` or deferred formatting is configured, and `_LoggableText` caches its result (`apps/m3u/tasks.py:89-110`).

### 4.3 What `scrub_text` masks (D2)

The design is a token-level scanner that hands each candidate token to `redact_url`'s own component parsing (`urlsplit`, then `_redact_netloc`, `_redact_path`, `_redact_query`, and the query-shaped fragment rule, `dispatcharr/utils.py:184-221`), rather than re-deriving those components with its own expressions. Round 1 showed that re-deriving them misses fragments.

1. **Cap** (§ 4.4).
2. **Fast path.** If neither `/` nor `=` occurs in the text, return it unchanged. That is two C-level `in` scans, and every masked shape in § 3.3 contains one of the two characters.
3. **Tokenise** with `re.finditer(r"\S+", text)`: one character class, one quantifier, no backtracking. Only tokens containing `/` or `=` are examined. The output is rebuilt around the original separators, and only when at least one token changed; otherwise the original string object is returned.
4. **Per token.**
   - **Wrappers.** Take off a leading run of `"'(<[{` and a trailing run of `"')>]},;.`. The leading run is always restored: it precedes any key, scheme or path, so it cannot be part of a credential.
   - **Scheme segments.** In the remaining core, find every `://` with `str.find` in a loop. From each one, walk left over scheme characters (`[A-Za-z0-9+.-]`), never past the end of the previous `://`. Then move right to the first ASCII letter, because a scheme starts with a letter: `1https://…` starts its URL at `h`. Each scheme start opens a URL segment that runs to the next scheme start or to the end of the core. Each URL segment goes through `redact_url` unchanged. A redirect such as `…?to=http://user:pass@example.invalid/` is two segments, and both are masked.
   - **Scheme-less segment.** The text before the first scheme start, or the whole core if there is none, goes through `redact_url(segment, root_route=segment.startswith("/"))`. `urlsplit` accepts relative references, so this parses the path, the query and a query-shaped fragment exactly as `redact_url` does for an absolute URL: `/play.html#username=user` and `/user/pass/1.ts#t` are masked. If the segment has neither `?` nor `#` but contains `=`, the result also goes through `_redact_query`, which masks a bare `password=pass` or `username=u&password=p` token.
   - **Trailing wrapper.** The trailing run is restored only when the scrubbed core does **not** end in the mask `***`. When it does, the trailing characters may be the rest of the credential: in `password=)))` the core is `password=`, and the `)))` is the password. They are dropped, absorbed into the mask. Restored punctuation therefore never follows a mask.
5. **The `root_route` keyword.** LS-1 adds it to `_redact_path` and `redact_url`, defaulting to `True`, so `redact_url`'s behaviour is unchanged. The scrubber passes `root_route=segment.startswith("/")`, so the bare `/<user>/<pass>/<id>` rule applies to a scheme-less token only when it begins with `/`. That is how a request path for that route always looks. Without this, `2026/11/12` and `3/4/5` would be logged as `***/***/12`. The prefix-keyed Xtream rule (`live|movie|series|timeshift`, `dispatcharr/utils.py:106`) still applies anywhere in the token, so `example.invalid/live/user/pass` is still masked.
6. The mask is `redact_url`'s own `***` (`dispatcharr/utils.py:59`), not observability's `[redacted]` (`dispatcharr/observability/redaction.py:34`). The text sink already prints `***` wherever a call site used `redact_url`, and one mask per sink keeps a reader's grep working.

**What it deliberately leaves.**

- Hostnames and ports. An operator needs them to tell providers apart, and they are already in the account's own configuration (the same reasoning as `relay/redact/redact.go:69-71`).
- Paths that match no Xtream shape.
- Channel UUIDs. The observability spec D8 leaves a UUID in a text line out of scope, and this spec does not reopen that.
- Query keys other than the four.
- A sensitive key nested in another key's value (`x=token=pass`): `_redact_query` reads the key as `x`.
- Any text containing neither `/` nor `=`.

**Over-masking accepted.** These cases are the trade `redact_url` already documents at `dispatcharr/utils.py:108-114` ("over-masking a log line is the safe direction"). Exempting them would make the scrubber disagree with `redact_url` about the same string, so they are not exempted, and the test suite pins each one so the cost stays visible:

- **The root-route rule** masks the first two segments of any three-segment path that starts with `/` and ends in a number. Django's `Not Found: /api/channels/5/` (from the `django.request` logger) prints as `Not Found: /***/***/5/`.
- **The prefix rule** masks the two segments after any `live`, `movie`, `series` or `timeshift` segment, so the filesystem path `/srv/live/cache/config.json` prints as `/srv/live/***/***` (`dispatcharr/utils.py:146-151` requires neither a stream id nor a URL context after the prefix).
- **A dropped trailing wrapper** after a mask. For example, `(/live/user/pass)` prints as `(/live/***/***`.

### 4.4 Bounds (D4)

- **Message limit.** `MESSAGE_CAP = 16,384` and `MARKER_RESERVE = 64`. A rendered message longer than the cap is cut at the last whitespace at or before character `16,384 − 64`. The cut never falls inside a token: a URL cut before its `@` would no longer parse as userinfo and would leak its first half. ` [log scrubber: N characters withheld]` is then appended. If there is no whitespace before the limit, the whole message is withheld and only the marker remains. The kept prefix is scanned normally. Because the result fits within the cap, a second pass leaves it unchanged (§ 5). Text past the limit is never emitted. Each boundary search (`str.rfind` per whitespace character) examines at most the first 16,320 characters.
- **Traceback and stack limit.** `TAIL_CAP = 65,536`, with the same 64-character reserve. A longer text keeps its **end**: the last line of a traceback is the exception message, which is where the URL is and what an operator needs. The cut starts at the first whitespace at or after `len − (65,536 − 64)`. The forward search examines at most that window, and `[log scrubber: N characters withheld] ` is prepended. If the window holds no whitespace, the whole text is withheld.
- **What is bounded, and what is not.** The bound covers the scan of retained text. The per-record cost the scrubber adds is:
  - one extra `getMessage()` render,
  - the two `in` scans,
  - for a message containing `/` or `=`, one tokenising pass and one `redact_url`/`_redact_query` call per examined token, each linear in the token,
  - for a record with an exception and no `exc_text`, one `traceback` render.

  The full `getMessage()` render and the full traceback render happen before the cut and are not bounded by this spec. Each formatter already does both today, on every record that reaches it. Arbitrary argument `__str__` methods are outside any bound. A level that is off costs nothing, because the factory runs only after `isEnabledFor`. The measurements in § 12 are single runs that show linear scaling; they are not an upper bound.

### 4.5 Failure behaviour (D5)

`_scrub_record` never raises and never emits original text from a step that failed:

| Failure | Result |
|---|---|
| `record.getMessage()` raises (bad `%` arguments) | `record.msg = "<log message withheld: formatting failed (<ExceptionType>)>"`, `record.args = ()`; the traceback and stack steps still run. Today `logging` would reach `Handler.handleError`, which prints `Message: <msg>` and `Arguments: <args>` to stderr, raw arguments included; withholding closes that route. |
| `scrub_text` raises | `record.msg = "<log message withheld: scrubber failed (<ExceptionType>)>"`, `record.args = ()`; the traceback and stack steps still run |
| Rendering or scrubbing the traceback raises (whether the cached or the rendered `exc_text`) | `record.exc_text = "<traceback withheld: scrubber failed (<ExceptionType>)>"`; `exc_info` kept, so the JSON and OTLP sinks still get the type and frames |
| Scrubbing `stack_info` raises | `record.stack_info = "<stack withheld: scrubber failed (<ExceptionType>)>"` |
| Anything else in `_scrub_record` raises | the outermost handler sets **all three** text fields: the message as in row 2; `exc_text` to the row-3 placeholder whenever `exc_info` or `exc_text` is set; `stack_info` to the row-4 placeholder whenever it is set. It does so by plain assignment of constant strings, which cannot itself fail. |
| The wrapped previous factory raises | not caught. This is today's behaviour without the scrubber; the scrubber adds no raise path of its own. The default factory is `logging.LogRecord`. |

The type name is the class's `__qualname__` only. The factory and the scrubbing call graph (`_factory`, `_scrub_record`, `scrub_text`, `scrub_tail` and their helpers) make no logging call, so they cannot re-enter themselves. `ensure_installed()`'s one WARNING (§ 4.6) is emitted only after the wrapper is in place, from outside that call graph, and its message is a constant. T10 pins both facts.

### 4.6 Installation (D6)

- **`dispatcharr/__init__.py`** runs, as its first statement and before `from .celery import app` (`:7`): `from .log_scrub import install as _install_log_scrub; _install_log_scrub()`. The relative import keeps that file's product-name count unchanged.
- **Every Python process imports the package before application code logs**:
  - uWSGI imports `dispatcharr.gevent_patch` (`docker/uwsgi.ini:54`, after `gevent-early-monkey-patch` at `:49`; `docker/uwsgi.relay.ini:57-62`), then `dispatcharr.wsgi`.
  - Celery is started as `celery -A dispatcharr` for both workers and for beat (`docker/supervisord.d/celery-default.conf`, `celery-dvr.conf`, `celery-beat.conf`).
  - Daphne loads `dispatcharr.asgi:application` (`docker/supervisord.d/daphne.conf`).
  - `manage.py` imports `dispatcharr.settings`.
  - The test runner's `dispatcharr.settings_test` star-imports `dispatcharr.settings` (`dispatcharr/settings_test.py:22`), so tests run with the scrubber on, as production does (§ 9.2 says what that means for existing tests).

  Coverage begins at that import. A framework's own records from before it are not covered: uWSGI's C-level log lines, and anything a launcher logs before importing the application.
- **Inheritance.** The factory is a module global, so Celery's prefork children and uWSGI's workers inherit it across `fork`, and the DVR worker's threads share it. That is stated from how `logging` works; it is not tested per lifecycle (§ 9.1, T13 tests the launcher configuration statically).
- **`install()`** is idempotent: if the current factory carries `__mino_log_scrubber__`, it returns.
- **`ensure_installed()`** is `install()` plus one WARNING with a constant message, emitted only when it had to re-wrap: "the log record factory was replaced; the log scrubber has been re-installed around it". It runs from a `finally:` that wraps the **whole body** of `PluginManager.discover_plugins` (`apps/plugins/loader.py:65-112`). That body has three exits: the cached early `return self._registry` at `:79-82`, the normal return from `_discover_plugins_impl` at `:101-109`, and any exception. The existing `try/finally` at `:101-112` covers only the last two. The new outer `try/finally` covers all three, and the existing one stays as it is. `discover_plugins` is the one function behind all eight discovery call sites (`apps/plugins/apps.py:42`, `:60`, `apps/plugins/api_views.py:129`–`:579`, `apps/plugins/loader.py:546`, and Celery's `worker_process_init`, `dispatcharr/celery.py:57`).
- Plugins are trusted, unsandboxed, in-process code (CLAUDE.md § Events and plugins). This re-check is a courtesy for a plugin that installs its own factory without chaining, not a boundary.
- **The module is a stdlib-only leaf.** `dispatcharr/log_scrub.py` imports only `logging`, `re`, `traceback`, `io` and `dispatcharr.url_redaction`. It is imported before Django settings exist, so it cannot import `dispatcharr.utils` (which imports `django.http` and `core.models`, `dispatcharr/utils.py:8-11`) or `dispatcharr.observability.redaction` (which imports the OTel SDK, `:25-30`). That is why LS-1 moves the URL primitives first.

### 4.7 Processes and logging configuration, checked

| Process | How logging is configured | Covered |
|---|---|---|
| uWSGI API and relay | `LOGGING` (`dispatcharr/settings.py:573-649`), `console` + `otel` | yes |
| Celery `default`, `dvr`, beat | `worker_hijack_root_logger=False` (`dispatcharr/celery.py:133`), so `LOGGING`'s `celery*` loggers format the records; a `print()` inside a task is redirected to the `celery.redirected` logger and becomes a record | yes, with D10 below |
| Daphne | `asgi.py` calls `django.setup()` (`dispatcharr/asgi.py:16`), which applies `LOGGING`; any handler Daphne's CLI added before that still receives records through the factory | yes |
| `manage.py`, tests | `LOGGING` via `settings_test`'s star import; identical to production's | yes |
| TRACE (level 5) | `core/apps.py:10-16`, via `Logger._log` → `makeRecord` | yes |
| `print()` outside Celery tasks | `dispatcharr/settings.py:561-568`, `dispatcharr/gevent_patch.py`, `dispatcharr/celery.py`'s memory prints | **no** (§ 7) |
| uWSGI request log, nginx, supervisord, Postgres, Redis | not Python `logging` | **no** (§ 7, § 8) |

**Celery's `SuppressFilter` (D10).** `setup_celery_logging` (`dispatcharr/celery.py:232-275`) puts a logger-level filter on `celery.app.trace`, `celery.beat`, `celery.worker.strategy`, `celery.beat.Scheduler` and `celery.pool`. The filter drops a record whose `record.msg` contains `"succeeded in"`, `"Scheduler: Sending due task"` or `"received"` (or `"Apply"`; see the note below), unless the level is TRACE (`:248-261`). It reads the **template**. Once the scrubber has rewritten `msg` to the rendered text, a substring of an *argument* is tested too. So an ERROR record whose template does not match, but whose rendered exception contains both a carrier and the word `received`, would be newly dropped. Masking or truncation can also remove a substring the template had.

**Fix, in LS-3:** the filter suppresses only records at INFO or below (`record.levelno <= logging.INFO` is added to its condition), so no error or warning can be suppressed, whatever the scrubber did to its text.

Residual difference: an INFO-or-below record on those five loggers can still change its suppression decision when the scrubber rewrote it. Either a matched word sits only in an argument, or truncation removed the matched word.

The noise lines the filter targets are Celery's own success, received, beat-sending and pool-apply lines. The implementer confirms their levels in the installed Celery inside the test container (Celery is not installed in this checkout's environment) and records `file:line` for each in the PR body. If any of them logs above INFO, the implementer stops and raises it rather than widening the guard.

Note for the record, not changed here: the filter class closes over the loop variable `logger_name` (`:239`, `:259`). Every instance sees its final value, `celery.pool`, so the `"Apply"` clause applies on all five loggers. This is pre-existing, outside this spec's scope, and the level guard does not depend on it.

## 5. Fixed points and pass-through

Two properties, each stated on its actual domain:

- **Self-idempotence, for every input:** `scrub_text(scrub_text(x)) == scrub_text(x)`.
  - **Truncation.** A truncated result is at most `16,384 − 64` characters plus a marker of under 64, so it fits within the cap and a second pass does not truncate it. The marker contains neither `/` nor `=`.
  - **Masked output is stable.** `_redact_path`'s prefix rule skips a segment already equal to `***` (`dispatcharr/utils.py:149`). Its root-route rule rewrites `/***/***/<id>` to the same bytes. `_redact_query` rewrites `password=***` to the same bytes. `_redact_netloc` maps `***@host` to `***@host`.
  - **Trailing wrappers.** A dropped wrapper is not re-dropped, because the token now ends in the mask. A restored wrapper is stripped again on the second pass and restored again, because its core is unchanged.
- **`redact_url` pass-through, on a bounded domain:** `scrub_text(redact_url(u)) == redact_url(u)`, for any `u` that meets all of:
  - `redact_url(u)` contains exactly one `://`, so no URL is nested in a parameter;
  - it contains no whitespace;
  - it neither starts with a leading-wrapper character nor ends with a trailing-wrapper character;
  - it fits within the cap.

  On that domain the scrubber's work is `redact_url(redact_url(u))`, which equals `redact_url(u)`. Outside it the property is false by design. For example, `redact_url` leaves `…?to=http://inner.invalid/live/user/pass/1` unchanged (`to` is not a sensitive key), and the scrubber masks it.

So a line such as `Fetching from URL http://***@example.invalid/live/***/***/1.ts` (the shape `apps/m3u/tasks.py:312` prints) is byte-identical after the scrubber. So are a documentation link (`https://docs.example.invalid/guide`), the relay base URL (`http://127.0.0.1:5658`) and a credential-free deep path. Because an unchanged message leaves the record untouched (§ 4.2), these lines also keep their template and arguments.

Both properties held over the scratch prototype's fuzzing (§ 12): 0 counterexamples to idempotence in 400,000 inputs, and 0 to pass-through in 300,000 URLs on its domain. T5 is the authority.

## 6. Relationship to existing redaction

### 6.1 `redact_url` and friends: reused, moved

`redact_url`, `_redact_netloc`, `_redact_path`, `_redact_query` and their constants (`dispatcharr/utils.py:59-221`) are exactly the carriers R15 asks for. Reusing them means the scrubber and every call-site `redact_url` agree about any string. They cannot be imported where the scrubber must run (§ 4.6), so **LS-1 moves them** to a stdlib-only `dispatcharr/url_redaction.py`. The move is byte for byte apart from the `root_route` keyword. `dispatcharr/utils.py` re-exports every moved name (`from dispatcharr.url_redaction import REDACTED, SENSITIVE_QUERY_KEYS, …, redact_url`), so importers are unchanged: `dispatcharr/urls.py`'s `XC_STREAM_ID_PATTERN`, and every `from dispatcharr.utils import redact_url`. `redact_headers` stays in `dispatcharr/utils.py`, because the scrubber does not need it.

Where `redact_url` does not fit, the scrubber does not stretch it. It does not mask an opaque token in a non-Xtream path (`/tok/<opaque>/index.m3u8`), and it does not recognise keys outside `SENSITIVE_QUERY_KEYS` (`dispatcharr/utils.py:63`). Both are residuals (§ 7). Q4 asks whether to widen the key set, which would widen `redact_url` everywhere.

### 6.2 `redact_text`: not reused; three patterns made linear

`redact_text` (`dispatcharr/observability/redaction.py:163-173`) is the D9 best-effort body scrubber for the JSON formatter (`dispatcharr/observability/logs.py:79`) and the OTLP log exporter (`dispatcharr/observability/redaction.py:359-370`). It does not fit the text sink, for two reasons.

**1. It is too broad for text.** It replaces every absolute URL, every scheme-less `/…` path, every UUID, every run of 32 or more hex digits, and every value whose key contains `password`, `token`, `auth` or a similar word. The observability spec promised `MINO_LOG_FORMAT=text` byte-identical (D8), and channel UUIDs and request paths are what an operator reads a text log for.

**2. Three of its six patterns are super-linear.** These are measured at the seed on CPython 3.13 (§ 12):

| Pattern | Adversarial input | Time | Why |
|---|---|---|---|
| `_URL_RE` (`:151`) | `"a" * 32000` | 821 ms | every letter is a start position, and each one scans the rest of the run looking for `://` |
| `_KEY_VALUE_RE` (`:156-159`) | `"a." * 16000` | 18.3 s | — |
| `_KEY_VALUE_RE` | `"auth" * 8000` | 2.2 s | — |
| `_PATH_RE` (`:160`) | `"/(" * 8000` | 738 ms | every `/` after a `(` is an eligible start; its greedy class scans the rest, then backtracks looking for a required character that never appears |

`JsonFormatter.format` runs it inline in the logging call, on the gevent hub, whenever `MINO_LOG_FORMAT=json`. The OTLP exporter runs it on the batch processor's thread, which under early monkey-patching is a greenlet on the same hub. A provider-controlled string of one of those shapes in a logged name stalls every request on that worker for seconds. This is a pre-existing defect in merged work. It is in this spec because the scrubber's bound means little while the next stage of the same pipeline is quadratic.

The scrubber's message limit does not fix this. A 16,320-character line of `"/("` holds no carrier, so it passes through the scrubber unchanged and reaches `redact_text` intact.

**LS-2 replaces the three regex substitutions with linear scanners that produce identical output.** Round 1 showed that a lookbehind and a possessive rewrite of the expressions are *not* identical: `1https://…` was no longer matched, and `x=token=pass` was no longer masked. So LS-2 does not edit the expressions. Each scanner reproduces the old pattern's leftmost-match semantics over one structural unit, uses the regex engine only for single-class or literal steps, and visits each character a bounded number of times. Appendix A holds the code; each scanner was fuzzed against its old expression (§ 12).

- **URL** (`_URL_RE` semantics). For each `://`, found with `str.find` from the end of the previous match, walk left over `[A-Za-z0-9+.-]` (bounded by that end), then move right to the first ASCII letter. That letter is where the old expression's leftmost match starts. If there is no letter, or no `[^\s"'<>]` character follows the `://`, this `://` starts no match and the search resumes one character later. Otherwise the match runs to the next `[\s"'<>]`.
- **Key/value** (`_KEY_VALUE_RE` semantics), one maximal `[\w.-]+` run at a time. A run can start a match only if:
  - its text from its first word character (the `\b` the old pattern needs) contains a keyword,
  - it is followed by `\s*[=:]\s*`,
  - a value follows: a quoted string closed later in the text, or else `[^\s,;&]+`.

  A run that fails any of these cannot start a match at any of its later positions, because each later start sees a subset of the same keyword text and the same separator. So the scanner moves to the next run. This is how `x=token=pass` is handled: the run `x` fails and the run `token` matches. A closing-quote `str.find` can fail at most once per quote character: any later quoted value would itself supply the closing quote for the earlier one.
- **Path** (`_PATH_RE` semantics), one maximal run of path characters (`[^\s"'<>,;)\]]+`) at a time. The match starts at the run's first `/` whose preceding character is not `[\w/:.-]`. It exists only if a `[A-Za-z0-9_%~-]` occurs after that `/` inside the run, and it always ends at the run's end. If the first eligible `/` fails, every later one in the same run fails too.

The other three patterns (UUID, HLS token, long hex) are left as they are. Each is a fixed-width or single-class match measured under 0.5 ms at 32,000 characters. The existing policy tests (`tests/test_observability_redaction.py`) must stay green unchanged, and LS-2 adds T8.

**Order in the pipeline** after LS-3, for one record:

```
logger.info(...) ─► makeRecord ─► [log scrubber: msg/args, exc_text, stack_info]
   ─► logger filters (Celery SuppressFilter, INFO-or-below only after LS-3)
   ─► handlers:
        console ─► text formatter (scrubbed text; byte-identical when unchanged)
                └► or JsonFormatter ─► redact_text(getMessage())          (D9, linear after LS-2)
        otel    ─► OtelBridgeHandler._structured_copy ─► LoggingHandler
                ─► BatchLogRecordProcessor ─► RedactingLogExporter: redact_text(body), field allowlist (D9)
```

The scrubber runs once, upstream of all three sinks. `redact_text` still runs on the JSON and OTLP bodies. The two layers do different jobs: the scrubber removes credential carriers in every sink, and `redact_text` applies D9's broader best-effort classes in the new sinks. Applied to scrubbed text, `redact_text` can only remove more. Structured fields are untouched: the scrubber changes no attribute other than `msg`, `args`, `exc_text` and `stack_info`, and the bridge already discards `exc_text` and `stack_info` (`dispatcharr/observability/logs.py:132-134`).

### 6.3 `_loggable_name` stays (D8)

`_loggable_name`/`_LoggableText` (`apps/m3u/tasks.py:61-110`) **withhold** a whole name when it is URL-shaped: over 512 characters, `://`, `?` then `=`, or a token with two or more `/`. That is stronger than the scrubber, which masks only known carriers and would let `https://cdn.example.invalid/tok/abc123/x.m3u8` through. It is also lazy, so a per-stream TRACE line at a disabled level costs nothing, and it sits on the hottest log path in the tree: one call per stream in a refresh.

It stays, unchanged and unmoved, and it is not generalised either. Making "withhold if URL-shaped" the scrubber's rule would withhold every intentionally logged `redact_url` output, which § 5 requires to pass through. The scrubber is the floor under every line; `_loggable_name` stays the stricter rule on the lines #642 chose. Its own tests keep their strength through D11 (§ 9.2).

### 6.4 Go is out of scope (D9)

Confirmed from the tree:

- The relay redacts every ffmpeg stderr line structurally: `relay/redact/redact.go:72` (`Line`) keeps only the scheme and host of any URL.
- `relay/internal/credlint` lints every error argument to a formatting or logging call.
- The relay's JSON and OTLP sinks sit behind `SafeHandler` and the redacting exporters (observability spec D8, D9).
- The relay links no Django code and logs no provider-supplied name through Python.

Nothing in this spec touches `relay/`.

## 7. Residual leak routes after this spec

Stated plainly; none of these is closed here.

1. **Opaque credentials in a non-Xtream URL path** (`https://cdn.example.invalid/tok/<opaque>/index.m3u8`), and any provider whose credential path prefix is not `live|movie|series|timeshift`.
2. **Non-standard query keys** (`user=`, `pass=`, `u=`, `p=`, `key=`, `auth=`, `sig=`): only `password`, `username`, `token` and `api_key` are masked (Q4). A sensitive key nested in another key's value (`x=token=pass`) is also missed.
3. **Scheme-less userinfo** (`user:pass@example.invalid/…`): `urlsplit` reads `user` as a scheme. Also missed: a credential split across whitespace, a bare password, or an encoded one.
4. **Handlers that format objects themselves**: one that serialises `exc_info`'s exception, the arguments of a message the scrubber left unchanged, an `extra=` attribute, or the record's `__dict__` (§ 4.1). None in the tree does this today.
5. **A `print()` outside a Celery task** (`dispatcharr/settings.py:561-568`, `dispatcharr/gevent_patch.py`, `dispatcharr/celery.py`'s memory prints). None prints provider text today.
6. **The uWSGI request log** prints `%(uri)` for every request (`docker/uwsgi.ini:69`, `docker/uwsgi.relay.ini:77`, `disable-logging = false`). The Xtream VOD and catch-up roots it serves therefore print **Dispatcharr users'** Xtream credentials: `/movie/<user>/<pass>/…`, `/series/…`, `/timeshift/…` and `/streaming/timeshift.php?username=…&password=…`. **nginx** has no `access_log` directive in `docker/nginx.conf`. Its access log is therefore whatever the base image's `nginx.conf` sets (not verified here), which by default records the full request line, live routes included. Neither passes through Python `logging`. This is not provider text and is a separate leak: follow-up F2.
7. **Plugin code** can replace the factory between discovery runs, or log by its own means. Plugins are trusted code.
8. **Records the factory does not protect**: the dictionary contents passed to `logging.makeLogRecord(d)`, which the factory never sees, and a record built with `logging.LogRecord(...)` directly. Nothing in the tree logs either way today.
9. **Text past the limits** is withheld rather than leaked. That is a loss of log content, not a leak.
10. **Persisted and client-visible text** (§ 8).

## 8. Out of scope: persisted and client-visible text (follow-up F1)

These surfaces are not covered, by default and on purpose. The scrubber is a log-record mechanism; these are database columns and WebSocket payloads, with their own audience (the admin UI) and their own fix (build the message without the secret). Evidence at the seed:

- `apps/m3u/tasks.py:356-368` builds `error_msg` from the raw `account.server_url` (Xtream accounts carry the login in it) **and the provider's response body** (`Server message: {response_content}`).
  - `:375` stores it in `M3UAccount.last_message`.
  - `:377-383` sends it to every admin over the WebSocket with `send_m3u_update(..., error=error_msg)`.
  - The same shape repeats at `:447`, `:528`–`:555` (one of them embedding `head_str[:100]` of the body) and `:603`–`:651`, each stored and sent at `:453`–`:728`.
  - Several are also logged (`:668`, `:700`, `:726`). Those log lines **are** scrubbed by this spec; the stored and sent copies are not.
- `apps/epg/tasks.py:1542` and `:2445` store `str(e)` in `EPGSource.last_message`, and `:832`, `:1544` and `:2446-2449` send it over the WebSocket. A `requests` exception there carries the URL (§ 3.2).
- `SystemEvent` rows written by `log_system_event()` (`core/utils.py`) are persisted text with the same exposure in principle. None is known to carry a provider URL today.

**F1** (new issue, filed by LS-3's PR): build those persisted and sent messages without the URL's credentials or the provider's response body, at the builders above. **F2** (new issue, filed by LS-3's PR): the uWSGI and nginx request logs (§ 7 item 6). Neither is in this spec's PRs.

## 9. Tests and break-checks

### 9.1 New tests

All new Python tests live in top-level `tests/` (label `tests`). Where they use `@given`, they register the tree's byte-identical `dispatcharr-ci` Hypothesis profile, as `tests/test_redaction.py:29-32` does. All are `SimpleTestCase`.

Every break-check follows the same procedure: apply the named wrong edit, run the test red with the stated message, and revert. The PR body records each one. Timing bounds are deliberately loose: 50 ms is more than ten times the measured linear cost, while the quadratic versions take hundreds of milliseconds to seconds at the same lengths (§ 12). CI load therefore cannot redden them, and a regression cannot pass them.

| # | Test | What it proves | Named wrong edit | Must redden with |
|---|---|---|---|---|
| T1 | `tests/test_log_scrub_install.py`, a cold child via `tests/otel_rig.py`'s `child_env`/`run_child` (`:200`, `:217`) running only `import dispatcharr` | **Before any Django setup or plugin discovery can run**, `logging.getLogRecordFactory()` carries `__mino_log_scrubber__`, and a record logged through a freshly added bare `StreamHandler` on a fresh logger comes out with `http://user:pass@example.invalid/` masked | delete the `_install_log_scrub()` line from `dispatcharr/__init__.py` | "scrubber not installed by importing the dispatcharr package" |
| T2 | same file, in-process | A handler added after setup, with no configuration, receives scrubbed text. So does a record propagated to the root logger, and a record at TRACE (level 5) | move the scrubbing into a `logging.Filter` attached to `LOGGING`'s `console` handler and drop the factory | the fresh-handler assertion, naming the unmasked sentinel |
| T3 | same file, in-process with a temporary empty plugins directory | `ensure_installed()` re-wraps a foreign factory and logs exactly one WARNING. The foreign factory still runs, and a second call is silent. `discover_plugins` restores the wrapper on each of its three exits: the cached return (`use_cache=True` after a completed discovery), the normal return, and an exception raised from a patched `_discover_plugins_impl` | put `ensure_installed()` after the existing `try/finally` instead of in an outer `finally` | the cached-exit case, "foreign factory not wrapped after cached discovery" |
| T4 | `tests/test_log_scrub.py`, property tests | No sentinel user or password survives `scrub_text` in any carrier of § 3.3's masked rows. The carriers are embedded in surrounding text drawn from an alphabet disjoint from the sentinel's, inside any combination of leading and trailing wrappers: userinfo; each of the four keys, any case; a query-shaped fragment on an absolute and a relative reference; each Xtream prefix with and without a host, sub-path and fragment; the root route with a leading `/`, with and without a fragment; a scheme-less query; a bare `key=value`, including a value made only of trailing-wrapper characters (`password=)))`); a URL nested in another's query | (a) remove the `_redact_query` call on scheme-less tokens; (b) always restore the trailing wrapper | (a) Hypothesis' falsifying example containing `username=`; (b) the `password=)))` example |
| T5 | same file | Idempotence for every input (property, § 5). Pass-through on § 5's bounded domain (property, generated with the URL strategies of `tests/test_redaction.py` and filtered to the domain). Fixed examples byte-identical: `http://***@example.invalid/live/***/***/1.ts`, `https://docs.example.invalid/guide`, `http://127.0.0.1:5658`, `A&E / HD`, `24/7 News`, `2026/11/12`. An unchanged record keeps its original `msg` object and `args`. The accepted over-masks pin their costs: `Not Found: /api/channels/5/` → `Not Found: /***/***/5/`, and `/srv/live/cache/config.json` → `/srv/live/***/***` | reduce each URL segment to `scheme://host/…` (the Go behaviour) instead of calling `redact_url` | the `http://***@example.invalid/live/***/***/1.ts` equality, showing the shortened output |
| T6 | same file | (1) Each adversarial input of exactly 16,384 characters scrubs in under 50 ms: `"a" * 16383 + "/"`, `"/" * n`, `"a/" * n`, `"a://" * n`, `"a=&" * n`, `"password=) " * n`, `"/a/b/1#username=x " * n`, `"x://u:p@h/live/a/b/1?username=x& " * n`. (2) `"word " * 300000`, which holds no carrier and so is not shortened by masking, scrubs to at most 16,384 characters ending in the marker; a second pass returns it unchanged. (3) A carrier straddling the limit is absent from the output, not half-present | remove the cap (scan the whole message) | (2)'s output-length assertion, naming the length |
| T7 | same file | Failure, one case per field, each run with a text handler and with `logging.raiseExceptions` left `True`. (1) `scrub_text` patched to raise: no exception reaches the caller; the record carries the "scrubber failed" placeholder; the sentinel is absent. (2) `logger.info("%d", "<sentinel>")`: the "formatting failed" placeholder, and nothing on stderr contains the sentinel. (3) A previous factory that pre-sets `exc_text` to text containing `username=<sentinel>`: the output shows `username=***`. (4) `logger.exception` whose message carries `http://example.invalid/xmltv.php?username=<sentinel>`: the traceback shows `username=***`. (5) `scrub_tail` patched to raise, with a cached `exc_text` and a `stack_info` both holding the sentinel: both fields are placeholders and the sentinel is absent. (6) The outer fallback: `_scrub_record`'s message step patched to raise a non-`Exception`-handled error after `exc_text` is set: all three fields hold placeholders. (7) A traceback over 65,536 characters whose last line is `ValueError: tail-marker` keeps that line | (a) on a scrubber exception, fall back to the unscrubbed `getMessage()`; (b) skip a pre-set `exc_text`; (c) make the outer fallback replace only `msg` | (a) the sentinel in case 1's output; (b) case 3; (c) case 6 |
| T8 | `tests/test_observability_redaction.py` (LS-2; tests added, none edited) | (1) Differential property: for strings drawn from an alphabet that is dense in the three patterns' trigger characters, `_scrub_urls`, `_scrub_key_values` and `_scrub_paths` each equal the corresponding old `re.sub`, and `redact_text` equals the old composition. The old expressions are kept in the test module as the oracle. (2) Fixed cases: `1https://example.invalid/x` and `x=token=pass`. (3) Each of `"a" * 32000`, `"a." * 16000`, `"auth" * 8000`, `'token="' * 4500` and `"/(" * 16000` goes through `redact_text` in under 50 ms | (a) restore `_PATH_RE.sub`; (b) replace `_scrub_urls` with the round-1 lookbehind expression | (a) the `"/(" * 16000` timing; (b) the differential property on `1https://…` |
| T9 | `tests/test_log_scrub_sinks.py`, in-process | The JSON sink, through `JsonFormatter`, and the OTLP sink, through `OtelBridgeHandler` with `logs.install_inner_handler` given an OTel `LoggingHandler` over a `LoggerProvider` with a `SimpleLogRecordProcessor(RedactingLogExporter(InMemoryLogExporter()))`: a body `get.php?username=<sentinel>&x=1` reaches neither. `redact_text` does **not** remove that shape: it has no leading `/`, and `username` is not among `_KEY_VALUE_RE`'s keywords. The export is asserted non-empty and to hold the record first, and the structured fields match the observability tests' expectation. The test restores the factory and the inner handler in `addCleanup` | swap the active factory for the one the scrubber wrapped, for the duration of the test, then log | the sentinel in the exported body |
| T10 | `tests/test_url_redaction_leaf.py` (the leaf half in LS-1, the rest in LS-3) | (1) `dispatcharr/url_redaction.py` and `dispatcharr/log_scrub.py` import only the standard library and each other (AST walk). (2) Every moved name in `dispatcharr.utils` **is** the object in `dispatcharr.url_redaction`. (3) Within `dispatcharr/log_scrub.py`, no function reachable from `_factory` (computed over the module's AST call graph) contains a logging call. (4) The only logging call in the module is the single constant-message WARNING in `ensure_installed` | (a) add `from django.http import JsonResponse` to `dispatcharr/url_redaction.py`; (b) add a `logger.debug(...)` to `scrub_text` | (a) "non-stdlib import: django.http"; (b) "logging call reachable from _factory: scrub_text" |
| T11 | `tests/test_celery_suppress_filter.py` | Built through `setup_celery_logging()` with the level not TRACE. (1) An ERROR record on `celery.app.trace` whose template is `"Task %s raised: %s"` and whose argument contains `received` and `http://user:pass@example.invalid/` is emitted, with the credential masked. (2) An INFO record with the template `"Task %s succeeded in %ss: %s"` whose return value carries a carrier is still suppressed. (3) An INFO `"Task %s received"` is still suppressed | remove the level guard | case 1, "error record suppressed" |
| T12 | `tests/test_log_scrub_install.py` | Static: each launcher imports the package before application code. `docker/supervisord.d/celery-*.conf` start `celery -A dispatcharr`; `docker/supervisord.d/daphne.conf` names `dispatcharr.asgi`; every `docker/uwsgi*.ini` has `import = dispatcharr.gevent_patch` or a `module`/`wsgi-file` under `dispatcharr` | change a Celery conf to `-A apps` | "launcher does not import the dispatcharr package: celery-default.conf" |

`tests/test_redaction.py` (the existing `redact_url` property suite) must pass unchanged across LS-1. That is the evidence the move changed nothing.

### 9.2 Existing tests whose policy is stronger than the scrubber (D11)

The test process runs with the scrubber on (§ 4.6). So a test that captures records and asserts that a credential-shaped value is absent would pass even if its call site regressed: the factory removes the value before capture. One example is `apps/m3u/tests/test_m3u_filter_url_logging.py:152-159`, `test_failed_stream_exception_text_is_not_logged`. Its call site, `apps/m3u/tasks.py:1587-1593`, logs `type(e).__name__`; changed back to `str(e)`, it would still pass under the scrubber. Such a test still runs green, but it no longer proves the stronger policy it names (the exception text, the pattern, the URL is not logged at all).

LS-3 therefore adds `tests/log_scrub_rig.py` with one context manager, `unscrubbed_logging()`. While it is active, `logging.getLogRecordFactory()` is the factory the scrubber wrapped, and on exit the scrubber is reinstated. A test whose policy is stronger than the scrubber captures inside it, so it again observes the raw call site.

**Which tests.** Every test that captures log records (`assertLogs`, a handler added to a logger, a patched logger) and asserts that a credential-shaped string is absent. At the seed, the files that capture records and assert absence are:

```bash
grep -rlE "assertLogs|caplog|_CapturingHandler|addHandler" --include='*.py' apps core tests dispatcharr | xargs grep -l "assertNotIn"
```

That finds 14 files, plus `apps/m3u/tests/test_m3u_filter_url_logging.py` and `tests/test_m3u_profile_test_logging.py`, which capture through helpers that grep does not see. The implementer reads each one and applies the rig where the absent string is something `scrub_text` would mask. At least these three need it:

- `apps/m3u/tests/test_m3u_filter_url_logging.py`
- `apps/proxy/tests/test_profile_pattern_logging.py` (`:63-66`)
- `tests/test_m3u_profile_test_logging.py`

The implementer lists every file touched in the PR body, with the before and after of each changed capture, per the test-modification rule. The behaviour those tests pin is unchanged; only how they capture changes.

**Break-check:** change `apps/m3u/tasks.py:1592`'s `type(e).__name__` to `str(e)`. With the rig, `test_failed_stream_exception_text_is_not_logged` must redden, naming the leaked secret. The PR body also records that it stayed green with the rig removed, which shows the hollowing the rig prevents.

A test that does not capture inside the rig, and only asserts a carrier is absent, now tests the scrubber as well as its call site. That is acceptable for tests whose policy is exactly "no credential carrier", and it is how T2 and T9 are meant to read.

## 10. PR breakdown

Each PR is small enough for one `sonnet` implementer. Every one touches `dispatcharr/`, which is in `_SHARED_PATH_PREFIXES` (`dispatcharr/test_discovery.py:10-18`), so CI and the commit gate run **all** backend labels for each. Product-name ratchet: regenerate `scripts/product_name_allowlist.txt` with `python3 scripts/check_product_name.py --write` in every PR. It counts the word in production modules, their comments and docstrings, and in tests, so a moved comment or a new `dispatcharr.` import moves a count.

### LS-1: URL-redaction primitives move to a leaf module

- **Files:**
  - `dispatcharr/url_redaction.py` (new): `REDACTED`, `SENSITIVE_QUERY_KEYS`, `XTREAM_PATH_PREFIXES`, `XC_STREAM_ID_PATTERN`, `_XC_STREAM_ID_RE`, `_redact_netloc`, `_redact_path` and `redact_url` (each with the new `root_route=True` keyword), and `_redact_query`, moved from `dispatcharr/utils.py:59-63` and `:102-221`.
  - `dispatcharr/utils.py`: the definitions replaced by one re-export import. `SENSITIVE_HEADERS`, `URL_VALUED_META_KEYS` and `redact_headers` stay.
  - `tests/test_url_redaction_leaf.py` (new; T10 parts 1 and 2).
  - `scripts/product_name_allowlist.txt`.
- **Gates:**
  - Credential-logging checker: the moved code contains no logging call, and the checker matches `redact_url` by name (`scripts/check_credential_logging.py:141-145`), so call sites stay clear.
  - Gate 2: none of its nine modules (`scripts/coverage_live_path.coveragerc`) changes.
- **Done when:** `tests/test_redaction.py` passes unchanged, T10 parts 1 and 2 pass, and all labels are green.

### LS-2: `redact_text` made linear

- **Files:**
  - `dispatcharr/observability/redaction.py`: `_scrub_urls`, `_scrub_key_values` and `_scrub_paths` from Appendix A replace the `_URL_RE`, `_KEY_VALUE_RE` and `_PATH_RE` substitutions in `redact_text`. The three old expressions are deleted from the module and live on only as the test oracle.
  - `tests/test_observability_redaction.py`: T8 added; no existing test edited.
- **Independent of LS-1 and LS-3**; it may land first. Its PR files the issue for the defect and references it (Q3).
- **Gates:** the credential-logging checker is unaffected.

### LS-3: the scrubber

- **Files:**
  - `dispatcharr/log_scrub.py` (new): `scrub_text`, `scrub_tail`, `_scrub_record`, `_factory`, `install` and `ensure_installed`, with the caps as module constants. Appendix B is the verified core of `scrub_text`.
  - `dispatcharr/__init__.py`: install first, through the relative import.
  - `apps/plugins/loader.py`: an outer `try/finally` around `discover_plugins`' whole body, calling `ensure_installed()` (imported inside the function).
  - `dispatcharr/celery.py`: the level guard in `SuppressFilter`.
  - New tests: `tests/test_log_scrub.py`, `tests/test_log_scrub_install.py`, `tests/test_log_scrub_sinks.py`, `tests/test_celery_suppress_filter.py` and `tests/log_scrub_rig.py` (T1–T7, T9, T10 parts 3 and 4, T11, T12).
  - Existing tests: the stronger-policy tests moved to capture inside `unscrubbed_logging()` (§ 9.2), listed in the PR body.
  - `scripts/product_name_allowlist.txt`.
  - `docs/observability.md`: one short section saying what the scrubber masks in every sink, what it leaves, the limits, and that it is best effort, not a proof.
  - CLAUDE.md § Known defects and traps → Security: the bullet that says provider names are "still logged, deliberately for now" is updated to name the scrubber, the residuals of § 7, and the two follow-ups by issue number.
- **Depends on LS-1.** The PR files F1 and F2 as issues (`gh issue create --repo D10Scot/Dispatcharr`, label `needs-triage`) and names them in its body with "Refs #N".
- **Gates:**
  - Product-name ratchet (above).
  - Credential-logging checker: `dispatcharr/log_scrub.py`'s one logging call is a constant-message WARNING with no argument, which the checker clears.
  - Gate 2 is untouched.
  - The `PostToolUse` hook runs the `tests` package on every edit of a new test file, against whichever tree `dispatcharr-testrunner` is mounted on (CLAUDE.md § Test hooks). Re-point it first.
- **Concurrent work:** `credcheck-impl` is widening `scripts/check_credential_logging.py` in `.worktrees/credcheck`. The files are disjoint and neither design depends on the other: the checker stays the call-site lint, and the scrubber is the floor behind it. Whichever lands second rebases and re-runs the checker over its own new files.

## 11. Open questions for the owner

Only the questions that change the design are listed. Each has a recommended default, which the spec already assumes.

- **Q1. Mask carriers, or reduce every URL to its host?** The Go relay keeps only the scheme and host (`relay/redact/redact.go:72`), which also catches opaque path tokens (§ 7 item 1). Doing that here would rewrite every URL a call site already passed through `redact_url`, losing the path operators read today and breaking § 5's pass-through. **Default: mask `redact_url`'s carriers only (D2), and accept its over-masks and residuals as listed.**
- **Q2. Fixed limits of 16,384 characters per message and 65,536 per traceback, in code.** Some refresh lines interpolate whole lists of names (`apps/vod/tasks.py:380`) and would be truncated. The limits bound the scan of retained text, not the total cost of a record (§ 4.4). **Default: yes, fixed, not an environment variable.** A limit an operator can raise is a limit a misconfiguration can remove.
- **Q3. Fix `redact_text`'s three super-linear patterns in this programme (LS-2), or file them separately?** It is merged code from the observability work, and it only bites with `MINO_LOG_FORMAT=json` or OTLP logs on, both opt-in. **Default: LS-2 in this programme, with its own issue.** A provider-controlled name of the measured shapes stalls the hub for seconds, and the scrubber's limit does not prevent it (§ 6.2).
- **Q4. Widen `SENSITIVE_QUERY_KEYS` to common non-Xtream credential keys (`user`, `pass`, `passwd`, `pwd`, `key`, `auth`)?** That changes `redact_url` for every call site and every sink, and `key` and `auth` would mask harmless parameters. **Default: no, not here.** File a separate issue if a provider shape is seen.

## 12. Measurements

Taken in the session scratchpad, against the seed's code, with `python3 -I` (CPython 3.13, macOS, arm64). Each is a single run: enough to separate linear from quadratic, not a benchmark and not an upper bound.

**`redact_text` patterns at the seed** (`re.sub` over the whole input):

| Input length | `_URL_RE` on `"a" * n` | `_KEY_VALUE_RE` on `"a." * n/2` / `"auth" * n/4` | `_PATH_RE` on `"/(" * n/2` |
|---|---|---|---|
| 8,000 | 51.7 ms | 1,109 ms / 139.5 ms | 171 ms |
| 16,000 | 198.6 ms | 4,467 ms / 563.7 ms | 738 ms |
| 32,000 | 821.3 ms | 18,289 ms / 2,249 ms | — |

Each doubling of the input length roughly quadruples the time. On their own adversarial shapes, `_UUID_ANYWHERE_RE`, `_HLS_TOKEN_RE` and `_LONG_HEX_RE` stayed under 0.5 ms at 32,000 characters.

**LS-2's scanners (Appendix A).**

- **Differential:** 1,800,000 comparisons, each scanner against its old expression, on strings of 0 to 30 characters drawn from an alphabet of the patterns' trigger characters (`:/.-_=(")'`, tab, space, `,;&<>]?#%~`, non-ASCII letters, a superscript digit, and the fragments `token`, `AUTH`, `https`, `://`, `PassWord`, `api-key`, `x=`, `1http`). Four seeds, 150,000 strings each. **0 differences.** The round-1 counterexamples now give `1[redacted]` and `x=token=[redacted]`, matching the old expressions.
- **Timing at 64,000 characters:**

  | Scanner | Input | Time |
  |---|---|---|
  | `_scrub_urls` | `"a" * n` | 0.08 ms |
  | `_scrub_key_values` | `"a." * n/2` | 3.47 ms |
  | `_scrub_key_values` | `"auth" * n/4` | 0.27 ms |
  | `_scrub_key_values` | `'token="' * n/7` | 3.82 ms |
  | `_scrub_paths` | `"/(" * n/2` | 0.44 ms |
  | `_scrub_paths` | `" /." * n/3` | 6.23 ms |

**The scrubber core (Appendix B, against a copy of `dispatcharr/utils.py`'s primitives with the `root_route` keyword added).**

- **Leaks:** 200,000 carrier-bearing strings. They were built from the § 3.3 masked shapes, including fragments, `password=)))` and nested URLs, inside random leading and trailing wrappers and filler. **0** sentinel leaks.
- **Idempotence:** 400,000 strings, carrier-bearing and random. **0** counterexamples.
- **Pass-through:** 300,000 generated URLs on § 5's domain. **0** counterexamples.
- **Timing at the 16,384-character cap:**

  | Input | Time |
  |---|---|
  | `"/" * n` | 0.41 ms |
  | `"a/" * n` | 0.55 ms |
  | `"a://" * n` | 1.74 ms |
  | `"a=&" * n` | 0.95 ms |
  | mixed carrier line | 1.18 ms |
  | `"password=) " * n` | 2.68 ms |
  | `"/a/b/1#username=x " * n` | 2.42 ms |

- `"word " * 300000` scrubbed to 16,363 characters ending in ` [log scrubber: 1483681 characters withheld]`, and a second pass left it unchanged.
- Fixed examples:

```
/play.html#username=CANARY                -> /play.html#username=***
/alice/bravo/123.ts#frag                  -> /***/***/123.ts#frag
password=)))                              -> password=***
'/u/p/1.ts',                              -> '/***/***/1.ts',
(/live/u/p)                               -> (/live/***/***
/srv/live/cache/config.json               -> /srv/live/***/***          (accepted over-mask)
2026/11/12                                -> 2026/11/12
Not Found: /api/channels/5/               -> Not Found: /***/***/5/     (accepted over-mask)
https://outer.invalid/?to=http://inner.invalid/live/alice/bravo/1
                                          -> https://outer.invalid/?to=http://inner.invalid/live/***/***/1
get.php?username=u&password=p#a           -> get.php?username=***&password=***#a
http://u:p@h.invalid/x)                   -> http://***@h.invalid/x)
password=pass),                           -> password=***
x=token=y                                 -> x=token=y                  (residual, § 7 item 2)
```

## 13. Appendices

### Appendix A: LS-2's linear scanners (fuzzed; § 12)

```python
REDACTED = "[redacted]"   # already defined in dispatcharr/observability/redaction.py

# _URL_RE's semantics: a match starts at the first ASCII letter of the run of
# scheme characters directly before "://", and runs to the next delimiter.
_SCHEME_CHARS = frozenset("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789+.-")
_LETTERS = frozenset("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ")
_URL_TAIL_RE = re.compile(r"[^\s\"'<>]+")


def _scrub_urls(text):
    out, pos = [], 0
    k = text.find("://")
    while k != -1:
        start = k
        while start > pos and text[start - 1] in _SCHEME_CHARS:
            start -= 1
        while start < k and text[start] not in _LETTERS:
            start += 1
        tail = _URL_TAIL_RE.match(text, k + 3) if start < k else None
        if tail is None:
            k = text.find("://", k + 1)
            continue
        out.append(text[pos:start])
        out.append(REDACTED)
        pos = tail.end()
        k = text.find("://", pos)
    out.append(text[pos:])
    return "".join(out)


# _KEY_VALUE_RE's semantics, one maximal [\w.-] run at a time: a run whose
# text from its first word character contains a keyword, followed by the
# separator and a value, is a match; any other run cannot start one.
_RUN_RE = re.compile(r"[\w.-]+")
_WORD_RE = re.compile(r"\w")
_KEYWORD_RE = re.compile(r"(?i)password|passwd|pwd|secret|token|api[_-]?key|credential|auth")
_SEPARATOR_RE = re.compile(r"\s*[=:]\s*")
_BARE_VALUE_RE = re.compile(r"[^\s,;&]+")


def _scrub_key_values(text):
    out, pos = [], 0
    for run in _RUN_RE.finditer(text):
        a, b = run.span()
        if b <= pos:
            continue
        word = _WORD_RE.search(text, max(a, pos), b)
        if word is None or not _KEYWORD_RE.search(text, word.start(), b):
            continue
        sep = _SEPARATOR_RE.match(text, b)
        if sep is None:
            continue
        v, end = sep.end(), -1
        if v < len(text) and text[v] in "\"'":
            close = text.find(text[v], v + 1)
            if close != -1:
                end = close + 1
        if end == -1:
            bare = _BARE_VALUE_RE.match(text, v)
            if bare is None:
                continue
            end = bare.end()
        out.append(text[pos:v])
        out.append(REDACTED)
        pos = end
    out.append(text[pos:])
    return "".join(out)


# _PATH_RE's semantics, one maximal run of path characters at a time: the
# match starts at the run's first "/" not preceded by [\w/:.-], needs one
# [A-Za-z0-9_%~-] after it, and always ends at the run's end.
_PATH_RUN_RE = re.compile(r"[^\s\"'<>,;)\]]+")
_PATH_NEED_RE = re.compile(r"[A-Za-z0-9_%~-]")
_PATH_BLOCK_RE = re.compile(r"[\w/:.-]")


def _scrub_paths(text):
    out, pos = [], 0
    for run in _PATH_RUN_RE.finditer(text):
        a, b = run.span()
        i = text.find("/", a, b)
        while i > 0 and _PATH_BLOCK_RE.match(text, i - 1):
            i = text.find("/", i + 1, b)
        if i == -1 or not _PATH_NEED_RE.search(text, i + 1, b):
            continue
        out.append(text[pos:i])
        out.append(REDACTED)
        pos = b
    out.append(text[pos:])
    return "".join(out)
```

`redact_text` becomes: `_scrub_urls`, then `_UUID_ANYWHERE_RE.sub`, `_HLS_TOKEN_RE.sub` and `_LONG_HEX_RE.sub` as today, then `_scrub_key_values`, then `_scrub_paths`. That is the same order as at `dispatcharr/observability/redaction.py:167-172`.

### Appendix B: the scrubber core (fuzzed; § 12)

`url_redaction` is LS-1's `dispatcharr/url_redaction.py`. `scrub_tail`, `_scrub_record`, `_factory`, `install` and `ensure_installed` are specified in §§ 4.2–4.6 and are not reproduced here.

```python
MESSAGE_CAP = 16384
MARKER_RESERVE = 64
_MASK = url_redaction.REDACTED
_TOKEN_RE = re.compile(r"\S+")
_LEAD = frozenset("\"'(<[{")
_TRAIL = frozenset("\"')>]},;.")
_SCHEME_CHARS = frozenset("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789+.-")
_LETTERS = frozenset("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ")


def _schemeless(segment):
    out = url_redaction.redact_url(segment, root_route=segment.startswith("/"))
    if "?" not in segment and "#" not in segment and "=" in out:
        out = url_redaction._redact_query(out)
    return out


def _scrub_core(core):
    starts, low = [], 0
    k = core.find("://")
    while k != -1:
        start = k
        while start > low and core[start - 1] in _SCHEME_CHARS:
            start -= 1
        while start < k and core[start] not in _LETTERS:
            start += 1
        if start < k:
            starts.append(start)
        low = k + 3
        k = core.find("://", low)
    if not starts:
        return _schemeless(core)
    parts = [_schemeless(core[: starts[0]]) if starts[0] else ""]
    for a, b in zip(starts, starts[1:] + [len(core)]):
        parts.append(url_redaction.redact_url(core[a:b]))
    return "".join(parts)


def _scrub_token(token):
    i, j = 0, len(token)
    while i < j and token[i] in _LEAD:
        i += 1
    while j > i and token[j - 1] in _TRAIL:
        j -= 1
    core = token[i:j]
    if not core:
        return token
    out = _scrub_core(core)
    if out == core:
        return token
    # Trailing punctuation is kept only when the core does not end in a mask:
    # after a mask it may be the rest of the credential, so it is dropped.
    return token[:i] + out + ("" if out.endswith(_MASK) else token[j:])


def _scan(text):
    if "/" not in text and "=" not in text:
        return text
    out, last = [], 0
    for m in _TOKEN_RE.finditer(text):
        token = m.group()
        if "/" in token or "=" in token:
            scrubbed = _scrub_token(token)
            if scrubbed != token:
                out.append(text[last : m.start()])
                out.append(scrubbed)
                last = m.end()
    if not out:
        return text
    out.append(text[last:])
    return "".join(out)


def scrub_text(text):
    if len(text) <= MESSAGE_CAP:
        return _scan(text)
    limit = MESSAGE_CAP - MARKER_RESERVE
    cut = max(text.rfind(ws, 0, limit + 1) for ws in " \t\n\r\f\v")
    kept = text[:cut] if cut > 0 else ""
    return _scan(kept) + f" [log scrubber: {len(text) - len(kept)} characters withheld]"
```

## 14. Changelog

### Round 1 → round 2 (review pinned at `6a0a233f`)

| # | Finding | Severity | Disposition |
|---|---|---|---|
| 1 | LS-2's lookbehind and possessive rewrites are not match-identical (`1https://…`, `x=token=pass`) | blocking | **Fixed by redesign.** LS-2 no longer edits the expressions. It replaces them with linear scanners that reproduce each pattern's leftmost-match semantics over one structural unit (§ 6.2, Appendix A), held to the old expressions by a differential property test (T8). Both counterexamples now match the old output; 1,800,000 fuzzed comparisons, 0 differences (§ 12). |
| 2 | `_PATH_RE` is also quadratic (`"/(" * n`) and survives the scrubber's limit | blocking | **Fixed.** Confirmed (738 ms at 16,000 characters). LS-2 now covers three patterns; `_scrub_paths` is linear (0.44 ms at 64,000). Added to T8. The text that called the downstream pipeline bounded is withdrawn, and § 6.2 says the limit does not prevent the stall. |
| 3 | Scheme-less tokens miss fragments; trailing punctuation re-appends a punctuation-only credential; `/srv/live/cache/config.json` over-mask undocumented | blocking | **Fixed by redesign.** Scheme-less segments now go through `redact_url(segment, root_route=…)`, whose `urlsplit` handles relative references, so fragments are parsed exactly as for absolute URLs. A trailing wrapper is restored only when the scrubbed core does not end in a mask (§ 4.3). The over-mask is documented and pinned in T5. T4 gains fragment and punctuation-only cases. The prototype: 0 leaks in 200,000 fuzzed carriers (§ 12). |
| 4 | The fixed-point claims are not universal (nested URL in a non-sensitive parameter; the truncation marker) | should-fix | **Fixed.** Pass-through is now stated on a bounded domain (§ 5). Self-idempotence is made genuinely universal by reserving 64 characters for the marker, so a truncated output fits within the cap. Fuzzed: 0 counterexamples in 400,000 (idempotence) and 300,000 (pass-through on its domain). |
| 5 | Failure contract: a pre-existing `exc_text` is skipped; the outer fallback leaves `exc_text`/`stack_info`; `_previous` raising is undefined; the arbitrary-handler guarantee is overstated | should-fix | **Fixed.** A pre-set `exc_text` is scrubbed. The outer fallback sanitises all three fields with constant assignments. A raising previous factory propagates exactly as today, and the claim is narrowed to "adds no raise path" (§ 4.5). The handler guarantee is narrowed to text fields (§ 4.1, § 7 item 4). T7 now has one case per field. |
| 6 | The limits bound scanning, not total record cost; the T6 and T7 fixtures are underspecified | should-fix | **Fixed.** § 4.4 claims a bounded scan of retained text only, names the unbounded renders, and states that the measurements are not an upper bound. Each boundary search is bounded and the no-whitespace tail case is specified. T6's oversized fixture is pinned to a carrier-free `"word " * 300000`; T7's tail line is pinned to `ValueError: tail-marker`. |
| 7 | Rewriting `msg` changes Celery `SuppressFilter` decisions | should-fix | **Fixed with a deliberate policy revision (D10).** The filter suppresses only records at INFO or below, so no warning or error can be newly suppressed. The remaining difference for INFO-or-below records is stated (§ 4.7). `dispatcharr/celery.py` joins LS-3, and T11 pins the policy. The implementer confirms Celery's noise levels in the container, where Celery is installed. |
| 8 | `discover_plugins` exit paths; T1 and T9 isolation; T9 cited a non-existent cold-child example | should-fix | **Fixed.** An outer `try/finally` around the whole `discover_plugins` body covers the cached return at `:79-82`, the normal return and exceptions; T3 tests all three exits. T1's child runs only `import dispatcharr`, so neither Django setup nor plugin discovery can repair a broken install. T9 is now in-process with `InMemoryLogExporter`, and the wrong citation is removed. The per-lifecycle runtime claims are narrowed to inheritance-by-construction plus a static launcher test (T12). |
| 9 | T10 forbids the logging call that `ensure_installed` must make | should-fix | **Fixed.** T10 forbids logging calls reachable from `_factory`, and permits exactly the one constant-message WARNING in `ensure_installed` (§ 4.5). |
| 10 | Existing stronger call-site tests go hollow once the factory scrubs before capture | should-fix | **Fixed (D11).** `tests/log_scrub_rig.py`'s `unscrubbed_logging()` restores the wrapped factory for captures whose policy is stronger than the scrubber. The tests that need it are listed with the rule for finding the rest. Break-check: `apps/m3u/tasks.py:1592` changed to `str(e)` must redden `test_failed_stream_exception_text_is_not_logged` with the rig in place (§ 9.2). |
| — | UNVERIFIED note: `logging.makeLogRecord` invokes the factory and then overwrites the record's fields | — | **Wording fixed** (§ 4.1, § 7 item 8). |
| — | Other checks: the F1 follow-up must cover embedded response bodies; the product-name regeneration covers production files | — | **Adopted** (§ 8, § 10). |
