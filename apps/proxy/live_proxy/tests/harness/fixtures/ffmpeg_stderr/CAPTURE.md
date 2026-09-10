# The ffmpeg stderr corpus

These three files are **verbatim captures of real ffmpeg stderr**, byte for
byte, `\r` record separators included. **Never hand-edit them.** Regenerate
with:

```bash
docker exec -w /repo dispatcharr-testrunner bash -lc \
  'export PATH=/dispatcharrpy/bin:$PATH; python scripts/capture_ffmpeg_stderr.py \
     apps/proxy/live_proxy/tests/harness/fixtures/ffmpeg_stderr'
```

then copy the three `.stderr` files out of the (read-only-mounted) container
with `docker cp` before committing them.

## Provenance

- **ffmpeg version**: `8.1.2` (`ffmpeg -version | head -1` with
  `LD_LIBRARY_PATH=/usr/local/lib` set — see below), captured
  2026-09-10 in `dispatcharr-testrunner`.
- **Command driven**: the PRODUCTION command,
  `core/migrations/0003_preload_stream_profiles.py`'s
  `ffmpeg -i {streamUrl} -c:v copy -c:a copy -f mpegts pipe:1`, no `-loglevel`,
  so the default `info` verbosity — exactly what `input/manager.py`'s stderr
  reader sees in production.
- **Upstream**: a looping ~8-second lavfi-generated asset (H.264/AAC in
  MPEG-TS), served over a local HTTP server at a controlled byte rate, by
  `scripts/capture_ffmpeg_stderr.py`.
- `LD_LIBRARY_PATH=/usr/local/lib` is set for the capture: the image carries
  two `librist` and the loader picks the wrong one without it, dying with
  `undefined symbol: rist_peer_config_defaults_set_versioned`.
  `docker/entrypoint.sh:102` sets this in production; the hook container and
  `backend-tests.yml` do not run that entrypoint. Tracked as
  [D10Scot/Dispatcharr#226](https://github.com/D10Scot/Dispatcharr/issues/226) —
  this is a **workaround**, not the fix; #226's own suggested fixes are
  ordered image-first, with exporting the variable in the test bootstraps as
  the last resort.

## What each fixture is, and its shape

| Fixture | Capture | Shape observed |
|---|---|---|
| `normal.stderr` | upstream at 2.0× real time, 8 s | a few KB; a handful of progress records; preamble carrying the banner, `Input #0, mpegts`, `Stream mapping:`, `Output #0, mpegts, to 'pipe:1'` and `Press [q] to stop`; `speed=` starts well above 1.0 and decays without crossing it |
| `slow-trickle.stderr` | upstream at 0.25× real time, 45 s | roughly ten KB and several dozen records; same preamble; `speed=` starts well above 5.0, crosses below 1.0 partway through, and the **last record stays below 1.0** — that crossing is the whole point of the fixture |
| `truncation.stderr` | upstream at 2.0×, cut after 3 s of media | a few KB; **exactly one** progress record, LF-terminated, so this fixture contains **zero CR bytes**; preamble carrying `Stream ends prematurely at …` and `Error during demuxing: Input/output error`; the one record's `speed=` is in scientific notation (`speed=…e+03x`) |

**Every digit above is a timing measurement, not a fact about ffmpeg.** The
record count, the exact `speed=` values and the index at which the curve
crosses 1.0 all move between machines and runs — a second capture on
different hardware will not reproduce them. **Do not write "a changed value
is ffmpeg drift, update the table"**: the values move run to run on the very
same ffmpeg binary, so a table of literal digits would be wrong on its next
reading and would invite someone to encode one in a test. What must hold, and
what every test in `test_harness_standin.py` actually asserts, is the
*shape*: `slow-trickle` starts high and ends below 1.0 with a sustained tail;
`truncation` has exactly one LF-terminated record in scientific notation;
`normal` and `slow-trickle` are CR-separated between records.

`slow-trickle.stderr` is the single most valuable artefact here: it is
empirical proof of parity-matrix row 4 — "`speed=` is a cumulative average
since process start, taking on the order of tens of seconds to arm." Against
a genuinely 0.25×-real-time upstream, real ffmpeg's cumulative average took
on the order of 18-20 seconds of wall clock before first touching 1.0 and
settling below it. The order of magnitude is the finding; the exact second is
not, and no test asserts one.

## Details of the real format a hand-written line would have got wrong

- ffmpeg 8.1.2 appends an **`elapsed=0:00:00.50`** field after `speed=`,
  which older documented examples (including the comment at
  `input/manager.py:1062`) do not show.
- The **final** progress line uses `Lsize=`, not `size=`.
- The speed field is **space-padded** when short: `speed= 1.1x`, with a
  space, or even `speed=   1x`. The production regex
  `re.search(r'speed=\s*([0-9.]+)x?', …)` (`input/manager.py:1065`) has the
  `\s*` and handles it; a few lines in `slow-trickle.stderr` are of this
  form, so the corpus exercises it.
- Records are **terminated** by `\r` — ffmpeg rewrites one status line in
  place — **except the last, which a gracefully-exiting ffmpeg (including one
  that receives SIGTERM) terminates with `\n`**. So CR == records − 1 for a
  clean or SIGTERM-ended process, and a capture with a single record
  (`truncation.stderr`) has no CR at all — its lone record is the final
  `Lsize=` line, ended with a demuxing error rather than SIGTERM, and it too
  ends LF. Splitting on `\n` alone gets one enormous line; splitting on `\r`
  alone glues the preamble to record 1 and finds nothing at all in
  `truncation`. Split on both, as `_read_stderr` does.
- **A real ffmpeg emits `speed=` in scientific notation.** `truncation.stderr`'s
  only progress line reads `speed=1.41e+03x` on this capture (the mantissa
  varies run to run; the exponent notation itself is the finding). See
  § Findings item 5 in the plan: the production regex
  `re.search(r'speed=\s*([0-9.]+)x?', …)` stops at the `e` and parses only the
  mantissa, so this line is read as `1.41` instead of `1410` — a roughly
  1000× under-report. Filed as
  [D10Scot/Dispatcharr#227](https://github.com/D10Scot/Dispatcharr/issues/227)
  and parity-matrix row 28. Reproduced here, not fixed: D5 is strict parity,
  defects included.
