# Central log scrubber for provider-supplied text

- **Status:** draft for internal review, round 3 (§ 14 lists what changed after rounds 1 and 2).
- **Seed SHA:** `1302b665` (`origin/main`, after #642). Every `file:line` below was read at that SHA; line numbers drift.
- **Authority:** the owner's ruling **R15** (2026-11-12): handle provider-supplied text in log lines with a **central log scrubber**, not by editing each call site to log IDs only. CLAUDE.md (§ Architecture, § Known defects and traps → Security, § Test hooks), the observability spec `docs/superpowers/specs/2026-10-31-observability-design.md` (D8, D9, ruling R-Q17), and the two merged leak fixes it follows: #636 (`0c142c15`, M3U profile search/replace patterns) and #642 (`1302b665`, URLs, record dumps, headers and exception text on the M3U refresh path).
- **Execution:** implement this spec PR by PR with subagents, per CLAUDE.md § Delegation for phase work (`implement-review-escalate`, `pr-merge-gate`). Security-adjacent: reviews run on `fable` from round one.
- **Scope line:** log hygiene. Not a logging rewrite, not structured logging, not a change to what any call site logs.

## 1. Summary

1. One function, `scrub_text`, masks credential carriers in free text with a deliberately blunt rule (§ 4.3). It works per whitespace-delimited token. It masks URL userinfo in place. Once it sees a credential position, it masks from there **to the end of the token**: the value after a `username`/`password`/`token`/`api_key` assignment, the segments after a `live|movie|series|timeshift/` prefix, or the path of a `/<user>/<pass>/<digit…>` root route. It may over-mask. It must never leave a carrier that `redact_url` would mask, and it restores nothing it masked.
2. It runs **at record creation**, from a chained `logging.setLogRecordFactory` installed by `dispatcharr/__init__.py` before anything else in the package. Every Python process here (uWSGI API and relay, Celery workers and beat, Daphne, `manage.py`) imports that package first, and a record factory runs whatever handler later emits the record. It runs at least once per record. A second pass, through a chain a plugin built, changes nothing.
3. It rewrites `record.msg`/`record.args` only when the rendered message changed. An untouched record keeps its template and arguments, so the text format stays byte-identical for every line the rule does not match.
4. It also scrubs the record's text caches: a pre-existing `exc_text`, a traceback it renders itself from `exc_info`, and `stack_info`. This matters because a `requests` exception message carries the full request URL with its query credentials (`apps/epg/tasks.py:853`).
5. Every scan is linear. The scan reads at most 16,384 characters of a message and 65,536 of a traceback, whose tail is kept, and the **output** never exceeds those lengths. Text past the limit is withheld, never emitted unexamined. What is bounded is the scan and the output. Rendering the full message and traceback is already done by every formatter today, and is not bounded by this spec.
6. If scrubbing fails, the record is still emitted. Every text field (message, `exc_text`, `stack_info`) is set to a fixed placeholder naming only the exception type. The scrubber adds no new way for a logging call to raise. A message whose `%` formatting fails is withheld the same way, which also closes `logging`'s own "--- Logging error ---" dump of the raw arguments to stderr.
7. The JSON formatter and the OTLP exporter keep their D9 `redact_text` pass; the scrubber runs upstream of both and touches no structured attribute. `redact_text` itself has **three** super-linear patterns (measured: 18 s on an 18-character-alphabet line of 32,000 characters). That is a live hub stall when JSON or OTLP logging is on. LS-2 replaces them with linear scanners whose output is identical to the regular expressions', which a differential property test holds them to.
8. `_loggable_name` stays where it is: it withholds, which is stronger than masking. The Go relay is out of scope (`relay/redact.Line` already scrubs structurally). Persisted and client-visible text (`M3UAccount.last_message`, `EPGSource.last_message`, WebSocket error payloads) is out of scope and named as follow-up F1 with evidence.
9. Two PRs. LS-2 makes `redact_text` linear. LS-3 adds the scrubber, its installation and the Celery filter's level guard. It moves three constants (the mask and the two key sets) into a stdlib-only leaf module, because `dispatcharr/utils.py` imports `core.models`, and it keeps the stronger call-site tests from going hollow. LS-1 of rounds 1–2 is gone: the scrubber no longer calls `redact_url`.
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
| D2 | A blunt per-token rule: mask userinfo in place, and from the first credential position to the end of the token. Never under-mask a `redact_url` carrier; over-masking is accepted and listed. It does not reduce a URL to its host the way `relay/redact.Line` does | § 4.3, Q1 |
| D3 | It rewrites a record only when the rendered text changed; scrubbing its output again changes nothing | § 4.2, § 5 |
| D4 | Fixed caps on the scan and on the output, not configurable; overflow is withheld with a count | § 4.4, Q2 |
| D5 | On its own failure it sanitises every text field and emits the record; it adds no raise path | § 4.5 |
| D6 | Installed in `dispatcharr/__init__.py`; re-asserted in a `finally` around `PluginManager.discover_plugins`. Each install wraps the then-current factory in a fresh closure with an immutable captured predecessor | § 4.6 |
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

| Shape | Example (fake) | Result |
|---|---|---|
| URL with userinfo, any scheme or none (`//…`) | `http://user:pass@example.invalid/get.php` | `http://***@example.invalid/get.php` |
| Sensitive key in a query, a fragment or a bare assignment, any case, raw or percent-encoded name | `…/xmltv.php?username=user&password=pass` | `…/xmltv.php?username=***` (the rest of the token goes too) |
| Sensitive value that is itself a URL | `…/?username=https://user.invalid/x` | `…/?username=***` |
| Value made of punctuation, or of the mask plus punctuation | `password=)))`, `username=***)))` | `password=***`, `username=***` |
| Key nested in another key's value | `x=token=pass` | `x=token=***` |
| Xtream path, absolute or scheme-less, with or without a fragment | `example.invalid/live/user/pass/1.ts#t` | `example.invalid/live/***` |
| XC root route, as a request path or as a URL's path | `/user/pass/1234.ts#t`, `http://h.invalid/user/pass/1.ts` | `/***`, `http://h.invalid/***` |
| URL nested in a non-sensitive parameter | `…?to=http://user:pass@example.invalid/live/a/b/1` | `…?to=http://***@example.invalid/live/***` |
| Opaque token in a non-Xtream path | `https://cdn.example.invalid/tok/abc123/index.m3u8` | **unchanged** (§ 7) |
| Non-standard key | `?user=user&pass=pass` | **unchanged** (§ 7, Q4) |
| Scheme-less userinfo without `//` | `user:pass@example.invalid` | **unchanged** (§ 7) |
| Name with no rule match | `A&E / HD`, `24/7 News`, `2026/11/12`, `https://docs.example.invalid/guide`, `http://example.invalid/channels/5` | unchanged, same object |

## 4. Design

### 4.1 Where it sits, and why a record factory (D1)

There are three candidates.

- **A `logging.Filter` on every handler**, configured in `LOGGING`. A handler filter sees every record that handler emits, including propagated ones (a logger-level filter does not). But it is configuration, so its coverage is only as good as the list. A handler added later (by a library, by `logging.basicConfig`, by a plugin, by Daphne's CLI before `django.setup()`) stays unscrubbed until someone notices. With the two handlers `LOGGING` has today (`console`, and the `otel` handler that `augment_logging` adds, `dispatcharr/observability/logs.py:141-163`), each record would be scrubbed twice. A mutating filter would also need a marker attribute, which `OtelBridgeHandler._structured_copy` (`dispatcharr/observability/logs.py:114-138`) then has to strip.
- **A helper at call sites.** That is the per-site edit R15 ruled out, and it misses the exception class (§ 3.2).
- **A chained `LogRecordFactory`** (`logging.setLogRecordFactory`). `Logger.makeRecord` calls it for every record that passed the logger's level check, before any filter or handler runs. It runs once per record per installed wrapper, however many handlers there are (§ 4.6 on chains). The custom TRACE level (`core/apps.py:6-16`) logs through `self._log`, which calls `makeRecord`, so it is covered too. Nothing else in the tree sets a factory (`grep -rn "setLogRecordFactory\|getLogRecordFactory"` is empty at the seed). The observability work deliberately does not use `LoggingInstrumentor`, which would set one (observability spec D8).

**Chosen: the record factory.** It is the only placement where a handler added later receives scrubbed message text without being configured for it. Its costs:

- It runs for records that no handler then emits. No logger in `LOGGING` has an enabled level and no handler.
- It renders the message one extra time per record.
- `logging.makeLogRecord(d)` calls the factory with empty fields and then overwrites the record's attributes from `d`, so whatever `d` carries is not scrubbed. A record constructed with `logging.LogRecord(...)` directly never reaches the factory at all. Nothing in the tree logs either way: `dispatcharr/observability/logs.py:20-22` builds one record only to read attribute names.

**What "every handler" means, narrowly.** The scrubber sanitises the record's **text**: `msg`/`args` when they rendered a carrier, `exc_text` and `stack_info`. It does not change `exc_info` (the exception object itself), arguments of a message it left unchanged, or attributes passed with `extra=` or added later. A handler that formats those objects itself, for example by serialising `exc_info[1]` or by dumping the record's `__dict__`, is not protected. The two non-text sinks in the tree today already avoid this: the JSON formatter and the OTel bridge render an exception as its type and frame list only (`dispatcharr/observability/logs.py:88-90`, `:131-137`) and drop every extra attribute (`:128-130`).

Each installation wraps whatever factory is current at that moment in a **fresh closure**. The closure calls that factory first, and the predecessor it captures is immutable:

```python
def install():
    current = logging.getLogRecordFactory()
    if getattr(current, "__mino_log_scrubber__", False):
        return False                              # the scrubber is already outermost: no-op

    def factory(*args, _previous=current, **kwargs):
        record = _previous(*args, **kwargs)       # a raise here propagates, as it does today
        _scrub_record(record)                     # never raises (§ 4.5)
        return record

    factory.__mino_log_scrubber__ = True
    factory.__mino_log_scrubber_previous__ = current   # read only by the test rig (§ 9.2)
    logging.setLogRecordFactory(factory)
    return True
```

`_previous` is bound as a keyword default when the closure is created, so a later installation cannot change it. There is no module-global predecessor.

### 4.2 What it does to a record (D3)

`_scrub_record(record)`:

1. **Message.** `message = record.getMessage()`, then `scrubbed = scrub_text(message)`. If `scrubbed != message`: set `record.msg = scrubbed` and `record.args = ()`. Otherwise the record is left exactly as it was created: template and arguments untouched, so every formatter renders the same bytes it renders today. `args` is set to `()` rather than `None` because `getMessage` formats only when `args` is truthy, so a scrubbed message containing `%` is never re-formatted.
2. **Traceback.** If `record.exc_text` is already set (a chained factory set it), it is replaced by `scrub_tail(record.exc_text)`. Otherwise, if `record.exc_info` holds an exception, `record.exc_text = scrub_tail(formatted)`, where `formatted` is what `logging.Formatter.formatException` produces (`traceback.print_exception` into a buffer, trailing newline stripped). `logging.Formatter.format` uses an existing `exc_text` rather than re-rendering, so the text console prints the scrubbed traceback. `exc_info` itself is kept: the JSON formatter and the OTel bridge need it for the type and frame list.
3. **Stack.** If `record.stack_info` is set: `record.stack_info = scrub_tail(record.stack_info)`.
4. Nothing else on the record is read or written. No attribute is added.

Rendering happens inside the logging call, before handlers run, so the text a handler formats is the text that was scrubbed. The one gap is an argument whose `__str__` returns different text on a second render, on a record the scrubber left unchanged. No `QueueHandler` or deferred formatting is configured, and `_LoggableText` caches its result (`apps/m3u/tasks.py:89-110`).

### 4.3 What `scrub_text` masks (D2)

**Principle.** The scrubber may over-mask. It must never leave a carrier that `redact_url` would mask. It does no reconstruction: no wrapper restoration, no recovery of a nested URL inside a masked value, and no "already masked" shortcut. Rounds 1 and 2 found three generations of edge cases in exactly that surgery (§ 14), so the rule below is chosen for being obviously safe, and every benign shape it hurts is listed rather than saved.

**The rule.** Text containing neither `/` nor `=` is returned unchanged; that is two C-level `in` scans. Otherwise the text is split into whitespace-delimited tokens with `re.finditer(r"\S+", …)`, and each token containing `/` or `=` goes through four steps.

1. **Userinfo.** After every `//` in the token, the *authority* runs to the next `/`, `?` or `#`, or to the end of the token. If it contains `@`, the text from the authority's start up to its last `@` is replaced by `***`. This is `urlsplit`'s netloc boundary and `_redact_netloc`'s `rpartition("@")` (`dispatcharr/utils.py:124-129`), applied to every `//` whether or not a valid scheme precedes it. Host and port survive.
2. **Mask to the end of the token** from the earliest of three positions. All of the token from that position onwards becomes `***`, and there is never more than one such mask per token. The positions are:
   - **key:** the character after an `=` whose *name* contains `username`, `password`, `token` or `api_key`. The name is the text since the previous `&`, `?`, `#`, `=` or `/`, or since the start of the token. The check is case-insensitive, and it is made on both the raw name and the percent-decoded name (`urllib.parse.unquote`). `_redact_query` matches a name that **equals** a key after the same decoding (`dispatcharr/utils.py:166-181`). Containment is a superset of that, so `x_token=…` and `pass%77ord=…` are both masked.
   - **prefix:** the character after `live/`, `movie/`, `series/` or `timeshift/` (case-insensitive) when the word is not preceded by an ASCII letter or digit. `_redact_path`'s prefix rule needs the word as a whole segment with two segments after it (`:146-151`). The scrubber needs one character, and its left boundary is any non-alphanumeric character, not only `/`.
   - **root:** the character after a *path start* that is followed by two non-empty segments and a third segment beginning with a digit (`\d`). Empty segments are skipped, and the path ends at `?`, `#` or the end of the token. A path start is either the first `/` after a `//` authority, or a `/` that is not followed by `/` and is at the start of the token or preceded by a character outside `[A-Za-z0-9._~%/-]`. `_redact_path`'s root rule needs exactly three segments and a stream id matching `\d+(\.[A-Za-z0-9]+)?` in full (`:153-161`). The scrubber needs at least three segments and a leading digit, so a quoted `'/u/p/1.ts',` is caught too. The start condition is what leaves `2026/11/12` and `24/7` alone.

   No position is masked when the token ends at it, for example `password=` at the end of a token: there is no value there to leak.
3. **Union.** A userinfo span that reaches the to-the-end mask merges into it.
4. **Emit.** If nothing was masked, the token is unchanged. If no token changed, the original string object is returned.

This is the whole rule. It masks every `redact_url` carrier in any token, including wrapped tokens and tokens with no scheme: userinfo, any of the four keys in a query, a fragment or a bare assignment, the Xtream prefix and the root route. That was checked by a differential fuzz against `redact_url` as the oracle (§ 12): 2,000,000 tokens, 0 cases where `redact_url` removed the sentinel and the scrubber did not.

**What it deliberately leaves.**
- Hostnames and ports. An operator needs them to tell providers apart, and they are already in the account's configuration (the same reasoning as `relay/redact/redact.go:69-71`).
- Channel UUIDs. Observability spec D8 leaves a UUID in a text line out of scope, and this spec does not reopen that.
- Query keys other than the four, paths that match no Xtream shape, and any text with neither `/` nor `=`.

**The mask** is `***`, the same as `redact_url`'s (`dispatcharr/utils.py:59`), not observability's `[redacted]` (`dispatcharr/observability/redaction.py:34`). The text sink already prints `***` wherever a call site used `redact_url`, and one mask per sink keeps a reader's grep working.

**Linear.** Each step is linear in the token. Authorities contain no `/`, so they are disjoint and each `//` search resumes past the previous authority. The key names are delimited by the separators they end at, so they are disjoint, and `unquote` runs once per name. The prefix rule is one regex search with a fixed-width lookbehind. The root check reads at most three segments from each path start. Starts inside an already-examined run of slashes are skipped, because they read the same segments, so each segment is read by at most three starts. § 12 measures the adversarial shapes; T6 bounds them.

**Over-masking accepted.** The rule hurts these benign shapes, listed so the cost is visible, and T5 pins each one:

| Input | Output | Why |
|---|---|---|
| `http://***@example.invalid/live/***/***/1.ts`, an existing `redact_url` line | `http://***@example.invalid/live/***` | the prefix rule masks to the end of the token, so a call site's `redact_url` output loses its stream id |
| `get.php?username=u&page=2` | `get.php?username=***` | the parameters after a key go with it |
| `Not Found: /api/channels/5/` (Django's `django.request` logger) | `Not Found: /***` | the root shape; `redact_url` already masks two segments of it |
| `https://h.invalid/api/v1/2` | `https://h.invalid/***` | the root shape in a URL path |
| `/srv/live/cache/config.json`, `C:/live/cache/config.json` | `/srv/live/***`, `C:/live/***` | the prefix rule with no URL context; `redact_url` masks these too |
| prose such as `movie/series counts` | `movie/***` | the prefix rule after a non-alphanumeric boundary |
| `csrf_token=abc`, `next_token=…` | `csrf_token=***` | the key rule matches by containment |
| `'password=x',`, `(/live/u/p)` | `'password=***`, `(/live/***` | closing punctuation after a mask is absorbed, never restored |

**Observability's byte-identity promise.** The observability spec promised `MINO_LOG_FORMAT=text` byte-identical (D8). That still holds for every line the rule does not match. Lines it matches change; the first row of the table above is the visible case. Q1 asks the owner to confirm the trade.

### 4.4 Bounds (D4)

`MESSAGE_CAP = 16,384`, `TAIL_CAP = 65,536` and `RESERVE = 64`. One rule, applied before and after the scan:

> Text longer than its cap is cut at whitespace to `cap − 64` characters, and a marker reporting the original length is appended. This happens to the **input** before scanning, so the scan never reads more than the cap, and again to the **output** after scanning, so the output never exceeds the cap.

- **The message cut.** The message keeps its **head**: it is cut at the last whitespace at or before `16,384 − 64`, and ` [log scrubber: truncated from N characters]` is appended. N is the length of the original rendered message.
- **The traceback and stack cut.** These keep their **tail**, because the last line is the exception message, which is where a URL is and what an operator needs. The cut is at the first whitespace at or after `len − (65,536 − 64)`, and `[log scrubber: truncated from N characters]` is prepended.
- **No whitespace.** If no whitespace falls in the window, the whole text is withheld and only the marker remains.
- **Why the cut is at whitespace.** A cut never falls inside a token. A cut inside a token could separate a URL from its `@` and leak the first half of it. The scan is per token, so every token kept is a token that was scrubbed in full.
- **Why the output cut is needed.** Masking can lengthen text, because a one-character value becomes `***`. Round 2's `"username=x " * 1489` is 16,379 characters in and would be 19,357 characters out. The output cut returns it to 16,362.
- **The marker.** It is under 64 characters and contains neither `/` nor `=`. So a cut output fits within the cap, and a second pass neither cuts nor masks it (§ 5).
- **What this bounds, and what it does not.** It bounds the scan and the output. It does not bound the full `getMessage()` render or the full traceback render, which happen before the cut. Every formatter already does both today, on every record that reaches it. Arbitrary argument `__str__` methods are outside any bound. A level that is off costs nothing, because the factory runs only after `isEnabledFor`. The timings in § 12 are single runs showing linear scaling, not an upper bound.

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

The type name is the class's `__qualname__` only. The factory closure and the scrubbing call graph (`_scrub_record`, `scrub_text`, `scrub_tail` and their helpers) make no logging call, so they cannot re-enter themselves. `ensure_installed()`'s one WARNING (§ 4.6) is emitted only after the wrapper is in place, from outside that call graph, and its message is a constant. T10 pins both facts.

### 4.6 Installation (D6)

- **`dispatcharr/__init__.py`** runs, as its first statement and before `from .celery import app` (`:7`): `from .log_scrub import install as _install_log_scrub; _install_log_scrub()`. The relative import keeps that file's product-name count unchanged.
- **Every Python process imports the package before application code logs**:
  - uWSGI imports `dispatcharr.gevent_patch` (`docker/uwsgi.ini:54`, after `gevent-early-monkey-patch` at `:49`; `docker/uwsgi.relay.ini:57-62`), then `dispatcharr.wsgi`.
  - Celery is started as `celery -A dispatcharr` for both workers and for beat (`docker/supervisord.d/celery-default.conf`, `celery-dvr.conf`, `celery-beat.conf`).
  - Daphne loads `dispatcharr.asgi:application` (`docker/supervisord.d/daphne.conf`).
  - `manage.py` imports `dispatcharr.settings`.
  - The test runner's `dispatcharr.settings_test` star-imports `dispatcharr.settings` (`dispatcharr/settings_test.py:22`), so tests run with the scrubber on, as production does (§ 9.2 says what that means for existing tests).

  Coverage begins at that import. A framework's own records from before it are not covered: uWSGI's C-level log lines, and anything a launcher logs before importing the application.
- **Inheritance.** The factory is a module global of `logging`, so Celery's prefork children and uWSGI's workers inherit it across `fork`, and the DVR worker's threads share it. That is stated from how `logging` works and is not tested per lifecycle. T12 tests the launcher configuration statically.
- **`install()`** (§ 4.1) does nothing if the current factory is already a scrubber. Otherwise it wraps the current factory in a fresh closure.
- **Chains, and why "exactly once" is withdrawn.** A plugin's factory `G` may have captured the scrubber `F1` and then replaced it. `ensure_installed()` then builds `F2 → G → F1`, and the record is scrubbed twice. That is harmless: scrubbing is idempotent (§ 5 (d)), and `_scrub_record` on an already-scrubbed record changes nothing. The second pass finds the message unchanged and leaves it alone, and `scrub_tail` maps a scrubbed `exc_text` and `stack_info` to themselves.

  The claim is therefore "**at least once; repeated passes change nothing**", at the cost of one extra pass per chained layer.

  **Recursion is impossible by construction.** Each closure calls only the predecessor it captured when it was created, and that predecessor already existed. Following the calls therefore walks strictly back in creation order and cannot revisit a factory. `F1 → G → F1` would need `F1` to call something created after it.

  The one way to recurse is a foreign factory that looks up `logging.getLogRecordFactory()` at call time and calls the result. That factory recurses into itself with or without the scrubber, so it is a plugin defect, not this design's.
- **`ensure_installed()`** is `install()` plus one WARNING with a constant message, logged only when `install()` returned `True`: "the log record factory was replaced; the log scrubber has been re-installed around it". The new wrapper is in place before the WARNING is logged, so the WARNING's own record is scrubbed and cannot re-trigger the install.

  It runs from a `finally:` that wraps the **whole body** of `PluginManager.discover_plugins` (`apps/plugins/loader.py:65-112`). That body has three exits:
  - the cached early `return self._registry` at `:79-82`,
  - the normal return from `_discover_plugins_impl` at `:101-109`,
  - any exception.

  The existing `try/finally` at `:101-112` covers only the last two. The new outer `try/finally` covers all three, and the existing one stays as it is. `discover_plugins` is the one function behind all eight discovery call sites (`apps/plugins/apps.py:42`, `:60`, `apps/plugins/api_views.py:129`–`:579`, `apps/plugins/loader.py:546`, and Celery's `worker_process_init`, `dispatcharr/celery.py:57`).
- Plugins are trusted, unsandboxed, in-process code (CLAUDE.md § Events and plugins). This re-check is a courtesy for a plugin that installs its own factory, not a boundary.
- **The module is a stdlib-only leaf.** `dispatcharr/log_scrub.py` imports only `logging`, `re`, `traceback`, `io`, `urllib.parse` and `dispatcharr.url_redaction`. It is imported before Django settings exist, so it cannot import:
  - `dispatcharr.utils`, which imports `django.http` and `core.models` (`dispatcharr/utils.py:8-11`);
  - `dispatcharr.observability.redaction`, which imports the OTel SDK (`:25-30`).

  That is why LS-3 moves `REDACTED`, `SENSITIVE_QUERY_KEYS` and `XTREAM_PATH_PREFIXES` into the new leaf module `dispatcharr/url_redaction.py`. `dispatcharr/utils.py` re-exports all three. Nothing else moves, and `redact_url` is unchanged.

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

## 5. Properties

Four properties, each stated on its whole domain, and nothing else is claimed:

| # | Property | T-test |
|---|---|---|
| (a) | **No listed carrier survives.** In any token, a sentinel that `redact_url` would remove is absent from `scrub_text`'s output. `redact_url` is applied to the token and to the token with leading `"'(<[{` and trailing `"')>]},;.` removed, with the root route counted only when the token starts with `/`. | T4 |
| (b) | **Text the rule does not match is returned as the same object.** This is the case when no token contains a userinfo `@` after `//` or one of the three positions. | T5 |
| (c) | **Bounded output.** `len(scrub_text(x)) ≤ 16,384` and `len(scrub_tail(x)) ≤ 65,536`, for every `x`. | T6 |
| (d) | **Scrubbing again changes nothing:** `scrub_text(scrub_text(x)) == scrub_text(x)`, and the same for `scrub_tail`. | T5 |

Property (d) is byte identity, and it falls out of the rule for two reasons. The only character that ever follows a mask is a userinfo `@`. The mask, the marker and that `@` contain no trigger. So a second pass finds the same positions, masks `***` to `***`, and stays under the cap.

The universal "`redact_url` pass-through" claim of rounds 1 and 2 is **withdrawn**. The prefix rule rewrites `…/live/***/***/1.ts` to `…/live/***` (§ 4.3).

All four held over the prototype's fuzzing (§ 12). T4–T6 are the authority.

## 6. Relationship to existing redaction

### 6.1 `redact_url`: the oracle, not the engine

Rounds 1 and 2 had the scrubber call `redact_url` per token. Round 2 showed that reusing it on fragments of a token loses the boundaries of the sensitive components (§ 14, round 2 finding 2). Round 3 therefore makes `redact_url` the scrubber's **oracle** (§ 5 (a), T4) and not its engine.

The scrubber shares only `REDACTED`, `SENSITIVE_QUERY_KEYS` and `XTREAM_PATH_PREFIXES` with it, through the leaf module LS-3 adds. `redact_url` itself is unchanged and does not move. The `root_route` keyword of rounds 1 and 2 is dropped, and so is LS-1.

The scrubber does not stretch beyond `redact_url`'s carriers into new ones. It does not mask an opaque token in a non-Xtream path (`/tok/<opaque>/index.m3u8`), and it does not recognise keys outside `SENSITIVE_QUERY_KEYS` (`dispatcharr/utils.py:63`). Both are residuals (§ 7). Q4 asks whether to widen the key set, which would widen `redact_url` everywhere.

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

The scrubber's message limit does not fix this. A 16,384-character line of `"/("` matches no scrubber rule, so it passes through the scrubber unchanged and reaches `redact_text` intact.

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

It stays, unchanged and unmoved, and it is not generalised either. Making "withhold if URL-shaped" the scrubber's rule would withhold every intentionally logged `redact_url` output, host and path included. The scrubber is the floor under every line; `_loggable_name` stays the stricter rule on the lines #642 chose. Its own tests keep their strength through D11 (§ 9.2).

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
2. **Non-standard query keys** (`user=`, `pass=`, `u=`, `p=`, `key=`, `auth=`, `sig=`). Only names containing `password`, `username`, `token` or `api_key` are masked (Q4). A key written with a separator other than `=` (`password: x`, `password = x`) is also missed.
3. **Scheme-less userinfo with no `//`** (`user:pass@example.invalid/…`). `redact_url` misses it too, because `urlsplit` reads `user` as a scheme. Also missed:
   - a credential split across whitespace;
   - a bare password;
   - a credential encoded beyond one `unquote`.
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

Every break-check follows the same procedure: apply the named wrong edit, run the test red with the stated message, and revert. The PR body records each one. Timing bounds are deliberately loose. Each is roughly ten times the measured linear cost or more, while the quadratic versions take hundreds of milliseconds to seconds at the same lengths (§ 12). CI load therefore should not redden them, and a quadratic regression cannot pass them.

| # | Test | What it proves | Named wrong edit | Must redden with |
|---|---|---|---|---|
| T1 | `tests/test_log_scrub_install.py`, a cold child via `tests/otel_rig.py`'s `child_env`/`run_child` (`:200`, `:217`) running only `import dispatcharr` | **Before any Django setup or plugin discovery can run**, `logging.getLogRecordFactory()` carries `__mino_log_scrubber__`, and a record logged through a freshly added bare `StreamHandler` on a fresh logger comes out with `http://user:pass@example.invalid/` masked | delete the `_install_log_scrub()` line from `dispatcharr/__init__.py` | "scrubber not installed by importing the dispatcharr package" |
| T2 | same file, in-process | A handler added after setup, with no configuration, receives scrubbed text. So does a record propagated to the root logger, and a record at TRACE (level 5) | move the scrubbing into a `logging.Filter` attached to `LOGGING`'s `console` handler and drop the factory | the fresh-handler assertion, naming the unmasked sentinel |
| T3 | same file, in-process with a temporary empty plugins directory | (1) `ensure_installed()` wraps a foreign factory, logs exactly one WARNING, and the foreign factory still runs; a second call is silent and adds no layer. (2) **Cooperative chain**: a foreign `G` that captured and calls the current scrubber `F1` replaces it; `ensure_installed()` builds `F2 → G → F1`; a carrier logged through it comes out exactly as through `F1` alone, `G` runs once, and the scrubber runs twice with no recursion. (3) **Repeated replacement**: three rounds of foreign replacement and re-installation build a finite chain, and logging through it terminates and gives the single-wrapper output. (4) Every wrapper's `__mino_log_scrubber_previous__` is the factory current at its creation, and re-assigning the module's state cannot change it. (5) `discover_plugins` restores the wrapper on each of its three exits: the cached return (`use_cache=True` after a completed discovery), the normal return, and an exception raised from a patched `_discover_plugins_impl` | (a) put `ensure_installed()` after the existing `try/finally` instead of in an outer `finally`; (b) make the predecessor a module global that `install()` reassigns | (a) the cached-exit case, "foreign factory not wrapped after cached discovery"; (b) case 2 failing with `RecursionError` |
| T4 | `tests/test_log_scrub.py`, property tests | Property § 5 (a), **differential against `redact_url` as the oracle**. Tokens are built from 1 to 28 pieces drawn from a trigger-dense list: `/`, `//`, `://`, `?`, `#`, `&`, `=`, `@`, `:`, `%`, `%77`, quotes, brackets, `,`, `;`, the four keys in mixed case and percent-encoded spellings, the four prefixes, scheme words, a host, digits, `3.ts`, a non-ASCII letter, a non-ASCII digit, and a lower-case sentinel. For each token: if the sentinel is absent from the oracle's output, it is absent from `scrub_text`'s output. The oracle is `redact_url` applied to the token, and to the token with its wrappers removed, with the root route counted only when that text starts with `/`. Fixed cases, each with the sentinel: `username=<s>)))`, `password=)))`, `https://outer.invalid/?username=https://<s>.invalid/x`, the same in a fragment (`#token=https://<s>.invalid/`), a bare assignment (`password=https://<s>.invalid/`), `x=token=<s>`, `pass%77ord=<s>`, `//u:<s>@h/x`, `http://h//u/<s>/1.ts` | (a) restore a trailing wrapper after a mask; (b) split the token at each `://` and mask each piece separately; (c) drop the percent-decoded name check | (a) `username=<s>)))`; (b) the nested-URL-in-`username` case; (c) `pass%77ord=<s>` |
| T5 | same file | (1) Property § 5 (d): `scrub_text(scrub_text(x)) == scrub_text(x)` and the same for `scrub_tail`, over T4's token strategy joined by whitespace and over lengths near both caps. (2) Property § 5 (b): fixed benign inputs are returned as the **same object**: `A&E / HD`, `24/7 News`, `2026/11/12`, `https://docs.example.invalid/guide`, `http://127.0.0.1:5658`, `http://example.invalid/channels/5`, `/api/channels/streams/`. An unchanged record keeps its original `msg` object and `args`. (3) Every over-mask in § 4.3's table, pinned to its exact output, including `C:/live/cache/config.json` → `C:/live/***` | make the root rule accept a `/` preceded by a digit as a path start | the `2026/11/12` same-object assertion |
| T6 | same file | (1) Property § 5 (c): `len(scrub_text(x)) ≤ 16,384` and `len(scrub_tail(x)) ≤ 65,536`, for dense short-value inputs below, at and above each cap: `"username=x " * k` for `k` from 1,480 to 1,500 (round 2's 16,379-character case among them), `"password= " * k`, `"//a@" * k` and `"/live/x " * k`. (2) Each of these, exactly 16,384 characters long, goes through `scrub_text` in under 100 ms (measured at most 10.6 ms, § 12): `"/" * n`, `"//" * n`, `"a/" * n`, `"a://" * n`, `"a=&" * n`, `"password=) " * n`, `"/a/b/1#username=x " * n`, `"//a@" * n`, `"=/" * n`, `"(/a" * n`, `"%=" * n`, `"(/a/b/" * n`. The same shapes at 65,536 characters go through `scrub_tail` in under 400 ms (measured at most 41.6 ms). (3) `"word " * 300000` scrubs to at most 16,384 characters ending in the marker. (4) A carrier straddling the cut is absent from the output, not half-present | (a) remove the output cut, keeping the input cut; (b) remove the slash-run de-duplication in the root check | (a) `"username=x " * 1489`'s output length, 19,357; (b) the `"/" * n` timing (measured at about 900 ms without it) |
| T7 | same file | Failure, one case per field, each run with a text handler and with `logging.raiseExceptions` left `True`. (1) `scrub_text` patched to raise: no exception reaches the caller; the record carries the "scrubber failed" placeholder; the sentinel is absent. (2) `logger.info("%d", "<sentinel>")`: the "formatting failed" placeholder, and nothing on stderr contains the sentinel. (3) A previous factory that pre-sets `exc_text` to text containing `username=<sentinel>`: the output shows `username=***`. (4) `logger.exception` whose message carries `http://example.invalid/xmltv.php?username=<sentinel>`: the traceback shows `username=***`. (5) `scrub_tail` patched to raise, with a cached `exc_text` and a `stack_info` both holding the sentinel: both fields are placeholders and the sentinel is absent. (6) The outer fallback: `_scrub_record`'s message step patched to raise a non-`Exception`-handled error after `exc_text` is set: all three fields hold placeholders. (7) A traceback over 65,536 characters whose last line is `ValueError: tail-marker` keeps that line | (a) on a scrubber exception, fall back to the unscrubbed `getMessage()`; (b) skip a pre-set `exc_text`; (c) make the outer fallback replace only `msg` | (a) the sentinel in case 1's output; (b) case 3; (c) case 6 |
| T8 | `tests/test_observability_redaction.py` (LS-2; tests added, none edited) | (1) **Bounded differential.** Every string handed to an old expression is **at most 64 characters**: a `@given` strategy concatenates 1 to 16 fragments and drops any result longer than 64. The fragments are quote characters, `=`, `:`, `/`, `(`, `"<>,;)]`, whitespace, keywords in mixed case (`token`, `AUTH`, `PassWord`, `api-key`, `ſecret`), `://`, scheme words, `1http`, non-ASCII letters and a superscript digit. On each string, `_scrub_urls`, `_scrub_key_values` and `_scrub_paths` equal the old `re.sub`, and `redact_text` equals the old composition. The old expressions live only in the test module, as the oracle. (2) Fixed examples, each also checked against the oracle: `1https://example.invalid/x`, `x=token=pass`, `token="one two";x=token=three`, `token='auth=x'auth=y`, `.-AUTH.key: "v"`, `ſecret=x`, `éhttps://x`, `a/b(/c)`, `/é`, `/éa`, and one 64-character string per scanner. (3) **Timing, scanner-only.** The long inputs `"a" * 32000`, `"a." * 16000`, `"auth" * 8000`, `'token="' * 4500` and `"/(" * 16000` go through the new `redact_text` in under 50 ms each; the oracle never sees them. A bounded differential complements the structural argument of § 6.2; it does not prove equivalence | (a) restore `_PATH_RE.sub`; (b) replace `_scrub_urls` with the round-1 lookbehind expression | (a) the `"/(" * 16000` timing; (b) the `1https://…` fixed example |
| T9 | `tests/test_log_scrub_sinks.py`, in-process | The JSON sink, through `JsonFormatter`, and the OTLP sink, through `OtelBridgeHandler` with `logs.install_inner_handler` given an OTel `LoggingHandler` over a `LoggerProvider` with a `SimpleLogRecordProcessor(RedactingLogExporter(InMemoryLogExporter()))`: a body `get.php?username=<sentinel>&x=1` reaches neither. `redact_text` does **not** remove that shape: it has no leading `/`, and `username` is not among `_KEY_VALUE_RE`'s keywords. The export is asserted non-empty and to hold the record first, and the structured fields match the observability tests' expectation. The test restores the factory and the inner handler in `addCleanup` | swap the active factory for the one the scrubber wrapped, for the duration of the test, then log | the sentinel in the exported body |
| T10 | `tests/test_url_redaction_leaf.py` (LS-3) | (1) `dispatcharr/url_redaction.py` and `dispatcharr/log_scrub.py` import only the standard library and each other (AST walk). (2) `dispatcharr.utils.REDACTED`, `SENSITIVE_QUERY_KEYS` and `XTREAM_PATH_PREFIXES` **are** the objects in `dispatcharr.url_redaction`. (3) Within `dispatcharr/log_scrub.py`, no function reachable from the factory closure or `_scrub_record` (computed over the module's AST call graph) contains a logging call. (4) The only logging call in the module is the single constant-message WARNING in `ensure_installed` | (a) add `from django.http import JsonResponse` to `dispatcharr/url_redaction.py`; (b) add a `logger.debug(...)` to `scrub_text` | (a) "non-stdlib import: django.http"; (b) "logging call reachable from the factory: scrub_text" |
| T11 | `tests/test_celery_suppress_filter.py` | Built through `setup_celery_logging()` with the level not TRACE. (1) An ERROR record on `celery.app.trace` whose template is `"Task %s raised: %s"` and whose argument contains `received` and `http://user:pass@example.invalid/` is emitted, with the credential masked. (2) An INFO record with the template `"Task %s succeeded in %ss: %s"` whose return value carries a carrier is still suppressed. (3) An INFO `"Task %s received"` is still suppressed | remove the level guard | case 1, "error record suppressed" |
| T12 | `tests/test_log_scrub_install.py` | Static: each launcher imports the package before application code. `docker/supervisord.d/celery-*.conf` start `celery -A dispatcharr`; `docker/supervisord.d/daphne.conf` names `dispatcharr.asgi`; every `docker/uwsgi*.ini` has `import = dispatcharr.gevent_patch` or a `module`/`wsgi-file` under `dispatcharr` | change a Celery conf to `-A apps` | "launcher does not import the dispatcharr package: celery-default.conf" |

`tests/test_redaction.py`, the existing `redact_url` property suite, must pass unchanged across LS-3. That shows that moving the three constants changed nothing.

### 9.2 Existing tests whose policy is stronger than the scrubber (D11)

The test process runs with the scrubber on (§ 4.6). So a test that captures records and asserts that a credential-shaped value is absent would pass even if its call site regressed: the factory removes the value before capture. One example is `apps/m3u/tests/test_m3u_filter_url_logging.py:152-159`, `test_failed_stream_exception_text_is_not_logged`. Its call site, `apps/m3u/tasks.py:1587-1593`, logs `type(e).__name__`; changed back to `str(e)`, it would still pass under the scrubber. Such a test still runs green, but it no longer proves the stronger policy it names (the exception text, the pattern, the URL is not logged at all).

LS-3 therefore adds `tests/log_scrub_rig.py` with one context manager, `unscrubbed_logging()`. A test whose policy is stronger than the scrubber captures inside it, so it again observes the raw call site. The contract:

1. **Entry checks.**
   - The current factory must carry `__mino_log_scrubber__`, or it raises `AssertionError("scrubber not installed at entry")`.
   - Its `__mino_log_scrubber_previous__` must not, so only one scrubber layer is ever removed; otherwise `AssertionError("nested scrubber chain")`.
   - The rig must not already be active; otherwise `RuntimeError("unscrubbed_logging is not re-entrant")`. **Nesting is refused, not supported.**
2. **During.** It records the exact factory object it found, sets the factory to that object's predecessor, and marks itself active.
3. **Exit, in `finally`.** It sets the factory back to the **exact object recorded at entry** and clears the active flag. This happens on every exit, an assertion failure inside the block included.
4. **Scope.**
   - It changes a process-global, so it is used only in the test's own thread, never around code that starts threads or greenlets that log.
   - It is never used in two overlapping contexts. Rule 1 enforces that within one process.
   - Django's runner executes a process's tests sequentially; `--parallel` gives each worker its own process and its own factory.
   - A background thread that logs during the window logs unscrubbed. In a test process that is acceptable.
5. **No silent repair elsewhere.**
   - T2 and T9 begin by **asserting** that the current factory carries the marker. They never call `install()`, so a factory leaked by a broken rig fails them instead of being repaired.
   - T1 runs in a cold child and is independent of the rig.

The rig has its own tests in `tests/test_log_scrub_install.py`:
- the exact entry factory is restored after an exception raised inside the block;
- a nested entry raises and leaves the outer context's state intact;
- entering with no scrubber installed raises.

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

### LS-1: withdrawn

Round 3 no longer calls `redact_url` from the scrubber (§ 6.1), so nothing needs to move ahead of LS-3. The three constants the scrubber shares move inside LS-3.

### LS-2: `redact_text` made linear

- **Files:**
  - `dispatcharr/observability/redaction.py`: `_scrub_urls`, `_scrub_key_values` and `_scrub_paths` from Appendix A replace the `_URL_RE`, `_KEY_VALUE_RE` and `_PATH_RE` substitutions in `redact_text`. The three old expressions are deleted from the module and live on only as the test oracle.
  - `tests/test_observability_redaction.py`: T8 added; no existing test edited.
- **Independent of LS-3**; it may land first. Its PR files the issue for the defect and references it (Q3).
- **Gates:** the credential-logging checker is unaffected.

### LS-3: the scrubber

- **Files:**
  - `dispatcharr/url_redaction.py` (new): `REDACTED`, `SENSITIVE_QUERY_KEYS` and `XTREAM_PATH_PREFIXES`, moved from `dispatcharr/utils.py:59`, `:63` and `:106`. `dispatcharr/utils.py` re-exports them, and nothing else in it changes.
  - `dispatcharr/log_scrub.py` (new): `scrub_text`, `scrub_tail`, `_scrub_record`, `install` and `ensure_installed`, with the caps as module constants. Appendix B is the fuzzed core of `scrub_text` and `scrub_tail`.
  - `dispatcharr/__init__.py`: install first, through the relative import.
  - `apps/plugins/loader.py`: an outer `try/finally` around `discover_plugins`' whole body, calling `ensure_installed()` (imported inside the function).
  - `dispatcharr/celery.py`: the level guard in `SuppressFilter`.
  - New tests: `tests/test_log_scrub.py`, `tests/test_log_scrub_install.py`, `tests/test_log_scrub_sinks.py`, `tests/test_celery_suppress_filter.py` and `tests/log_scrub_rig.py` (T1–T7, T9–T12, and the rig's own tests).
  - Existing tests: the stronger-policy tests moved to capture inside `unscrubbed_logging()` (§ 9.2), listed in the PR body.
  - `scripts/product_name_allowlist.txt`.
  - `docs/observability.md`: one short section saying what the scrubber masks in every sink, what it leaves, the limits, and that it is best effort, not a proof.
  - CLAUDE.md § Known defects and traps → Security: the bullet that says provider names are "still logged, deliberately for now" is updated to name the scrubber, the residuals of § 7, and the two follow-ups by issue number.
- **Depends on nothing.** The PR files F1 and F2 as issues (`gh issue create --repo D10Scot/Dispatcharr`, label `needs-triage`) and names them in its body with "Refs #N".
- **Gates:**
  - Product-name ratchet (above).
  - Credential-logging checker: `dispatcharr/log_scrub.py`'s one logging call is a constant-message WARNING with no argument, which the checker clears.
  - Gate 2 is untouched.
  - The `PostToolUse` hook runs the `tests` package on every edit of a new test file, against whichever tree `dispatcharr-testrunner` is mounted on (CLAUDE.md § Test hooks). Re-point it first.
- **Concurrent work:** `credcheck-impl` is widening `scripts/check_credential_logging.py` in `.worktrees/credcheck`. The files are disjoint and neither design depends on the other: the checker stays the call-site lint, and the scrubber is the floor behind it. Whichever lands second rebases and re-runs the checker over its own new files.

## 11. Open questions for the owner

Only the questions that change the design are listed. Each has a recommended default, which the spec already assumes.

- **Q1. Blunt carrier masking, or reduce every URL to its host?** The Go relay keeps only the scheme and host (`relay/redact/redact.go:72`), which also catches opaque path tokens (§ 7 item 1). Doing that here would drop every path operators read today. Round 3's rule sits between the two. It keeps host and path up to the first credential position, then masks to the end of the token. The cost is the over-masks listed in § 4.3. The most visible is that a call site's `redact_url` output `…/live/***/***/1.ts` prints as `…/live/***`, losing the stream id. **Default: the blunt rule (D2), with its over-masks accepted as listed.**
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

**The scrubber core (Appendix B; round 3's blunt rule).**

- **Leaks against the oracle.** 2,000,000 tokens over eight seeds, each built from 1 to 14 or 1 to 28 pieces. The pieces are those T4 lists: separators, the keys in mixed case and percent-encoded, the prefixes, schemes, wrappers, digits, non-ASCII characters and a lower-case sentinel. **0** cases where `redact_url` removed the sentinel (§ 5 (a)'s oracle) and `scrub_text` did not.
  - The first version of the root rule leaked once in that run, on `//username://qzq.api%5Fkey/:(//3.tshttps#`, a root route whose path begins with `//`. The fix: the first `/` after every authority is a path start even when another `/` follows it. Slash-run de-duplication keeps that linear.
  - The oracle is checked case-sensitively with a lower-case sentinel, because `urlunsplit` lower-cases a scheme. An upper-case sentinel would make the oracle look as if it had removed the sentinel.
- **Idempotence.** Byte-identical on every one of those 2,000,000 tokens. It also held for the cap sweeps below.
- **Output cap.** It held for:
  - `"username=x " * k` for every `k` from 1,480 to 1,499. `k = 1489` is 16,379 characters in and 16,362 out, where round 2's design gave 19,357.
  - `"password= "`, `"//a@"`, `"//a@ "`, `"/live/x "`, `"x=token=y "` and `"a=b "` repeated from 2,600 to 2,800 times.
  - 20,000 random mixtures with lengths from `cap − 200` to `cap + 400`.

  0 violations, and 0 non-idempotent outputs.
- **Timing of the token scan, single runs:**

  | Input, repeated to length | 16,384 | 65,536 |
  |---|---|---|
  | `"/"` | 2.2 ms | 8.7 ms |
  | `"//"` | 2.3 ms | 8.9 ms |
  | `"a://"` | 1.9 ms | 7.8 ms |
  | `"a=&"` | 2.5 ms | 10.8 ms |
  | `"password=) "` | 2.4 ms | 9.4 ms |
  | `"/a/b/1#username=x "` | 2.4 ms | 9.9 ms |
  | `"//a@"` | 2.6 ms | 10.8 ms |
  | `"=/"` | 6.6 ms | 26.6 ms |
  | `"(/"` | 4.6 ms | 18.2 ms |
  | `"%="` | 10.6 ms | 41.6 ms |

  Before slash-run de-duplication, `"/" * 16384` took 905 ms: the quadratic T6's break-check (b) names.
- `"word " * 300000` scrubbed to 16,369 characters ending in ` [log scrubber: truncated from 1500000 characters]`, and a second pass left it unchanged.
- Fixed examples:

```
username=CANARY)))                                 -> username=***
https://outer.invalid/?username=https://CANARY.invalid/x
                                                   -> https://outer.invalid/?username=***
/play.html#token=https://CANARY.invalid/           -> /play.html#token=***
password=)))                                       -> password=***
x=token=y                                          -> x=token=***
pass%77ord=CANARY                                  -> pass%77ord=***
http://u:p@h.invalid/x)                            -> http://***@h.invalid/x)
http://h.invalid//u/CANARY/1.ts                    -> http://h.invalid/***
https://outer.invalid/?to=http://u:p@inner.invalid/live/alice/bravo/1
                                                   -> https://outer.invalid/?to=http://***@inner.invalid/live/***
get.php?username=u&password=p#a                    -> get.php?username=***              (over-mask)
/alice/bravo/123.ts#frag                           -> /***                              (over-mask)
'/u/p/1.ts',                                       -> '/***                             (over-mask)
(/live/u/p)                                        -> (/live/***                        (over-mask)
/srv/live/cache/config.json                        -> /srv/live/***                     (over-mask)
C:/live/cache/config.json                          -> C:/live/***                       (over-mask)
Not Found: /api/channels/5/                        -> Not Found: /***                   (over-mask)
http://***@example.invalid/live/***/***/1.ts       -> http://***@example.invalid/live/*** (over-mask)
2026/11/12                                         -> 2026/11/12                        (same object)
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

This is the prototype that § 12 measured, with its imports pointed at LS-3's `dispatcharr/url_redaction.py`. `_scrub_record`, the factory closure, `install` and `ensure_installed` are specified in §§ 4.1–4.6 and are not reproduced here. The implementer may restructure the code. What they must keep is § 4.3's rule, § 4.4's cut rule, and T4–T6.

```python
import re
from urllib.parse import unquote

from dispatcharr import url_redaction

MASK = url_redaction.REDACTED  # "***"
SENSITIVE_QUERY_KEYS = tuple(url_redaction.SENSITIVE_QUERY_KEYS)
CAP = 16384
TAIL_CAP = 65536
RESERVE = 64

_TOKEN_RE = re.compile(r"\S+")
# Built from url_redaction.XTREAM_PATH_PREFIXES in the implementation; spelled out here.
_PREFIX_RE = re.compile(r"(?i)(?<![A-Za-z0-9])(?:live|movie|series|timeshift)/")
_DIGIT_RE = re.compile(r"\d")
_NAME_DELIMS = "&?#=/"
_PATHISH = frozenset("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789._~%-/")


def _key_tail(tok):
    """Index after the first '=' whose name names a sensitive key, or -1."""
    start = 0
    n = len(tok)
    i = 0
    while i < n:
        c = tok[i]
        if c == "=":
            name = tok[start:i]
            low = name.lower()
            dec = unquote(name).lower() if "%" in name else low
            if any(k in low or k in dec for k in SENSITIVE_QUERY_KEYS):
                return i + 1 if i + 1 < n else -1
            start = i + 1
        elif c in _NAME_DELIMS:
            start = i + 1
        i += 1
    return -1


def _prefix_tail(tok):
    for m in _PREFIX_RE.finditer(tok):
        if m.end() < len(tok):
            return m.end()
    return -1


def _root_ok(tok, p):
    """tok[p] == '/'; True when two non-empty segments then one starting with a digit follow."""
    n = len(tok)
    i = p
    segs = 0
    while i < n:
        # skip slashes
        while i < n and tok[i] == "/":
            i += 1
        if i >= n or tok[i] in "?#":
            return False
        if segs == 2:
            return bool(_DIGIT_RE.match(tok, i))
        j = i
        while j < n and tok[j] != "/" and tok[j] not in "?#":
            j += 1
        if j >= n or tok[j] in "?#":
            return False
        segs += 1
        i = j
    return False


def _authority_spans(tok):
    """Userinfo spans [a, b) after each '//' and the path start after each authority."""
    spans, path_starts = [], []
    n = len(tok)
    k = tok.find("//")
    while k != -1:
        a = k + 2
        j = a
        while j < n and tok[j] not in "/?#":
            j += 1
        at = tok.rfind("@", a, j)
        if at > a:
            spans.append((a, at))
        if j < n and tok[j] == "/":
            path_starts.append(j)
        k = tok.find("//", j if j > k + 1 else k + 1)
    return spans, path_starts


def _root_tail(tok, extra_starts):
    starts = set(extra_starts)
    for i, c in enumerate(tok):
        if c == "/" and (i == 0 or tok[i - 1] not in _PATHISH) and tok[i + 1 : i + 2] != "/":
            starts.add(i)
    examined = 0  # starts inside an already examined run of slashes give the same answer
    for p in sorted(starts):
        if p < examined:
            continue
        if _root_ok(tok, p):
            return p + 1
        examined = p
        while examined < len(tok) and tok[examined] == "/":
            examined += 1
    return -1


def scrub_token(tok):
    spans, path_starts = _authority_spans(tok)
    tails = [t for t in (_key_tail(tok), _prefix_tail(tok), _root_tail(tok, path_starts)) if t != -1]
    tail = min(tails) if tails else len(tok)
    kept = []
    for a, b in spans:
        if a >= tail:
            continue
        if b >= tail:
            tail = a
            continue
        kept.append((a, b))
    if not kept and tail == len(tok):
        return tok
    out, pos = [], 0
    for a, b in kept:
        if a < pos:  # overlapping spans cannot occur (authorities are disjoint), defensive
            continue
        out.append(tok[pos:a])
        out.append(MASK)
        pos = b
    out.append(tok[pos:tail])
    if tail < len(tok):
        out.append(MASK)
    return "".join(out)


def _scan(text):
    if "/" not in text and "=" not in text:
        return text
    out, last = [], 0
    for m in _TOKEN_RE.finditer(text):
        tok = m.group()
        if "/" in tok or "=" in tok:
            s = scrub_token(tok)
            if s != tok:
                out.append(text[last:m.start()])
                out.append(s)
                last = m.end()
    if not out:
        return text
    out.append(text[last:])
    return "".join(out)


_WS = " \t\n\r\f\v"


def _cut_head(text, n_original):
    limit = CAP - RESERVE
    cut = max(text.rfind(ws, 0, limit + 1) for ws in _WS)
    kept = text[:cut] if cut > 0 else ""
    return kept + f" [log scrubber: truncated from {n_original} characters]"


def scrub_text(text):
    n = len(text)
    src = _cut_head(text, n) if n > CAP else text
    out = _scan(src)
    if len(out) > CAP:
        out = _cut_head(out, n)
    return out


def _cut_tail(text, n_original):
    start = len(text) - (TAIL_CAP - RESERVE)
    cut = min((i for i in (text.find(ws, start) for ws in _WS) if i != -1), default=-1)
    kept = text[cut:] if cut != -1 else ""
    return f"[log scrubber: truncated from {n_original} characters]" + kept


def scrub_tail(text):
    n = len(text)
    src = _cut_tail(text, n) if n > TAIL_CAP else text
    out = _scan(src)
    if len(out) > TAIL_CAP:
        out = _cut_tail(out, n)
    return out
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

### Round 2 → round 3 (review pinned at `f9384a61`)

Round 2 resolved round-1 items 1, 2, 5, 6, 7, 8 and 9, and hand-walked Appendix A clean; none of that is touched. Findings 1–3 were the third generation of edge cases from token surgery: wrapper stripping, scheme splitting and the "already masked" shortcut. They are not patched one by one. § 4.3 replaces the surgery with a blunt rule: mask userinfo in place, and mask from the first credential position to the end of the token, with no restoration and no shortcut.

| # | Finding | Severity | Disposition |
|---|---|---|---|
| 1 | `username=***)))` survives: the unchanged-token shortcut returned before the trailing-wrapper rule | blocking | **Fixed by redesign.** No wrapper is stripped or restored, and there is no unchanged-core shortcut. The key rule masks from after `=` to the end of the token, so `username=***)))` becomes `username=***`. Fixed case in T4, with break-check (a). |
| 2 | Splitting at every scheme exposes a sensitive parameter's value (`?username=https://…`), in a query, a fragment or a bare assignment | blocking | **Fixed by redesign.** Nothing is split at `://`. A sensitive value is masked to the end of its token, any URL inside it included. A URL in a non-sensitive parameter keeps its own userinfo and path masks. All three shapes are fixed cases in T4, with break-check (b). `redact_url` is now the test oracle, not the engine (§ 6.1). |
| 3 | Mask expansion defeats the cap and idempotence (`"username=x " * 1489`: 16,379 → 19,357); S:15 wording | should-fix | **Fixed.** One cut rule, applied to the input before the scan and to the output after it (§ 4.4), so the output never exceeds the cap. The example now gives 16,362. Idempotence is byte-identical for the reason § 5 (d) gives. S:15 now says the scan reads at most the cap. T6 sweeps dense short values below, at and above both caps, with break-check (a). |
| 4 | T8 has no bound on the oracle's input length | should-fix | **Fixed.** Oracle comparisons are on strings of at most 64 characters from a structured fragment strategy, plus fixed examples, including the reviewer's hand-walked ones and one at the bound for each scanner. The long timing inputs run on the new code only. T8 states that a bounded differential complements the structural argument and does not prove equivalence. |
| 5 | D11 rig: restoration, nesting and shared-process use unspecified; T2 might repair a leaked factory | should-fix | **Fixed.** § 9.2 gives a five-part contract: entry checks; restore the exact entry object in `finally`; no nesting (raises); single-thread, no-overlap scope; and T2 and T9 assert rather than install. The rig has its own restoration, nesting and no-scrubber tests. |
| 6 | Reinstallation vs "exactly once": `F2 → G → F1` double-scrubs; a mutable predecessor allows `F1 → G → F1` recursion | should-fix | **Fixed, and the claim narrowed.** Each install wraps the current factory in a fresh closure whose predecessor is bound at creation. There is no module-global predecessor (§ 4.1). Repeated scrubbing is harmless because the rule is idempotent, so the claim is now "at least once; repeated passes change nothing" (§ 4.6). Recursion is impossible by construction, because each closure calls only something created before it. T3 adds the cooperative-chain and repeated-replacement cases, and a mutable-global break-check. |
| 7 | S:229 says T13, means T12; add `C:/live/cache/config.json` as an over-mask | nit | **Fixed.** The text now refers to T12. `C:/live/cache/config.json` → `C:/live/***` is in § 4.3's over-mask table and pinned by T5. |
| — | D10 is a real visibility change, not only a scrubber consequence | note | **Agreed; wording unchanged.** D10 already presents itself as a deliberate policy revision. § 4.7 does not claim that suppression is otherwise preserved. |

**Consequences of the redesign, stated rather than hidden:**

- **Claims withdrawn.** The universal `redact_url` pass-through claim is gone (§ 5), and so is "exactly once" (§ 4.6).
- **New over-masks.** These are listed in § 4.3 and pinned by T5:
  - a call site's `redact_url` output loses its stream id;
  - parameters after a sensitive key go with it;
  - a root-route path collapses to `/***`.
- **LS-1 is withdrawn** (§ 10). Three constants move in LS-3, and `redact_url` does not change.
- **A new prototype was fuzzed** (§ 12): 2,000,000 tokens against `redact_url` as the oracle, with 0 leaks and 0 non-idempotent outputs. One root-route defect, a path that begins with `//`, was found by that fuzz and fixed before this commit.

