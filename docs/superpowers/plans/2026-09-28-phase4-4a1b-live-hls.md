# Plan: Phase 4a-1b, live HLS end to end

> **For agentic workers:** implement this plan task by task with subagents, per CLAUDE.md § Delegation for phase work. The Go and Python code is specified by its contracts below (types, signatures, lock order, flows, test names and their oracles), not by a diff: the implementer writes it. Every documentation and configuration edit is Appendix A, a byte-exact `git diff` against the seed that the implementer applies and does not rewrite; its only non-literal parts are the `⟨…⟩` slots in the parity-matrix rows and the one COVERAGE observation row, each of which names exactly what fills it.

**Goal.** A live tune whose output format resolves to `hls` answers a multivariant playlist, and a player plays the channel from `/hls/<token>/…` on the relay. That means: `hls` becomes a resolved format (the hop's aliases, the relay's `identify()` and the Xtream `.m3u8` override); the relay mints an opaque media-session token and keeps a process-wide session table; the HLS viewer is a client in the channel's registry exactly while its session is live (an explicit `DELETE /hls/<token>`, an admin client stop or stream-limit termination, a stop of its channel, or the idle sweep ends it); a session never outlives its channel's stop and never starts a channel on resume; a failed HLS output marks the channel until its next source boundary; a Redirect-profile channel is served over HLS as Proxy; `nginx` routes `^~ /hls/` to the relay with no authorize hop; Django advertises `m3u8` to Xtream clients, emits `.m3u8` URLs from `get.php`, and answers the Mino app's capability document. `relay/hls` is linked into the binary for the first time, `hls.StoreSegments` rises to 21 (R44), and the Go coverage floor is re-baselined under R21/R27/R34. Spec D2-D5, D13, D19; § The contract; § Presence and lifecycle; § 4a-1b.

**Seed.** `fabc663a9c27cfc317fe52f32a95c5f992d3ef0e` (`fabc663a`, main on 2026-09-28: #529 merged the inert `relay/hls`). Every `file:line` below is at the seed unless it says otherwise.

**Branch.** `migration/phase4-4a1b-live-hls` (spec D1), so the full E2E and lifecycle matrix runs on it.

**Authority.** In order of precedence:

1. The owner's and orchestrator's rulings R1-R48 (the orchestrator's `rulings.md`). The ones this PR carries: R13 and R22 (the opaque token, valid exactly while its session is), R15 (every new externally visible identifier is Mino-named or neutral: `/hls/`, `/api/mino/capabilities/`, `hls_encoder`, `hls_generation`; nothing existing is renamed), R19 (a TS-only channel starts no encode), R21, R27 and R34 (the Go floor: linking `relay/hls`), R23 (D13 Redirect over HLS as Proxy, `hls` never a default, software fallback), R24 and R25 (the explicit leave; grace machinery is 4a-3's), R29 (measure the 1080i software transcode against real time on CI), R44 (`StoreSegments` 21), R45 (hardware measurements do not gate) and R48 (the seam, if a split is needed).
2. The Phase 4 spec, `docs/superpowers/specs/2026-09-27-phase4-apple-native-live-design.md`, as amended by this plan's own PR (§ Spec amendments in this PR): D2-D5 (`:211-214`), D7 (`:216`), D11-D13 (`:222-224`), D19-D20 (`:230-231`), § The ADR 0006 amendment (`:233-259`), § The contract (`:305-438`), § Encoder argv › Failure (`:585-634`), § Presence and lifecycle (`:662-823`), § Testing and gates (`:1081-1210`), § 4a-1b (`:1308-1416`), Q2 and Q6 (`:1593`, `:1597`). Line numbers are this branch's, after the amendments below.
3. The 4a-1a plan (`docs/superpowers/plans/2026-09-27-phase4-4a1a-hls-packager.md`) for the shape of `relay/hls` and its hand-offs (§ Decisions 11, 16, 17; § Overlap), and `relay/hls` **as merged at the seed**, tests included — this plan links against the package as committed, never against that plan's appendix.
4. CLAUDE.md (the Go hooks, stdlib-only, credlint, the Go ratchet as amended by R21/R27, nginx buffering, the commit gate), ADR 0005, ADR 0006 (and ADR 0008's record of its amendment), ADR 0008, ADR 0009, `CONTEXT.md`, and `docs/relay-parity-matrix.md` (every new live-path behaviour lands as a pinned row).

**Issues.** This PR closes no issue. Nothing it carries is tracked by an open issue, so neither its commits nor its description carry a closing keyword or a `Refs`.

## Global constraints

1. **Standard library only**, and no Redis or Postgres by any route (ADR 0006; `scripts/check_go_stdlib_only.sh relay`). The session table, the token and the sweeper are `sync`, `crypto/rand`, `crypto/hmac`, `crypto/sha256`, `encoding/base64` and `time`.
2. **Every error a log or format call carries goes through `redact.Error`**, or carries a written `credential-logging: ok - <reason>` (`scripts/check_go_credential_logging.sh relay`). **The media-session token and its sid are never logged**, at any level, in any form; the `/hls/` handlers log the client id. `credlint` cannot see a string, so a unit test holds this (`TestARejectedTokensTextNeverReachesTheLog`).
3. **Zero lint findings under three GOOS** (`golangci-lint run ./...` natively, `GOOS=linux`, `GOOS=darwin`, v2.13.2), `go vet` and `go test -race ./...` green.
4. **Lock order `m.mu` → `c.mu` → `st.mu`** (spec § Locks). Code holding `st.mu` (the session table's mutex) never takes `c.mu`, `m.mu` or `outMu`, never calls a release func, never emits an event and never writes a response. `outMu` never nests with `c.mu` (as at the seed, `relay/channel/output.go:121-125`) and never with `st.mu`.
5. **The test-modification rule.** An existing test changes only where the behaviour it pins is the thing this PR changes, and every such change is listed in § Tests changed with its before and after. Test-support edits that change no assertion (the rig gaining the session table) are listed there too.
6. **Parity rows 37-44 land pinned** in the `phase 4` block, row 32 gains its E2E pin, and `HIGHEST_ROW_ID` goes 36 → 44 in the same diff. Ids are the next free ones at the seed; if another PR takes any of 37-44 first, renumber at merge (spec: "Ids are assigned at merge time").
7. **The spec amendments ride in this plan PR, not the implementation PR** (§ Spec amendments in this PR). The implementation PR edits no spec text.
8. **No hardware gate** (R45). The PR merges on CI and software-encoder evidence plus the implementer's own AVPlayer run (§ AVPlayer); Quick Sync, the Apple TV and Q1-Q5/Q7 stay the owner's, owed and non-gating.
9. **No new E2E project and no workflow change.** The HLS specs join the `streaming` project (spec § Testing › E2E).

## Overlap with sibling plans

| Plan | Its files | Boundary with 4a-1b |
|---|---|---|
| **4a-1c** slot reclaim | `apps/proxy/next_source.py`, `apps/proxy/serializers.py` (`capacity`), `relay/control/nextsource.go`, `relay/channel/manager.go` (`ReclaimFor`, the releasing set), `relay/channel/channel.go` (`released`), `relay/httpapi/stream.go` (`startTune`'s one retry), `relay/session` (the D16 silence predicate) | 4a-1b records, under `st.mu`, exactly what 4a-1c's predicate reads — each session's in-flight count and the end time of its last request (`Session.inFlight`, `Session.lastEnd`) — and exposes **no** silence predicate and **no** reclaim. The three map-delete sites `manager.go` has — `take` (under `Manager.Stop`/`StopAll`), `stopIfStillIdle` (now reached also through 4a-1b's `StopIfIdle`) and `claim`'s closed-ring delete — are the sites 4a-1c extends with its releasing-set insertion, and `ReclaimFor` is its own fourth; 4a-1b adds no delete site and inserts into nothing. R24's "silent > 2 × TD is departed for slot yield" is 4a-1c's. The limit-1 zap E2E ("a limit-1 user tunes A, calls leave, tunes B: no 429") is 4a-1c's scenario list; 4a-1b provides the leave it needs and pins that the leave's 204 is written only after the client entry is gone. |
| **4a-1d** automatic profile | the `core` and `channels` migrations, `OutputProfile.hls_mode`, `Channel.hls_output_profile`, next-source `hls_profile`, `relay/hls`'s automatic rules, the frontend selects | 4a-1b's HLS output key is the constant `"hls"` (the built-in transcode); 4a-1d introduces `hls:p<id>`. 4a-1b stores each session's target duration from `hls.TargetDuration` (always 2); 4a-1d sources it from the pipeline (R42's per-pipeline `StallTimeout` is 4a-1d's too). 4a-1b already ignores `X-Relay-Output` on an `hls` tune (D12's relay half); the consumer exclusions are 4a-1d's. |
| **4a-2** browser player | `frontend/…` only | 4a-2 relies on 4a-1b's `?output_format=hls` entry, on `?token=` JWT authorization reaching the hop unchanged, and on `DELETE /hls/<token>` answering 204 (idempotent). No shared file. |
| **4a-3** rewind window | `relay/hls` (the disk store, window playlists), `relay/channel/manager.go` (the linger hold), `relay/session` (behind-live tracking, the grace), the four `rewind_*` settings, the capability document's `rewind_window` | 4a-1b's pipeline refcount reaching 0 stops the pipeline at once; 4a-3 turns that into a linger. 4a-1b's capability document reports `rewind_window: {available: false, depth_seconds: 0}`; 4a-3 fills it. 4a-1b does not record which segment a session last fetched or whether a departure was explicit — 4a-3 adds both to `relay/session` (a leave and an idle departure are already distinct code paths in 4a-1b: `Table.Leave` and `Table.Sweep`). CLAUDE.md § State's registry sentence is amended by 4a-1b and again by 4a-3 (linger). |
| 4a-1a (merged, #529) | `relay/hls` | Read and linked. 4a-1b changes one constant there (`StoreSegments`) and one test's two literals that pin it (§ Tests changed); no API change. |

## Decisions the spec leaves open

Each is the plan's own ruling, open to challenge. The ones that change behaviour the spec states are § Open questions instead.

1. **Where the session table lives: a new package, `relay/session`.** It imports `relay/channel` (for `*channel.Channel` and `*channel.Client`) and `relay/hls` (for `*hls.Pipeline`); `relay/channel` never imports it, and reaches it only through an interface it defines (`channel.SessionEnder`), so there is no cycle. `relay/httpapi` orchestrates the entry, the GETs, the leave and the resume. Keeping the table out of `httpapi` lets its state machine be tested with an injected clock and no HTTP, and gives 4a-1c and 4a-3 one file to extend. The package name is internal Go, not an externally visible identifier (R15).
2. **The token lives in `relay/control`** (`mediasession.go`), beside the three HMAC contexts it joins (`relay/control/token.go:40-44`), and reuses its `hmac.Equal`-after-ASCII-check comparison (`matches`).
3. **The channel holds its HLS pipelines in a second map in `outputRegistry`**, typed `*hls.Pipeline`, under the existing `outMu`: `outputEntry.pipeline` is typed `*output.Pipeline` (`relay/channel/output.go:90-94`) and stays so. `AttachOutput`'s refcount semantics are reproduced for HLS, with two additions: the release func is **identity-safe** (it decrements only while the registered entry is the pipeline it attached to, so a stale release after a failure can never stop a fresh pipeline), and `AttachHLSExisting` re-attaches a resume only to the very pipeline its session names.
4. **The client registry entry and the pipeline reference are the session's two releases**, owned by the session while it is ARRIVED or ACTIVE and taken, exactly once, under `st.mu` by whichever transition ends that: a leave, an admin client stop, an idle departure, a failed entry (each then runs them, outside `st.mu`), or STOPPED (which **discards** them: the goroutine that stops the channel or the HLS output drops the client entries itself and the pipeline is torn down with its channel or by the failure path).
5. **An idle departure settles before it is resumable.** The sweeper takes a departing session's releases under `st.mu`, marks it DEPARTED with `settling = true`, and runs the departure (event, then releases) outside `st.mu`; the departure then clears `settling` and stamps `departedAt`. A request that finds a session settling answers 503 with `Retry-After: 1` (a window of milliseconds): without this, a resume could re-register the client id before the departure had dropped it and fail with `ErrDuplicateClient`.
6. **`client_connect` is emitted when the multivariant is about to be written** (after the session becomes ACTIVE), and on a resume when it commits — the HLS counterpart of the TS path's "after the channel is up and the response has begun" (`relay/httpapi/stream.go:299-302`). A session that never got its multivariant emits neither `client_connect` nor `client_disconnect`; `channel.StoppedClient.Connected` carries that fact to the goroutine that drops a STOPPED session's client entry.
7. **The leave's 204 is written after its side effects complete** — the `client_disconnect`, the pipeline release and the client release — so a zap that tunes B the instant A's `DELETE` returns finds A's client entry already gone from the registry the hop counts (spec § The rest, limit-1 zap).
8. **The run-ended self-stop is a manager hook the channel fires on a fresh goroutine.** `Manager.publish` sets `c.onRunEnd = m.runEnded` when `ManagerConfig.Sessions` is set; `Channel.run` gains `defer c.fireRunEnd()`, declared immediately after `defer close(c.done)` so it runs just before `done` closes, and `fireRunEnd` does `go c.onRunEnd(c)`. `runEnded` asks the table to mark the channel's sessions STOPPED and, only when that dropped a client entry, calls `Manager.EndHLSSessions`, which drops the entries and calls `StopIfIdle`. Because the hook fires on every run's end, `Manager.Stop`'s own path (which already marked the sessions) finds nothing and does nothing. The spec's wrong edit (§ 4a-1b break-checks: "synchronously from `run()`'s defer chain") is then exactly the deletion of the `go`.
9. **The HLS-failure self-stop is a watcher goroutine per pipeline**, started by `httpapi` when `AttachHLS` reports it started a new pipeline: it waits on the pipeline's `Done()`; on a non-nil `Err()` it sets the channel's mark and unregisters the pipeline (`Channel.FailHLS`), asks the table to mark that pipeline's sessions STOPPED, and calls `Manager.EndHLSSessions`. On a nil `Err()` (a stop at refcount 0, or its channel ending) it does nothing: the channel's own run-end hook covers a channel that ended.
10. **The mark records its reason** (`hls.ErrNoVideo` or `hls.ErrFailed`), and the entry's 502 body follows it: `{"error": "no video stream in the source"}` or `{"error": "HLS output failed"}` (spec § Entry's two 502 rows). See Open question 2 for whether `ErrNoVideo` marks at all.
11. **`AttachHLS` refuses on a closed ring** (`channel.ErrChannelEnding`, answered 503 `Retry-After: 1`), so a late entry cannot register a pipeline on a channel whose `stopOutputs` has already run.
12. **`X-Relay-Output` is ignored on an `hls` tune** by clearing the registered client's `OutputProfileID` through `Channel.SetClientOutputProfile(client.ID, nil)` — never by writing the field through the pointer, which a status snapshot reads under `c.mu` — and `attachOutputProfile` is never called on the HLS branch (D12's relay half).
13. **Redirect as Proxy** (D13) reuses the internal principal's arm (`relay/httpapi/stream.go:701-713`): `startTune` gains a `viaProxy bool` in place of `internal bool`, passed `internal || client.OutputFormat == OutputFormatHLS`, and logs which of the two reasons applied.
14. **nginx `^~ /hls/`** carries `proxy_read_timeout 60s` explicitly, above the relay's two 20 s waits, and `proxy_connect_timeout 60s` for the byte-path locations' reason (the server block's 75 would otherwise be inherited, CLAUDE.md § Architecture). The fifth greybox test pins both.
15. **The capability document** is a DRF `APIView` in `core/api_views.py` with `permission_classes = [AllowAny]` and `authentication_classes = []` (so a stale Bearer header from a Mino app build never turns it into a 401), gated by `network_access_allowed(request, "XC_API")` (403 otherwise), serialized by nested serializers in `core/serializers.py`, and routed by a new `core/mino_api_urls.py` mounted at `path("mino/", …)` in `apps/api/urls.py`. `server_version` is `version.__version__`; `rewind_window` is `{"available": false, "depth_seconds": 0}` until 4a-3.
16. **`get.php?output=m3u8|hls` with Xtream credentials** emits `/live/<u>/<p>/<id>.m3u8`, drops `output_format` from the query and keeps `output_profile` (which the relay then ignores, Decision 12). Without Xtream credentials nothing changes: `/proxy/ts/stream/<uuid>?output_format=m3u8` already resolves through the new aliases.
17. **E2E drives the upstream at `rate: 1`** on every HLS spec. The HLS output is re-encoded; a faster-than-real-time feed would measure the encoder's backlog, not the product.

## Open questions for the orchestrator

Each has a recommendation, and the plan is written to the recommendation; a different ruling changes the named sections only.

1. **A resume when its pipeline has stopped but its channel runs on (spec gap, behavioural).** The spec says a DEPARTED session resumes "if its channel is still running". In 4a-1b a channel can outlive its HLS pipeline: the lone HLS viewer departs (refcount 0, the pipeline stops at once) while a TS client keeps the channel. A resume that re-attached a fresh pipeline would hand the player a media sequence restarting at 0 under the same playlist URL. **Recommendation: a resume requires its own pipeline to be registered and running (`AttachHLSExisting`); otherwise it answers 410, like an absent channel.** Pinned by `TestAResumeOnAStoppedPipelineIs410`. On the ruling, the spec's § The rest gains one sentence.
2. **Does `hls.ErrNoVideo` set the channel's mark (behavioural)?** The spec sets the mark on "every attempt fails" (`ErrFailed`) and answers a no-video probe with 502. A radio channel (audio only) would otherwise re-probe, 3 s of `ffprobe` per entry, forever. **Recommendation: yes, the mark records its reason (Decision 10); the next source boundary clears it as for `ErrFailed`.** Pinned by `TestANoVideoProbeIs502AndTheTSClientIsUnaffected`'s second entry.
3. **The sweeper runs each departure on its own goroutine (spec § Who ends sessions says "the sweeper goroutine").** A lone viewer's departure releases the channel, whose `c.stop` can wait `StopWait` (5 s). On the sweeper goroutine that delays every other departure by up to 5 s per stopping channel, breaking § The rest's "one idle timeout plus one 1 s sweep tick". **Recommendation: the sweeper starts `go dep.Run()` per departure (never on a channel's goroutine, which is what the spec's rule protects).** Pinned by `TestASlowDepartureDoesNotDelayTheNextTick`.
4. **The floor header's census wording (R21) versus the ratchet's slack.** `scripts/coverage_relay_go.floor`'s "HOW TO MOVE" says a raise needs "the census maximum is the old `missing` plus exactly the listed count". The seed's own census maximum is 564 against a floor of 589 (4a-1a's census at `f44c8135`), so a correct census lands up to 25 below "old plus listed", and the sentence as written cannot be met. **Recommendation: the new floor is `589 + H + O` exactly (§ Coverage) and every census round must not exceed it; and the header's sentence is corrected to "does not exceed the old `missing` plus exactly the listed count".** The plan does not make that one-line edit to the floor file until it is ruled on, because the sentence is R21's own text.
5. **R29's "raise it as a finding".** If CI's software transcode of the 1080i fixture measures below real time, the implementer reports the ratio in the PR body and to the orchestrator; **recommendation: the orchestrator files the issue** (an outward-facing act), and the COVERAGE observation row cites it. Nothing in this PR's assertions moves either way.

## The design

### `relay/control/mediasession.go` (new)

```go
// MediaSessionVersion is the only token version (spec § The media-session token).
const MediaSessionVersion = "v1"

var contextMediaSession = []byte("media-session")

// NewMediaSessionID is 16 bytes from crypto/rand, base64url without padding: 22 characters.
func NewMediaSessionID() (string, error)

// MediaSessionToken is "v1." + sid + "." + base64url_nopad(HMAC-SHA256(secret,
// "media-session" LF "v1" LF sid)): 69 characters, path-safe.
func MediaSessionToken(secret, sid string) string

// VerifyMediaSession splits token on ".", requires exactly three parts, "v1",
// a 22-character sid and a 43-character MAC, all ASCII, and compares the MAC
// with hmac.Equal. It looks nothing up: the table does that after a MAC passes.
func VerifyMediaSession(secret, token string) (sid string, ok bool)
```

### `relay/session` (new package)

`doc.go` states the package's place (spec § Presence and lifecycle; § The ADR 0006 amendment: the one place the relay infers presence) and its lock rule (Global constraint 4).

`thresholds.go`:

```go
const (
	ResumeWindow  = 300 * time.Second // a DEPARTED session may resume, and a STOPPED one is kept unrequested, this long
	SweepInterval = time.Second
)

// IdleTimeout is max(12 s, 6 x TARGETDURATION) (spec § Presence thresholds).
func IdleTimeout(td time.Duration) time.Duration
```

`table.go`:

```go
type State int // Arrived, Active, Departed, Stopped

// Owner is the channel as the table needs it; *channel.Channel satisfies it.
// An interface so the state machine is testable without a running channel;
// identity is pointer equality through the interface.
type Owner interface {
	EmitClientConnect(cl *channel.Client)
	EmitClientDisconnect(cl *channel.Client, at time.Time)
}

// Releases are what an ARRIVED or ACTIVE session holds, run exactly once by
// whoever ends it (Decision 4). Output first: the pipeline reference, then the
// registry entry (Manager.release), which may stop the channel.
type Releases struct{ Output, Client func() }

type Session struct {
	// Immutable after Add.
	ID       string // the sid, never logged
	Owner    Owner
	Key      string // the channel's HLS output key; "hls" in 4a-1b
	Pipeline *hls.Pipeline
	TD       time.Duration // hls.TargetDuration * time.Second in 4a-1b

	// Under Table.mu.
	client     *channel.Client // the current registry entry's client; replaced on resume
	state      State
	inFlight   int
	lastEnd    time.Time // arrival for the entry; the end of the last request after that
	departedAt time.Time
	stoppedAt  time.Time
	settling   bool
	connected  bool // client_connect emitted for the current attachment
	releases   *Releases
}

type Config struct {
	Now  func() time.Time    // nil: time.Now
	Tick <-chan time.Time     // nil: a SweepInterval ticker; tests drive it
	Log  *slog.Logger
}

type Table struct { /* mu (st.mu), byID map[string]*Session, cfg */ }

func NewTable(cfg Config) *Table

func (t *Table) Add(s *Session, client *channel.Client, r Releases) // ARRIVED, inFlight 1, lastEnd now
func (t *Table) Activate(sid string) bool                           // ARRIVED -> ACTIVE, inFlight--, lastEnd now, connected; false if not ARRIVED
func (t *Table) Abandon(sid string) (*Releases, bool)               // a failed entry: remove; the releases when it still held them
func (t *Table) Begin(sid string) Lookup                            // a GET's arrival (below)
func (t *Table) End(sid string)                                     // a GET's completion: inFlight--, lastEnd now; no-op when removed
func (t *Table) ResumeFailed(sid string)                            // resume step 2 failed: remove
func (t *Table) ResumeCommit(sid string, client *channel.Client, r Releases) bool // step 3: DEPARTED and not settling -> ACTIVE, inFlight 1
func (t *Table) Leave(sid string) *Departure                        // DELETE: remove whatever the state; a Departure only when it held releases
func (t *Table) EndClient(o Owner, clientID string) *Departure      // admin client stop / limit termination
func (t *Table) StopChannel(c *channel.Channel) []channel.StoppedClient // implements channel.SessionEnder
func (t *Table) StopPipeline(p *hls.Pipeline) []channel.StoppedClient
func (t *Table) Sweep() []*Departure                                // one tick's work, under st.mu
func (t *Table) Run(ctx context.Context)                            // the process-wide sweeper: every tick, Sweep, then `go d.Run()` each
func (t *Table) Len() int                                           // tests

type Outcome int // Unknown (403), Gone (410, and removed), Busy (503 Retry-After 1), Resume, Serve

type Lookup struct {
	Outcome  Outcome
	Session  *Session
	Client   *channel.Client // for Serve: the client whose meter the response feeds
	Pipeline *hls.Pipeline
	Depart   *Departure      // non-nil when Begin found an ACTIVE session past its idle timeout (lazy expiry)
}

type Departure struct { /* owner, client, connected, releases, idle bool, table, sid */ }
func (d *Departure) Run() // outside st.mu: EmitClientDisconnect if connected; Output(); Client(); if idle, settle (clear settling, stamp departedAt)
```

`Begin` applies every expiry lazily, exactly as `Sweep` would (spec § The sweeper): an ACTIVE session with nothing in flight past `IdleTimeout(TD)` becomes a settling departure returned in `Lookup.Depart` (the handler runs it and calls `Begin` once more); a DEPARTED one past `ResumeWindow` and a STOPPED one unrequested for `ResumeWindow` are removed (`Unknown`). A STOPPED session is removed and answers `Gone` (its one 410). ARRIVED and ACTIVE answer `Serve` and increment `inFlight`. DEPARTED within the window and not settling answers `Resume`; settling answers `Busy`.

`StopChannel` and `StopPipeline` mark every ARRIVED, ACTIVE or DEPARTED session of that channel (or pipeline) STOPPED with `stoppedAt = now`, **discard** their releases, and return `{ClientID, Connected}` for each that held a client entry (ARRIVED or ACTIVE, not settling). They take only `st.mu`. `StopChannel` delegates to an unexported `stopOwner(Owner)`, which the package's own tests drive with a fake owner; a `*hls.Pipeline` in those tests is `&hls.Pipeline{}`, used only as an identity.

### `relay/channel` additions

`sessions.go` (new):

```go
// StoppedClient is an HLS session's client entry that the session table has
// just marked STOPPED: the caller drops it without a release.
type StoppedClient struct {
	ClientID  string
	Connected bool // client_connect was emitted, so client_disconnect is owed
}

// SessionEnder is the HLS session table as the manager sees it.
type SessionEnder interface{ StopChannel(c *Channel) []StoppedClient }

var ErrChannelAbsent = errors.New("channel: the channel is not running")
var ErrChannelEnding = errors.New("channel: the channel is ending")

// dropHLSClients deletes the entries under c.mu and, after unlocking, emits
// client_disconnect for each Connected one. It never calls Manager.release.
func (c *Channel) dropHLSClients(stopped []StoppedClient)
```

`clientevents.go` (new; the bodies of `relay/httpapi/clientevents.go` move here unchanged so the channel can emit them): `(*Channel).EmitClientConnect(cl *Client)` and `(*Channel).EmitClientDisconnect(cl *Client, at time.Time)`. `httpapi`'s `emitClientConnect`/`emitClientDisconnect` stay as one-line delegations, so no TS or fMP4 call site moves.

`manager.go`:

- `ManagerConfig.Sessions SessionEnder` (nil: no HLS; every existing caller and test keeps working).
- `publish` sets `c.onRunEnd = m.runEnded` when `m.cfg.Sessions != nil`.
- `Stop`: after `take`, `m.endSessions(c)` (`StopChannel` then `c.dropHLSClients`), then `setState`/`stop` as today.
- `stopIfStillIdle`: once it has decided to stop, `m.endSessions(c)` before `setState`/`stop` (only DEPARTED sessions remain there; none holds an entry).
- `func (m *Manager) StopIfIdle(c *Channel)`: `release`'s idle decision without the drop — `Clients() > 0` does nothing; otherwise `stopIfStillIdle` at once or after `ShutdownDelay`.
- `func (m *Manager) EndHLSSessions(c *Channel, stopped []StoppedClient)`: `c.dropHLSClients(stopped)` then `m.StopIfIdle(c)`. Called only off the channel's goroutines (the run-end hook's goroutine, the failure watcher).
- `func (m *Manager) runEnded(c *Channel)`: `stopped := m.cfg.Sessions.StopChannel(c)`; when `len(stopped) > 0`, `m.EndHLSSessions(c, stopped)`.
- `func (m *Manager) AttachExisting(c *Channel, client *Client) (func(), error)`: under `m.mu`, registers `client` only when `m.channels[c.id] == c` and `!c.ring.Closed()`; otherwise, including while a start is in progress, `ErrChannelAbsent`, never a gate and never a start. The release func is `m.release(c, client.ID)`.

`channel.go`: `onRunEnd func(*Channel)` field; `defer c.fireRunEnd()` declared immediately after `defer close(c.done)` in `run` (`relay/channel/channel.go:447-460`); `fireRunEnd` is `if c.onRunEnd != nil { go c.onRunEnd(c) }`.

`hlsoutput.go` (new), with `outputRegistry` gaining `hls map[string]*hlsEntry` and `hlsFailed error`:

```go
// AttachHLS returns the channel's HLS pipeline for key, starting one with
// start if none is registered, and registers the caller against it.
// ErrHLSOutputFailed while the mark is set; ErrChannelEnding once the ring
// has closed. started reports that this call started the pipeline, so the
// caller starts its failure watcher. start runs under outMu and must not
// block (hls.Start returns at once, D9).
func (c *Channel) AttachHLS(key string, start func(src hls.Source) (*hls.Pipeline, error)) (p *hls.Pipeline, started bool, release func(), err error)

// AttachHLSExisting re-attaches a resume to p only while p is key's
// registered pipeline and has not ended.
func (c *Channel) AttachHLSExisting(key string, p *hls.Pipeline) (release func(), ok bool)

// FailHLS sets the mark (err non-nil) and unregisters p if it is still key's.
func (c *Channel) FailHLS(key string, p *hls.Pipeline, err error)

// HLSFailed is the mark's reason, or nil.
func (c *Channel) HLSFailed() error

// HLSStatus is the registered pipeline's engine and generation, for the payload.
func (c *Channel) HLSStatus() (engine string, generation int, ok bool)

type ErrHLSOutputFailed struct{ Reason error } // Unwrap returns Reason
```

The release func captures `p`: under `outMu`, if `c.hls[key]` is an entry whose pipeline is `p`, decrement; at zero delete and `p.Stop()` **after** unlocking. `stopOutputs` stops and clears every HLS entry too. `markBoundary` (`relay/channel/boundary.go:38-49`) clears the mark (`clearHLSFailed`, under `outMu`, after `boundaryMu` is released): the next real source boundary only clears it and starts nothing (R19).

### `relay/httpapi` additions

`hls.go` (new):

```go
const OutputFormatHLS = "hls"

// HLSDeps is the HLS output's process-wide state and its test seams.
type HLSDeps struct {
	Detector *hls.Detector     // process-wide; main.go builds one
	Silence  *hls.SilenceCache // process-wide
	// Test seams, never set by main.go.
	Command      func(hls.Spawn) (string, []string)
	ProbeCommand func(generation int) (string, []string)
	ExitGrace, StallTimeout time.Duration
	ReadyWait, PlaylistWait time.Duration // 0: 20 s (spec § Entry, § Session resources)
}

func serveHLSEntry(w http.ResponseWriter, r *http.Request, deps StreamDeps, ch *channel.Channel, client *channel.Client, release func(), log *slog.Logger)
func HLSHandler(deps StreamDeps) http.HandlerFunc      // the two GET shapes
func HLSLeaveHandler(deps StreamDeps) http.HandlerFunc // DELETE /hls/{token}
func watchHLS(deps StreamDeps, ch *channel.Channel, key string, p *hls.Pipeline)
```

`StreamDeps` gains `Sessions *session.Table`, `HLS HLSDeps` and an unexported `hooks *hlsHooks` (`afterResumeLookup`, `afterResumeAttach func()`: the spec's deterministic seams, set only by tests in the package). `ControlDeps` gains `Sessions *session.Table`.

**Routes** (`relay/httpapi/server.go`, inside the dev-routes gate with the others):

```go
s.mux.Handle("GET /hls/{token}/{file}", HLSHandler(cfg.Stream))
s.mux.Handle("GET /hls/{token}/{rendition}/{file}", HLSHandler(cfg.Stream))
s.mux.Handle("DELETE /hls/{token}", HLSLeaveHandler(cfg.Stream))
```

`GET /hls/{token}/{file}` is strictly more specific than `GET /{username}/{password}/{channelID}` (a literal first segment), so net/http prefers it without a registration conflict; a user literally named `hls` on the bare XC root reaches it and gets 403 (spec D3 records this cost).

**`identify`** accepts `OutputFormatHLS` beside `mpegts` and `fmp4` (`relay/httpapi/stream.go:397-403`), and `ErrUnsupportedOutput.Error` names the three. **`xcForcedFormat`** maps `.m3u8` to `OutputFormatHLS` (`relay/httpapi/xc.go:64-72`).

**`StreamHandler`**: the HLS branch is taken immediately after `Attach` succeeds and **before** `defer release()` (`relay/httpapi/stream.go:231-249`), handing `release` to `serveHLSEntry`, which either stores it in the session or calls it on every failure path. `startTune` is called with `viaProxy = internal || client.OutputFormat == OutputFormatHLS` (Decision 13).

**The entry** (`serveHLSEntry`), in order:

1. `ch.SetClientOutputProfile(client.ID, nil)` (Decision 12).
2. `p, started, releaseOutput, err := ch.AttachHLS("hls", start)` where `start` builds `hls.Config{ChannelID: ch.ID(), Source: src, JoinBehind: ch.Tuning().JoinBehind, Detector, Silence, Log, …seams}` and calls `hls.Start(context.Background(), cfg)`. On `ErrHLSOutputFailed`: `release()`, 502 with the reason's body (Decision 10). On `ErrChannelEnding`: `release()`, 503 `Retry-After: 1`. Any other error: `release()`, 500 `{"error": "Failed to start the HLS output"}`.
3. When `started`: `go watchHLS(deps, ch, "hls", p)`.
4. `sid := control.NewMediaSessionID()`, `token := control.MediaSessionToken(secret, sid)`; `deps.Sessions.Add(&session.Session{ID: sid, Owner: ch, Key: "hls", Pipeline: p, TD: hls.TargetDuration * time.Second}, client, session.Releases{Output: releaseOutput, Client: release})`.
5. `p.Ready(ctx)` with `ReadyWait` (20 s) and the request's context. Deadline: `Abandon`, run what it returned, 503 `Retry-After: 1`. `hls.ErrNoVideo`: `Abandon`, 502 `{"error": "no video stream in the source"}`. `hls.ErrFailed`: `Abandon`, 502 `{"error": "HLS output failed"}`. `hls.ErrStoreClosed` (the pipeline stopped: its channel is ending): `Abandon`, 503 `Retry-After: 1`. The request's own context ended: `Abandon`, return. On every one of these, the releases `Abandon` returns (none when the session was already STOPPED: the stopper dropped the client entry and the pipeline went with its channel) are run before the response. A channel stopped between `Attach` and `Add` never saw the session, so its entry still owns both releases and `Abandon` returns them.
6. `body, err := p.Multivariant("/hls/" + token)`.
7. `deps.Sessions.Activate(sid)`; false (the channel stopped meanwhile, or an admin ended the client) is 503 `Retry-After: 1`.
8. `ch.EmitClientConnect(client)`, then 200, `Content-Type: application/vnd.apple.mpegurl`, `Cache-Control: no-store`, the body. Logged at INFO with the channel and the client id.

**A GET** (`HLSHandler`): verify the token (`403 {"error": "invalid or expired media session"}` on any failure, the one body for every 403); `Begin` (running `Lookup.Depart` and calling `Begin` once more when present); then by outcome — `Unknown` 403, `Gone` 410 `{"error": "channel stopped"}`, `Busy` 503 `Retry-After: 1`, `Resume` (below), `Serve`. Serving (always `defer deps.Sessions.End(sid)`):

- `{rendition}.m3u8`, rendition one of the pipeline's `Output().Renditions()` (else 404): `Store().WaitSegment` bounded by `PlaylistWait` (20 s; deadline or `ErrStoreClosed` is 503 `Retry-After: 1`), then `MediaPlaylist(rendition)`; 200, `application/vnd.apple.mpegurl`, `Cache-Control: no-cache`, `Last-Modified` = the newest segment's publish time in `http.TimeFormat`.
- `{rendition}/init-{gen}.mp4`: `Store().Init(rendition, gen)`, 404 when absent; `video/mp4` for `video`, `audio/mp4` otherwise; `Cache-Control: private, max-age=86400`.
- `{rendition}/{seq}.m4s`: `Store().Segment(rendition, seq)`, 404 when absent; the same types and caching.
- Anything else under a valid token: 404. Every body written feeds `Lookup.Client.Sent(n, now)`, so `bytes_sent` counts HLS bytes.
- The `/hls/` handlers read no `X-Relay-*` and no `X-Dispatcharr-Authorized` header (R13).

**A resume** (spec § Resume never starts a channel, steps 1-3, with Open question 1): `hooks.afterResumeLookup`; `releaseClient, err := deps.Channels.AttachExisting(ch, fresh)` where `fresh` is a copy of the session's client with `ConnectedAt = now` — on `ErrChannelAbsent`, `ResumeFailed`, 410; `releaseOutput, ok := ch.AttachHLSExisting(key, p)` — on false, `releaseClient()`, `ResumeFailed`, 410; `hooks.afterResumeAttach`; `ResumeCommit(sid, fresh, …)` — on false, `releaseOutput()`, `releaseClient()`, 410; else `ch.EmitClientConnect(fresh)` and serve.

**The leave** (`HLSLeaveHandler`): a token failing `VerifyMediaSession` is 403; otherwise `if d := deps.Sessions.Leave(sid); d != nil { d.Run() }`, then 204 — for an unknown sid too (idempotent, spec § Session resources). Decision 7.

**The admin client stop** (`ClientHandler`, `relay/httpapi/control.go`): `if d := deps.Sessions.EndClient(ch, clientID); d != nil { d.Run(); signalled = true }` before `ch.StopClient(clientID)`, and the payload's `locally_processed`/`stop_key_set` report the OR of the two. Stream-limit termination reaches the same route (`apps/proxy/utils.py:143-254`).

**`watchHLS`**: `<-p.Done()`; when `p.Err() != nil`: `ch.FailHLS(key, p, p.Err())`, `stopped := deps.Sessions.StopPipeline(p)`, `deps.Channels.EndHLSSessions(ch, stopped)`. Logged at WARNING with the channel and the reason (the pipeline has already logged its ERROR with the redacted stderr tail).

**Payload** (`relay/httpapi/channels.go`, `relay/httpapi/detail.go`): `HLSEncoder string \`json:"hls_encoder,omitempty"\`` and `HLSGeneration *int \`json:"hls_generation,omitempty"\`` on both, set from `c.HLSStatus()` (the encoder only once it is non-empty). `state` gains no value.

### `relay/hls` change

`StoreSegments` 12 → 21 (R44; `relay/hls/store.go:17-23`), its comment rewritten to give RFC 8216 § 6.2.2's arithmetic: the live edge lists 10 segments (20 s at TD 2), a removed segment must stay available for its own 2 s plus the playlist's 20 s, which is 11 publications after it leaves the list, so the store keeps 10 + 11 = 21; about 46 MB per channel at D8's top rate with AAC and AC-3, under `StoreBytes`' 64 MiB.

### `main.go`

```go
sessions := session.NewTable(session.Config{Log: slog.Default()})
go sessions.Run(context.Background())
channels := channel.NewManager(channel.ManagerConfig{Events: …, Release: …, Sessions: sessions})
…
Stream:  httpapi.StreamDeps{…, Sessions: sessions, HLS: httpapi.HLSDeps{
	Detector: &hls.Detector{Log: slog.Default()},
	Silence:  &hls.SilenceCache{Log: slog.Default()},
}},
Control: httpapi.ControlDeps{Secret: cfg.Secret, Channels: channels, Sessions: sessions},
```

This is what links `relay/hls` (and `relay/session`) into the binary.

### Django

- `apps/proxy/authorize.py:251-256`: `_FORMAT_ALIASES` gains `"hls": "hls"` and `"m3u8": "hls"`.
- `apps/output/views.py:416-418`: `_xc_allowed_output_formats` returns `['ts', 'mp4', 'm3u8']`.
- `apps/output/views.py:224-233` and `:318`: Decision 16.
- `apps/proxy/relay_serializers.py`: `hls_encoder = serializers.CharField(required=False)` and `hls_generation = serializers.IntegerField(required=False)` on `RelayChannelSerializer` and `RelayChannelDetailSerializer` (no `default=`: an absent key stays absent, per the module docstring).
- The capability document: `core/serializers.py` (`RewindWindowCapabilitySerializer`, `LiveHLSCapabilitySerializer`, `MinoCapabilitiesSerializer`), `core/api_views.py` (`MinoCapabilitiesView`, `@extend_schema(responses=MinoCapabilitiesSerializer)`), `core/mino_api_urls.py` (`app_name = "mino"`, `path("capabilities/", …, name="capabilities")`), `apps/api/urls.py` (`path('mino/', include(('core.mino_api_urls', 'mino'), namespace='mino'))`). Body exactly `{"product": "mino", "api_version": 1, "server_version": <version.__version__>, "live_hls": {"available": true, "segment_seconds": 2, "session_leave": true, "rewind_window": {"available": false, "depth_seconds": 0}}}`.

## PR 4a-1b: live HLS end to end

**Files.**

- New: `relay/control/mediasession.go`, `relay/control/mediasession_test.go`; `relay/session/{doc,thresholds,table,departure}.go`, `relay/session/table_test.go`, `relay/session/sweep_test.go`; `relay/channel/{sessions,clientevents,hlsoutput}.go`, `relay/channel/hlsoutput_test.go`, `relay/channel/sessions_test.go`; `relay/httpapi/hls.go`, `relay/httpapi/hls_test.go`; `relay/internal/relaytest/hlsmedia.go` (below) and `relay/internal/relaytest/hlsmedia_test.go`; `core/mino_api_urls.py`, `core/tests/test_mino_capabilities.py`; `apps/proxy/tests/test_hls_format.py`; `apps/output/tests/test_xc_hls_urls.py`; `e2e/fixtures/hls.ts`; `e2e/tests/streaming/hls-entry.spec.ts`, `hls-playlists.spec.ts`, `hls-sessions.spec.ts`, `hls-failover.spec.ts`, `hls-realtime.spec.ts`.
- Changed, relay: `relay/main.go`; `relay/httpapi/{server,stream,xc,control,channels,detail,clientevents}.go`; `relay/channel/{manager,channel,output,boundary}.go`; `relay/hls/store.go`.
- Changed, Django: `apps/proxy/authorize.py`, `apps/proxy/relay_serializers.py`, `apps/output/views.py`, `core/api_views.py`, `core/serializers.py`, `apps/api/urls.py`.
- Changed by Appendix A (apply it; do not rewrite it): `CLAUDE.md`, `README.md`, `docker/nginx.conf`, `docker/dispatcharr_api_params_proxy.conf`, `docker/docker-compose{,.aio,.dev}.yml`, `docs/relay-parity-matrix.md` (fill the `⟨…⟩` slots), `e2e/COVERAGE.md` (fill the one observation row's slots), `e2e/fixtures/types.ts`, `e2e/tests/guards/parity-matrix.ts`, `e2e/tests/streaming-greybox/nginx-stream-buffering.spec.ts`.
- Changed by the census (§ Coverage): `scripts/coverage_relay_go.floor`, `scripts/coverage_relay_go.floor.packages`.
- Changed tests: § Tests changed.

`relay/internal/relaytest/hlsmedia.go` gives the `httpapi` and `channel` tests synthetic encoder output the real `relay/hls` parses: `HLSVideoStream(fragments, framesPerFragment int) []byte` (a 12800 Hz H.264 init with an `avcC` for `avc1.64002a` and whole fragments each opening on a sync sample), `HLSAACStream(fragments int) []byte` (a 48 kHz AAC-LC init and 200 ms fragments of 1024-sample frames) and `HLSProbeJSON(video, audio bool) []byte` (an ffprobe `-show_streams -of json` answer: 640×360 progressive H.264 at 25/1 and, when asked, one qualifying AAC stereo stream). They are **copied** from `relay/hls/helpers_test.go`'s `initSpec`, `fragSpec`, `videoStream` and `audioStream` (not moved: the `relay/hls` tests are untouched), and `hlsmedia_test.go` (package `relaytest_test`) asserts that `hls.ParseInit` and `hls.ParseFragment` accept every one and that the codec string is `avc1.64002a`/`mp4a.40.2`. The stand-in (`relaytest.StandInCommand` with `--fd-file 1=…`, `--fd-file 3=…`, `--wait-stdin-eof` or `--ignore-stdin-eof`, `--exit-code`, `--spawn-log`; 4a-1a's flags) plays the encoder and the probe through `HLSDeps.Command` and `HLSDeps.ProbeCommand`; the detector is `&hls.Detector{Device: "/nonexistent"}` (software, spawning nothing).

**Tasks.** Run every command from the implementation worktree (`worktree-per-change`), anchored with an absolute path or a leading `cd`. `SEED=fabc663a9c27cfc317fe52f32a95c5f992d3ef0e`.

1. **Pre-flight.** `set -o pipefail; git diff --stat "${SEED}" origin/main -- relay apps/proxy/authorize.py apps/proxy/relay_serializers.py apps/output/views.py core apps/api/urls.py docker e2e/tests/guards e2e/tests/streaming e2e/tests/streaming-greybox e2e/fixtures e2e/COVERAGE.md docs/relay-parity-matrix.md CLAUDE.md README.md scripts/coverage_relay_go.floor scripts/coverage_relay_go.floor.packages` prints nothing (stderr kept; a non-zero exit is a stop). If main has moved any of those paths, stop and report: Appendix A and every anchor here are against the seed.
2. **Apply Appendix A.** `awk '/^<!-- appendix-A-begin -->$/{f=1; next} /^<!-- appendix-A-end -->$/{f=0} f' docs/superpowers/plans/2026-09-28-phase4-4a1b-live-hls.md | sed '1d;$d' > "$SCRATCH/4a1b-docs.diff" && git apply --whitespace=error "$SCRATCH/4a1b-docs.diff"` (from the plan at its merged SHA; `$SCRATCH` is your session scratchpad). `git diff --stat` shows the twelve files of § Files' Appendix-A bullet. The parity rows' and the COVERAGE row's `⟨…⟩` slots are filled in Task 12, once the code exists.
3. **The token** (`relay/control/mediasession.go`) with its tests; `go test -race ./control`.
4. **`relay/channel`**: the client-event move, `sessions.go`, the manager changes, `fireRunEnd`, `hlsoutput.go` and the mark's clearing in `markBoundary`, with their tests; `go test -race ./channel` (and the whole module: `channel` is imported everywhere).
5. **`relay/session`** with its tests; `go test -race ./session`.
6. **`relay/httpapi`**: `identify`, `xcForcedFormat`, the HLS branch, `hls.go`, the routes, the client stop, the payload fields, `startTune`'s `viaProxy`; the rig change (§ Tests changed); `relaytest/hlsmedia.go`; `hls_test.go`; `go test -race ./httpapi ./internal/relaytest`.
7. **`relay/hls/store.go`** (R44) and the store test changes; `go test -race ./hls`.
8. **`main.go`** wiring. `cd relay && go list -deps . | grep -E 'relay/(hls|session)$'` prints both.
9. **The whole relay gate**: `cd relay && go build ./... && go vet ./...`; `golangci-lint run ./...`, `GOOS=linux golangci-lint run ./...`, `GOOS=darwin golangci-lint run ./...` (`0 issues.` each); from the repo root `scripts/check_go_stdlib_only.sh relay` and `scripts/check_go_credential_logging.sh relay` (`credlint: 14 package(s) clean`, one more than the seed's 13); `cd relay && go test -count=1 -race ./...`. The eleven `relay/hls` real tests skip locally without ffmpeg and fail under `CI` without it; say which happened.
10. **Django.** The four source changes, the golden fixtures and goldens (§ Tests changed; regenerate with `DISPATCHARR_WRITE_GOLDEN=1` exactly as each golden module's docstring says, and read the diff: it must add the two keys and nothing else), and the three new test modules. Run the labels `apps.proxy.tests`, `apps.output.tests` and `core.tests` in the test container, re-pointed at this worktree first (`cd <worktree> && .claude/hooks/start-test-container.sh`), once fresh without `--keepdb`. Then **the Python Gate 2 isolated run** (`scripts/coverage_live_path_isolated.sh`): `missing` stays 33, because `authorize.py` and `relay_serializers.py` are Gate 2 modules (spec § Testing and gates; memory of #312's lesson: a green label does not imply a green gate). The schema test proves the route is in drf-spectacular's schema.
11. **E2E, static.** `cd e2e && npm ci && npx tsc --noEmit -p . && npx playwright test --project=guards`. The parity guard passes only after Task 12. **Do not start a local stack or the shared provider**: the `streaming` and `streaming-greybox` projects run on the PR's CI (the `migration/` branch runs every project).
12. **Fill the slots.** Each parity row's `⟨…⟩` becomes `path:start-end` of the named declaration as `grep -n` prints it at the implementation's final head (the guard checks each resolves: `every row cites source that resolves`). Re-run the guards.
13. **Break-checks** (§ Break-checks): each applied alone, run, the message compared with the one recorded there, reverted; `git diff --stat` afterwards is unchanged. BC3 (nginx) and the E2E halves of BC1, BC2 and BC4 run on CI only, from a throwaway commit on a scratch branch `migration/phase4-4a1b-bc` pushed, observed red and deleted (never on the PR branch).
14. **AVPlayer** (§ AVPlayer).
15. **Push and open the PR as a draft** (`implement-review-escalate`), branch `migration/phase4-4a1b-live-hls`, with the description below. No closing keyword and no `Refs` anywhere.
16. **The census and the floor** (§ Coverage). Detach the census loop and watch its stopfile (a long CI loop stalls an attached subagent).
17. **Fill the measurement slots** (Q6, R29) from the PR's green `streaming` runs (§ E2E measurements), in the COVERAGE row and the PR body.

### Tests added

"Stand-in" tests spawn the re-executed test binary through `relay/internal/relaytest` with `relaytest.HLSVideoStream`/`HLSAACStream`/`HLSProbeJSON` output; the subject is the relay's reaction. No new Go test spawns ffmpeg: the real encoder is `relay/hls/real_test.go`'s (4a-1a) and the E2E's.

| File | Test | Pins |
|---|---|---|
| `relay/control/mediasession_test.go` | `TestAMediaSessionTokenHasTheSpecsShape` | 69 characters, `v1.<22>.<43>`; the MAC recomputed in the test with `crypto/hmac` over the literal `media-session\nv1\n<sid>` (the oracle is the stdlib, never the code under test) |
| | `TestAMediaSessionTokenIsRefusedWhenForgedOrTampered` | row 38: `v2`, one MAC character flipped, another secret's MAC, a changed sid, a fourth segment, a non-ASCII byte, padding `=`, empty, over-long parts: every one `ok == false`; the genuine token verifies |
| | `TestNewMediaSessionIDsAreDistinctAnd128Bit` | 1,000 ids distinct, each decoding to 16 bytes |
| `relay/session/table_test.go` | `TestAnEntryIsInFlightUntilActivated` | ARRIVED holds `inFlight` 1; no sweep departs it at any age; `Activate` makes it ACTIVE with `lastEnd` = now |
| | `TestAnIdleSessionDepartsAfterTheIdleTimeoutAndNotBefore` | row 39: at `lastEnd` + 11.999 s nothing; at + 12 s one departure, whose `Run` emits `client_disconnect` once and calls Output then Client exactly once, in that order |
| | `TestARequestInFlightHoldsASessionActive` | row 39, spec § Session states' activity rule: a request begun at t and ended at t + 60 s departs at t + 72 s, never at t + 12 s |
| | `TestTheIdleTimeoutScalesWithTheTargetDuration` | `IdleTimeout(2 s)` 12 s, `IdleTimeout(6 s)` 36 s; a TD 6 s session is not departed at 35 s (4a-1d's case, held now) |
| | `TestALeaveRemovesTheSessionAndReturnsItsReleasesOnce` | a second `Leave` returns nil; `Begin` afterwards is `Unknown` |
| | `TestADepartedSessionIsResumableForThreeHundredSeconds` | `Resume` at + 299 s, `Unknown` and removed at + 301 s |
| | `TestASettlingDepartureIsBusyNotResumable` | Decision 5 |
| | `TestStopChannelMarksOnlyThatChannelsSessions` | ARRIVED, ACTIVE and DEPARTED of channel 1 STOPPED; channel 2 untouched; the returned clients are the ARRIVED and ACTIVE ones with their `Connected`; no release called |
| | `TestAStoppedSessionIs410OnceThenForgotten` | `Gone` then `Unknown`; a STOPPED session unrequested for 300 s is removed by a sweep |
| | `TestEndClientEndsOnlyThatClientsLiveSession` | a DEPARTED session with the same client id is left alone |
| | `TestResumeCommitNeedsTheSessionStillDeparted` | a session STOPPED between lookup and commit refuses the commit |
| `relay/session/sweep_test.go` | `TestTheSweeperDepartsOnItsTicks` | `Run` driven by `Config.Tick`: a departure per idle session, removals of expired ones |
| | `TestASlowDepartureDoesNotDelayTheNextTick` | Open question 3: a departure whose Client release blocks does not stop the next tick departing another session |
| `relay/channel/sessions_test.go` | `TestAttachExistingNeverStartsAChannel` | row 41: absent, starting, closed-ring and restarted-under-the-same-id channels all `ErrChannelAbsent` with no start; the channel itself registers the client |
| | `TestStopIfIdleHonoursTheShutdownDelayAndLeavesAWatchedChannel` | a TS client keeps the channel; with none it is removed at once, or after `ShutdownDelay` |
| | `TestDroppingHLSClientsEmitsDisconnectOnlyForConnectedOnes` | Decision 6 |
| | `TestAManagerStopMarksTheSessionsBeforeTheChannelStops` | the `SessionEnder` fake records `StopChannel` before the source's context is cancelled |
| `relay/channel/hlsoutput_test.go` | `TestOneHLSPipelinePerKeyStopsAtZero` | refcount sharing; the last release stops it after `outMu` is released |
| | `TestAStaleHLSReleaseCannotStopAFreshPipeline` | Decision 3: p1 failed and unregistered, p2 registered; p1's release leaves p2 running |
| | `TestTheMarkRefusesUntilTheNextBoundaryAndTheBoundaryStartsNothing` | row 44 at the channel: `AttachHLS` answers `ErrHLSOutputFailed{Reason}` while marked; `markBoundary` clears it and no start func is called |
| | `TestAttachHLSRefusesAnEndingChannel` | Decision 11 |
| `relay/httpapi/hls_test.go` | `TestAnHLSTuneAnswersAMultivariantPlaylistRatherThanBytes` | row 37: 200, content type, `no-store`, `#EXTM3U`, `EXT-X-STREAM-INF`, URIs `/hls/<token>/video.m3u8` whose token verifies; the client listed with `output_format` `hls` and `output_profile_id` null although `X-Relay-Output: 3` was sent (Decision 12); one `client_connect` |
| | `TestAnXCM3U8URLForcesHLSOnBothRoots` | row 37: `/live/u/p/12.m3u8` and `/u/p/12.m3u8` with the hop's `X-Relay-Output-Format: mpegts` still answer the multivariant |
| | `TestAnEntryWhoseInitsNeverArriveIs503AndLeavesNoClient` | row 37: a stand-in that writes nothing and ignores EOF, `ReadyWait` 300 ms: 503 `Retry-After: 1`; no client, no session, the lone channel stopped |
| | `TestANoVideoProbeIs502AndTheTSClientIsUnaffected` | § Entry: an audio-only probe answer; 502 `{"error": "no video stream in the source"}`; a TS client keeps receiving bytes; a second entry also 502s (Open question 2's mark) |
| | `TestAMediaPlaylistWaitsForItsFirstSegmentAndCarriesItsHeaders` | row 43: `no-cache`, a parseable `Last-Modified`; with an init-only stand-in and `PlaylistWait` 300 ms, 503 `Retry-After: 1`; init and segment content types and caching; 404 for an undeclared rendition, an unknown file, a sequence outside the store; `bytes_sent` grows by what was served |
| | `TestTheHLSRoutesIgnoreTheTrustHeaders` | R13: a GET carrying a valid `X-Dispatcharr-Authorized` and another channel's `X-Relay-Channel` is served from its session's own pipeline |
| | `TestALeaveEndsTheSessionAtOnceAndIsIdempotent` | row 39, Decision 7: two sessions; the moment `DELETE` returns 204 the registry lists only B's client; `client_disconnect` with `duration` and `bytes_sent`; A's GET 403; a second `DELETE` 204; an unknown sid with a valid MAC 204; a tampered token 403 |
| | `TestAStoppedSessionIs410OnceThen403AndADeleteIs204` | row 38, the spec's STOPPED test: after the internal channel DELETE, a GET gets 410 `{"error": "channel stopped"}` within 1 s of `Manager.Stop` returning, then 403; the other session's `DELETE` 204 |
| | `TestAnAdminClientStopEndsAnHLSSession` | row 39: the internal client DELETE reports `locally_processed: true`; the GET is 403; `client_disconnect` |
| | `TestARejectedTokensTextNeverReachesTheLog` | Global constraint 2: forged tokens (each carrying a unique marker) on a GET and a DELETE, and a valid session's own requests: the captured log contains neither any token nor the sid |
| | `TestSelfStopRunEnded` | row 40, the spec's case (i) and **the break-check's oracle**: two sessions attached, every source exhausted (`relaytest.Config{StopAfterBytes: …}`, `MAX_RETRIES` 1): both STOPPED, the channel removed from the map, and its `Done()` closed, all within 1 s of the run ending; the captured log carries no `source goroutine did not return in time` |
| | `TestSelfStopHLSFailedWithNoOtherClient` | row 40, case (ii): every generation attempt exits early; both sessions STOPPED; the channel stopped and removed within 1 s; the control-plane stub records the release POST |
| | `TestSelfStopHLSFailedWithATSClient` | row 40, case (iii): the sessions STOPPED; the channel stays in the map and the TS client keeps receiving bytes |
| | `TestAnAdminChannelStopEndsItsHLSSessions` | row 40: `Manager.Stop` path; `client_disconnect` for each connected session |
| | `TestAFailedHLSOutputRefusesEntriesUntilTheNextBoundaryAndStartsNothingThere` | row 44, the spec's failure-and-recovery test: a TS client and a session; the stand-in fails every attempt until a flag the test sets; the session gets 410 once; a new entry 502; the spawn log records no spawn while marked; an operator advance (the internal `POST …/advance`) clears the mark and the spawn log still records none; the next entry answers 200 and starts generation 0 of a fresh pipeline |
| | `TestAResumeNeverStartsAChannel` | row 41, the spec's first resume case: a TS client holds the channel, the session departs (driven ticks), `afterResumeLookup` stops the channel; the GET answers 410, the stub records exactly one next-source call, the table holds no entry for the sid |
| | `TestAResumeThatLosesTheRaceToAStopReleasesItsAttachment` | row 41, the spec's second case: `afterResumeAttach` stops the channel; the GET answers 410 and the stopped channel's `ClientSnapshot` no longer lists the resumed client |
| | `TestADepartedSessionResumesOnItsRunningPipeline` | row 41: sessions A and B and a TS client; A departs, B keeps requesting; A's next GET is 200 with a second `client_connect` and A ACTIVE again |
| | `TestAResumeOnAStoppedPipelineIs410` | Open question 1: A departs, B leaves (refcount 0, the pipeline stops), the TS client keeps the channel: A's GET is 410 |
| | `TestARedirectChannelIsServedOverHLSAsProxy` | row 42: `Kind: redirect`; a TS tune while the channel is not running gets its 302; an `hls` tune gets 200 and the upstream records the relay's own request; a TS tune while it runs attaches and gets bytes |
| | `TestTheSweeperIsProcessWideAndOutlivesItsChannel` | the spec's sweeper test: a lone viewer departs, the pipeline and the channel stop; after 300 s plus one driven tick the table is empty |
| | `TestTheChannelPayloadCarriesTheHLSEncoderAndGeneration` | list and detail payloads: `hls_encoder` `software` and `hls_generation` 0 while the pipeline runs; both absent on a TS-only channel |
| `relay/httpapi/detail_golden_test.go` | `TestTheDetailPayloadOmitsTheHLSFieldsWithoutAPipeline` | the two keys vanish when unset and render when set, as the DVR-field test does for its three |
| `relay/hls/store_test.go` | `TestARemovedSegmentStaysAvailableForItsDurationPlusThePlaylists` | row 43, R44: publishing at 2 s intervals, every segment that leaves the 10-segment list is still in the store 22 s (11 publications) later |
| `relay/internal/relaytest/hlsmedia_test.go` | `TestTheSyntheticHLSMediaParses` | the builders produce what `relay/hls` accepts |
| `apps/proxy/tests/test_hls_format.py` | `ResolveOutputFormatHLSTests` (`test_hls_and_m3u8_resolve_to_hls`, `test_the_hop_answers_hls_for_an_hls_tune`) | D2: `?output_format=hls`, `?output=m3u8` resolve to `hls`; the authorize view's `X-Relay-Output-Format` for `/proxy/ts/stream/<uuid>?output_format=hls` is `hls` |
| `apps/output/tests/test_xc_hls_urls.py` | `XCHLSURLTests` (`test_player_api_advertises_m3u8`, `test_get_php_output_m3u8_emits_m3u8_urls`, `test_get_php_output_hls_emits_m3u8_urls`, `test_the_output_profile_is_kept_and_output_format_dropped`, `test_output_ts_is_unchanged`, `test_a_non_xc_request_keeps_the_query`) | R9, Decision 16 |
| `core/tests/test_mino_capabilities.py` | `MinoCapabilitiesTests` (`test_answers_anonymously_with_the_documented_body`, `test_a_stale_bearer_header_is_not_a_401`, `test_the_xc_api_acl_refuses_with_403`, `test_the_route_is_in_the_schema`) | D19, Decision 15 |

**E2E** (project `streaming`, e2e-upstream 1.3.0's assets, `rate: 1`, every channel on the locked Proxy profile unless stated; every test ends by `DELETE`ing the sessions it opened; timeouts generous and never gates; `e2e/fixtures/hls.ts` holds the parsers: `parseMultivariant`, `parseMediaPlaylist`, `topLevelBoxes`, `initSummary` (handler, timescale, whether `edts` is present) and `fragmentTiming` (`tfdt` and the `trun` durations, falling back to `tfhd` and the init's `trex` defaults), plus `MEDIA_SESSION_TOKEN_RE = /^v1\.[A-Za-z0-9_-]{22}\.[A-Za-z0-9_-]{43}$/`):

| Spec | Test (tag) | Asserts |
|---|---|---|
| `hls-entry.spec.ts` | `an hls tune answers a multivariant playlist on all three entry forms` (`@contract`) | `/proxy/ts/stream/<uuid>?output_format=hls`, `/live/<u>/<p>/<id>.m3u8` and `/<u>/<p>/<id>.m3u8` (a `seed.xcUser({user_level: 1})`): 200, `application/vnd.apple.mpegurl`, `no-store`, `EXT-X-STREAM-INF`, every URI `/hls/<token>/…` with the token matching the pattern; the channel status lists `hls` clients |
| | `a Redirect-profile channel is served over HLS through the relay` (`@contract`) | the locked Redirect profile: the multivariant is served and the provider's log shows the relay's own connection |
| | `the Xtream API advertises m3u8 and get.php emits .m3u8 stream URLs` (`@contract`) | `player_api.php`'s `allowed_output_formats` contains `m3u8`; `get.php?…&output=m3u8` lists `/live/<u>/<p>/<id>.m3u8` with no `output_format` |
| | `the Mino capability document answers anonymously` (`@contract`) | the documented body, with no credential |
| `hls-playlists.spec.ts` | `the multivariant declares the audio groups and codecs of each fixture` (`@contract`) | `h264-eac3`: groups `aac`, `ac3`, `eac3`, CODECS `avc1.64002a` with `mp4a.40.2`, `ac-3`, `ec-3`; `h264-noaudio`: one `aac` group; `mpeg2-576i-mp2`: `RESOLUTION=720x576`, `FRAME-RATE=50.000`, one `aac` group; `h264-1080i-aac-ac3`: `RESOLUTION=1920x1080`, `FRAME-RATE=50.000`, groups `aac` and `ac3` (`CHANNELS="6"`). One channel per fixture, the four run in series |
| | `a media playlist conforms and its init and segments parse` (`@contract`) | row 43 on `h264-eac3`: `VERSION:7`, `TARGETDURATION:2`, `INDEPENDENT-SEGMENTS`, PDT on every segment, at least 6 listed within 60 s, no `ENDLIST`, the media sequence advancing between two reloads with no gap; the video init has a `moov` and no `edts`; two consecutive media segments are `moof`+`mdat`, each `tfdt` continuing the previous, each duration within one frame of its `EXTINF`; the `aac` playlist lists the same sequence numbers |
| `hls-sessions.spec.ts` | `a tampered token, a left session and a stopped client are refused` (`@contract`) | row 38: one flipped MAC character is 403; after `DELETE /hls/<token>` (204) its GET is 403; after `POST /proxy/ts/stop_client/<uuid>` with the session's client id its GET is 403 |
| | `a session on a stopped channel is refused 410 once and 403 after` (`@contract`) | `POST /proxy/ts/stop/<uuid>`: 410, then 403 |
| | `an hls client is listed while it plays and leaves at once on DELETE` (`@contract`) | row 39: a TS client and an HLS session on one channel; the status lists both; after the 204, the very next status read lists the TS client only (no wait for the idle timeout, R24) |
| `hls-failover.spec.ts` | `a failover to a different asset starts a new generation behind EXT-X-DISCONTINUITY` (`@contract`) | row 32's E2E pin: channel streams `h264-1080i-aac-ac3` (1) then `mpeg2-576i-mp2` (2); `not-found` then `disconnect` armed on 1 once the session plays; within 90 s the status names stream 2 and the video playlist lists `EXT-X-DISCONTINUITY` then a new `EXT-X-MAP` (`init-1.mp4`), the media sequence continuing and the multivariant's `CODECS` unchanged on a fresh entry. Records the Q6 gap (§ E2E measurements) as the annotation `q6-failover-gap-seconds` |
| `hls-realtime.spec.ts` | `the software transcode of the 1080i fixture is measured against real time` (`@characterization`) | R29: records `r29-1080i-realtime-ratio` (§ E2E measurements); asserts only that segments appear |

The nginx greybox fifth test is Appendix A's (`streaming-greybox`).

### E2E measurements (Q6, R29) — recorded, never asserted

- **Q6, the failover gap.** From the first status poll (every 250 ms) whose `stream_id` is the alternate's, to the first video-playlist poll (every 250 ms) that lists a segment after an `EXT-X-DISCONTINUITY`. The resolution is the poll interval; the annotation and one `console.log` line carry the seconds to two places. It is an upper bound on "boundary to the new generation's first segment" by the time the relay spent retrying the first URL before switching, which the log line also reports (the fault time to the status flip).
- **R29, real time.** Once the 1080i channel's first segment is listed, poll its video playlist every second for 40 s; the ratio is the sum of the `EXTINF` of the newly listed segments over 40 s of wall clock. The `streaming` project runs two workers, so the figure is taken under whatever the other worker runs, and the log line says so.
- Both land in the PR body and in COVERAGE's observation row, with the CI run id. A ratio below 1.0 is a finding (Open question 5), never a lowered assertion.

### Tests changed

Each is a change to a test whose pinned behaviour this PR changes, or a support edit that changes no assertion.

| Test | Before | After | Why |
|---|---|---|---|
| `relay/httpapi/fanout_test.go:451` `TestAnOutputThisRelayDoesNotServeIsRefused` | row `{"an output format it does not serve", "X-Relay-Output-Format", "hls", 501}` | `"dash"`, and the comment above it says why (`hls` is served since 4a-1b; `dash` is a format neither relay ever had) | `hls` is now served (D2) |
| `relay/hls/store_test.go:121-129` `TestTheStoreIsBoundedAndServesBySequence` | `publishN(s, 1, 13, t0)`; message `"… past the 12-segment bound"` | `publishN(s, 1, StoreSegments+1, t0)`; message `"… past the StoreSegments bound"` | R44 changes the bound it pins; the assertions (segment 1 evicted, 2 kept, generation 0's init evicted) are unchanged |
| `relay/hls/store_test.go:112` and `:209-215` (comments only) | "everything but generation 2 leaves the store"; "StoreSegments = LiveEdge + 2 … which the thread's reply puts to a ruling" | "…leaves the list"; "StoreSegments = LiveEdge + 11, R44" | comments that R44 makes false; no assertion |
| `relay/httpapi/golden_test.go` `goldenPayload()` | the populated channel sets neither HLS field | sets `HLSEncoder: "software"`, `HLSGeneration: ptr(3)` | the payload gains two optional fields (spec § Relay channel payload additions) |
| `relay/httpapi/golden_test.go` `TestEveryOptionalFieldIsAbsentRatherThanNull` | the minimal channel's absent-key list | the list plus `hls_encoder`, `hls_generation` | the same |
| `relay/httpapi/golden_test.go` `TestTheLiveEndpointProducesTheGoldensKeySet` | `want = keysOf(golden.Channels[0])` | `want` = that set minus `hls_encoder` and `hls_generation`, with a comment: a TS-only transcode tune runs no HLS pipeline, and `TestTheChannelPayloadCarriesTheHLSEncoderAndGeneration` pins the HLS channel's two keys | the golden's populated channel now carries keys a TS tune never has |
| `relay/httpapi/detail_golden_test.go` `detailGoldenPayload()` | neither field | both set as above | the same |
| `relay/httpapi/testdata/channels_clients_all.json`, `channel_detail.json` | — | regenerated by the Python goldens (never by the Go) | the same |
| `apps/proxy/tests/test_relay_list_payload_golden.py`, `test_relay_detail_payload_golden.py` `fixture()` | — | the populated channel gains `"hls_encoder": "software", "hls_generation": 3` | `test_the_fixture_covers_every_serializer_field` requires every declared field |
| `relay/httpapi/stream_test.go` `newRigWithClient` (support) | builds the manager and the server with no session table | builds a `session.Table` with a test-driven `Tick`, passes it to `ManagerConfig.Sessions`, `StreamDeps.Sessions` and `ControlDeps.Sessions`, starts its `Run`, and exposes it and its tick channel on `rig` | no assertion changes; every existing test runs with the table present and empty |

### Break-checks

Each wrong edit is applied alone, the named test run (`cd relay && go test -count=1 -race -run '<test>' ./<pkg>`, or the named Django label, or CI for the E2E), the red message compared with the one described (the implementer records the literal line in the PR body), and the edit reverted. BC1-BC9 are the spec's (§ 4a-1b); BC10-BC22 are this plan's.

- **BC1 — look up the session without verifying the MAC** (spec). `relay/control/mediasession.go`, `VerifyMediaSession`: return `sid, true` in place of the `hmac.Equal` result. `TestAMediaSessionTokenIsRefusedWhenForgedOrTampered` reddens naming the tampered case ("a token whose MAC was tampered verified"); on CI the E2E `a tampered token, a left session and a stopped client are refused` reddens with 200 where 403 is expected.
- **BC2 — `DELETE` answers 204 without ending the session** (spec). `HLSLeaveHandler`: delete the `Leave` call. `TestALeaveEndsTheSessionAtOnceAndIsIdempotent` reddens: the registry still lists A's client after the 204; on CI the post-leave E2E reddens (200 where 403).
- **BC3 — `auth_request` on `^~ /hls/`** (spec). Add `auth_request /_dispatcharr/authorize;` to the location in `docker/nginx.conf`. On CI the greybox fifth test reddens: `location "location ^~ /hls/ {" must not run the authorize subrequest`.
- **BC4 — the client stop no longer ends the session** (spec). `ClientHandler`: delete the `EndClient` branch. `TestAnAdminClientStopEndsAnHLSSession` reddens (`locally_processed` false and the GET 200); on CI the revoke E2E reddens.
- **BC5 — the run-ended self-stop runs synchronously on the channel's goroutine** (spec). `relay/channel/channel.go`, `fireRunEnd`: `go c.onRunEnd(c)` → `c.onRunEnd(c)`. `TestSelfStopRunEnded` reddens: `Done()` closes about 5 s after the sessions went STOPPED, not within 1 s, and the log carries `source goroutine did not return in time` — the stop waiting on its own `done`, which names the mechanism. Cases (ii) and (iii) are coverage only (spec).
- **BC6 — start a generation at the boundary instead of only clearing the mark** (spec). `watchHLS`, after `FailHLS`: wait until `ch.HLSFailed()` is nil, then call `ch.AttachHLS("hls", start)` and keep the reference. `TestAFailedHLSOutputRefusesEntriesUntilTheNextBoundaryAndStartsNothingThere` reddens: the spawn log records a spawn after the advance with no session attached.
- **BC7 — drop the sessions without the idle decision** (spec). `Manager.EndHLSSessions`: delete `m.StopIfIdle(c)`. `TestSelfStopRunEnded` reddens (the channel is still in the manager's map 1 s after its run ended) and `TestSelfStopHLSFailedWithNoOtherClient` reddens (still in the map, and the stub records no release POST: the slot is held with zero clients).
- **BC8 — resume through the starting `Attach`** (spec). `resume`: `deps.Channels.AttachExisting(ch, fresh)` → `deps.Channels.Attach(ch.ID(), fresh, func() (channel.Started, error) { return startTune(r.Context(), tuneDeps{…}, ch.ID(), false) })`. `TestAResumeNeverStartsAChannel` reddens: the stub records a second next-source call (the fresh channel is not the session's, so the GET itself still ends 410 at `AttachHLSExisting`; the second call is the mechanism and the oracle).
- **BC9 — run the idle sweep per pipeline** (spec). Delete the rig's (and `main.go`'s) `go sessions.Run(…)`, and in `serveHLSEntry` start `go deps.Sessions.Run(ctx)` with a context cancelled when the pipeline's `Done()` closes. `TestTheSweeperIsProcessWideAndOutlivesItsChannel` reddens: the entry is never removed.
- **BC10 — R44 undone.** `StoreSegments = 20`. `TestARemovedSegmentStaysAvailableForItsDurationPlusThePlaylists` reddens naming the segment evicted 20 s after it left the list, want 22 s.
- **BC11 — no `client_disconnect` for a STOPPED session.** `dropHLSClients`: skip the emit. `TestAnAdminChannelStopEndsItsHLSSessions` and `TestDroppingHLSClientsEmitsDisconnectOnlyForConnectedOnes` redden.
- **BC12 — idle measured from arrival.** `Sweep`: compare the request's begin time instead of `lastEnd` (and ignore `inFlight`). `TestARequestInFlightHoldsASessionActive` reddens: departed at t + 12 s with a request in flight.
- **BC13 — resume by id.** `AttachExisting`: `m.channels[c.id] != nil` instead of `== c`. `TestAttachExistingNeverStartsAChannel`'s restarted-channel case reddens.
- **BC14 — the token reaches the log.** Log `"token", token` in the GET handler's 403 path. `TestARejectedTokensTextNeverReachesTheLog` reddens, naming the marker it found.
- **BC15 — Redirect keeps its 302 on HLS.** `startTune` called with `internal` alone. `TestARedirectChannelIsServedOverHLSAsProxy` reddens: 302 where 200.
- **BC16 — `X-Relay-Output` honoured on HLS.** Delete `SetClientOutputProfile(client.ID, nil)`. `TestAnHLSTuneAnswersAMultivariantPlaylistRatherThanBytes` reddens: `output_profile_id` 3, want null.
- **BC17 — an identity-blind HLS release.** The release func decrements `c.hls[key]` without comparing its pipeline to `p`. `TestAStaleHLSReleaseCannotStopAFreshPipeline` reddens.
- **BC18 — the mark survives the boundary.** Delete `clearHLSFailed` from `markBoundary`. `TestTheMarkRefusesUntilTheNextBoundaryAndTheBoundaryStartsNothing` and the httpapi recovery test redden (502 after the advance).
- **BC19 — a settling departure is resumable.** `Begin`: ignore `settling`. `TestASettlingDepartureIsBusyNotResumable` reddens.
- **BC20 — the leave answers before its side effects.** `HLSLeaveHandler`: `go d.Run()`. `TestALeaveEndsTheSessionAtOnceAndIsIdempotent` reddens (A's client still listed when the 204 arrives), made deterministic by a Client release the test holds until after the 204 is read.
- **BC21 — the capability document runs the authenticators.** Delete `authentication_classes = []`. `test_a_stale_bearer_header_is_not_a_401` reddens with 401.
- **BC22 — `get.php` keeps `output_format`.** Leave `output_format` in the XC query for `m3u8`. `test_get_php_output_m3u8_emits_m3u8_urls` reddens naming the URL.

### Coverage (R21, R27, R34)

The Go gate (`scripts/coverage_relay_go.sh --gate` in `go-tests.yml`'s `Coverage gate` job) refuses the first push: the linked package set changed (`relay/hls` and `relay/session` join; `package_count` 10 → 12). That refusal prints no `missing`. The procedure is the floor file's own ("HOW TO MOVE", steps 1-5), in this order:

1. **Re-baseline the shape.** Download the first green `build` job's `relay-go-coverage` artifact (`gh run download <id> --repo D10Scot/Dispatcharr -n relay-go-coverage -D "$SCRATCH/cov-1"`), run `scripts/coverage_relay_go.sh --write-floor "$SCRATCH/cov-1"` from the worktree (it rewrites the floor and `scripts/coverage_relay_go.floor.packages`), then **hand-set `missing=589`, `percent`, `measured` and `runs` back to the seed's values** and commit (message: "floor: re-baseline packages for relay/hls and relay/session; missing unchanged pending the census"). The gate now fails only on `missing`, and prints `this run missing=` every round.
2. **The census.** Dispatch `go-tests.yml` on the branch one run at a time (its concurrency group cancels an in-flight run on the same ref), at least twelve times, until the maximum has held for six consecutive rounds, and record every round's `this run missing=` in order. A round counts when its `build` job succeeded, whatever the `Coverage gate` job said. From each round's artifact compute, with the floor file's `awk` over the coverprofile: (a) `relay/hls`'s uncovered statements per file; (b) the uncovered blocks in 4a-1b's own new or changed code — the blocks whose start line falls in an added range of `git diff -U0 "${SEED}" -- relay ':!*_test.go' ':!relay/internal'` (every line of a new file is added); (c) any other uncovered block not in 4a-1a's census artifacts at `f44c8135` (the orchestrator's `scratchpad/phase4/census-4a1a-f44c/r*`): a pre-existing flap, recorded, never counted.
3. **The two amounts.** `H` = the sum over `relay/hls`'s files of each file's maximum across the rounds (4a-1a's census gave box 8, detect 1, fragment 3, init 31, pipeline 25, reader 1, segmenter 6, silence 14 = 89; a file that moves by more than one statement from that is attributed block by block before going on). `O` = the sum over 4a-1b's files of each file's maximum of (b). Coverage on additions = 1 − (maximum uncovered in (b)) / (added statements) and must be **≥ 85%**; below it, add tests, never lower the bar.
4. **The floor.** `missing = 589 + H + O`; `percent = (1 − missing / statements) × 100` with this census's `statements`; `measured` today; `runs` the round count. Every census round's `this run missing=` must be ≤ the new `missing` (Open question 4). Commit, and confirm one more CI run's gate is green.
5. **The listing, in the PR body** (the reviewer checks it against the artifacts):

```
Coverage (R21/R27/R34). Census: <N> rounds (runs <ids>), `this run missing=` in order: <m1, …, mN>; max <M>.
Floor: missing 589 -> 589 + H + O = <new>; statements <S>; percent <P>; packages <hash> (12: + relay/hls, relay/session).
H, relay/hls re-measured (per-file max over the rounds; 4a-1a's figure in brackets):
  box.go <n> [8], detect.go <n> [1], fragment.go <n> [3], init.go <n> [31], pipeline.go <n> [25],
  reader.go <n> [1], segmenter.go <n> [6], silence.go <n> [14] = <H> [89]
O, 4a-1b's own new or changed statements, uncovered (per-file max over the rounds):
  <file>: <n> (blocks <start-end>, …) …  = <O>
Additions: <A> statements, at most <U> uncovered in any round -> <pct>% (>= 85%).
Pre-existing flaps outside H and O: <none | file:block, rounds>.
```

The Python Gate 2 floor does not move (Task 10).

### AVPlayer (the manual gate's software half; R45)

No macOS runner exists in CI (Q8), so the implementer shows playback on this Mac, with Homebrew ffmpeg 9.0.1 standing in for the image's 9.0 and libx264 for Quick Sync:

1. **A scratch harness, never committed**, in `$SCRATCH/avharness/`: `git archive HEAD relay | tar -x` of the implementation's head plus one `cmd/avharness/main.go` inside that module copy (so it may import `relay/internal/relaytest`). It builds what `main.go` builds (the manager, the session table and its sweeper, `httpapi.New` with the dev routes and real `HLSDeps`), a `relaytest.ControlPlane` answering next-source with the Proxy kind, and a `relaytest.Upstream` paced at `Rate: 1` over an 80 s loop of a 4a-0 fixture (built with `e2e-upstream/scripts/make-asset.sh <out> <asset>` and concatenated with `ffmpeg -stream_loop 3 -c copy`, as 4a-1a's runs did). In front of the handler, a shim plays the authorize hop's part for the two tune roots only — it sets `X-Dispatcharr-Authorized` to `control.RelayTrustToken(secret)` and the `X-Relay-Channel`, `X-Relay-Client`, `X-Relay-User` and `X-Relay-Output-Format` headers (the last from `?output_format=`) — and strips every `X-Relay-*` from `/hls/` requests, as the blanking include does.
2. **The runs**, with the spec's probes (Appendix B: `probe2` for ready, first frame, frames and seconds behind PDT; `probe4` for the audio format; binaries in the orchestrator's `scratchpad/av/` and `scratchpad/p4proto/`), on macOS 27 and on the iOS 27 Simulator through `xcrun simctl spawn`:
   - `http://127.0.0.1:<port>/live/u/p/1.m3u8` (the Xtream `.m3u8` form, through `XCHandler`), 15 s, on `h264-1080i-aac-ac3`: macOS and iOS;
   - `http://127.0.0.1:<port>/proxy/ts/stream/<uuid>?output_format=hls`, 15 s, on `h264-eac3`: macOS and iOS, and `probe4` for the selected audio format;
   - a boundary: 40 s on the Xtream form with the harness advancing the channel to a second fixture (`mpeg2-576i-mp2`) at 20 s: macOS;
   - the leave: after a run, `curl -X DELETE` on the token path the harness's request log shows, then the channel list shows no `hls` client and the table is empty.
3. **The artefact** is the PR body's AVPlayer section: each probe's output line verbatim (platform, URL form, fixture), the harness's request log excerpt showing the `/hls/` GETs and the `DELETE`, and the harness's scratch path. Not committed. The Apple TV run, Q1 (Quick Sync) and Q2 (which audio group tvOS picks, through a TV and through a receiver) are the owner's, owed and non-gating (R45); the PR body says so in one line each.

### Gates

- Go: Task 9, and the Go gate under § Coverage.
- Python: `apps.proxy.tests`, `apps.output.tests`, `core.tests` green; Gate 2 isolated `missing` 33.
- E2E: every `Playwright`, `Lifecycle`, `Go`, `Backend` and `Frontend` result green on the PR (the `migration/` branch runs the full matrix).
- Manual: § AVPlayer.
- **Stopping point.** Not on its own (spec): on a slot-constrained provider a third-party app that never calls leave holds its slot for the idle timeout, so 4a-1c follows directly.

### PR description draft

Fill the `<…>` slots from Tasks 13, 14, 16 and 17; no closing keyword anywhere.

> **Phase 4a-1b: live HLS end to end.** A live tune whose format resolves to `hls` (`?output_format=hls`/`m3u8`, or an Xtream `.m3u8` URL) now answers a multivariant playlist instead of bytes. Media playlists and fMP4 segments live under `/hls/<token>/…`, where the token is an opaque, relay-minted session id with an HMAC of `SECRET_KEY` (context `media-session`). It names no channel and lives exactly as long as its session: `DELETE /hls/<token>`, an admin client stop or stream-limit termination, a stop of its channel, or the idle sweep (`max(12 s, 6 × TARGETDURATION)` with no request in flight) ends it, and a relay restart forgets it. An HLS viewer is a client in the relay's registry while its session is live, so stream limits, admin stop and the stats page need no special case; a resume never starts a channel. A failed HLS output marks the channel until its next source boundary, which only clears the mark. A Redirect-profile channel is served over HLS through the relay. nginx routes `^~ /hls/` to the relay with no authorize hop. `player_api` advertises `m3u8`, `get.php?output=m3u8` emits `.m3u8` URLs, and `/api/mino/capabilities/` tells the Mino app this server has 4a. `relay/hls` is linked for the first time; its store keeps 21 segments so a segment leaving the playlist stays available for its duration plus the playlist's (RFC 8216 § 6.2.2, R44). Spec D2-D5, D13, D19; this amends ADR 0006's registry sentence (spec § The ADR 0006 amendment; CLAUDE.md § State). Plan: `docs/superpowers/plans/2026-09-28-phase4-4a1b-live-hls.md` at `<plan PASS SHA>`. Refs: ADR 0008, ADR 0009.
>
> **Coverage.** <§ Coverage listing, verbatim>. Python Gate 2: `missing` 33, unchanged.
>
> **Tests changed** (before → after): <§ Tests changed, one line each>.
>
> **Break-checks:** <BC1-BC22, one line each: the wrong edit, the test, the red line>.
>
> **Measurements (not gates).** Q6 failover gap on CI's software encoder: <s> (run <id>). R29, the 1080i software transcode against real time: <ratio> (run <id>)<; below 1.0: raised as a finding>.
>
> **AVPlayer** (macOS 27 and the iOS 27 Simulator, the scratch harness, Homebrew ffmpeg 9.0.1, software): <probe lines>. Apple TV, Quick Sync (Q1) and tvOS's audio pick (Q2): the owner's, owed, not gating (R45).
>
> 🤖 Generated with [Claude Code](https://claude.com/claude-code)

## The seam, if this PR must split (R48)

One PR is the default: the relay half, nginx and the E2E are one behaviour and review against one another. If fix rounds grow it past review, the seam is the Django-surface half, which nothing in the relay half needs:

- **4a-1b-1**: everything except the next bullet — the relay, the aliases (`_FORMAT_ALIASES`, which the `?output_format=hls` E2E needs), the payload serializers, nginx, the E2E minus the Xtream-advertising and capability tests, the docs.
- **4a-1b-2**: `_xc_allowed_output_formats`, `get.php`'s `.m3u8` URLs, the capability document, their tests and E2E, and README's line.

## Residual risks and follow-ups

- **Resume bypasses the stream limit** for up to 300 s (spec § Risks), unchanged.
- **The drain's 5 s client grace is simply waited out** when HLS sessions exist: they never leave on their own. Bounded, and within D6's budget.
- **A third-party app that never calls leave** holds its stream-limit count for up to one idle timeout plus one sweep tick (13 s), and its slot until 4a-1c reclaims a silent session.
- **The token is in nginx's access log** (spec § Risks), as XC credentials already are.
- **The failover gap** (Q6) is measured in software on CI only; the owner measures Quick Sync (R45).
- **`hevc-aac` and `h264-gop10-aac`** are not in 4a-1b's E2E: both are transcoded to H.264 in 4a-1b exactly as the others, and they are 4a-1d's copy-rule fixtures.
- **A `CONTEXT.md` entry for "media session"** is not added: the spec's glossary names it "HLS session" in prose, and a term entry is a docs follow-up if the app repository needs one.
- **The M3U-link builder** (`frontend/src/components/tables/ChannelsTable.jsx:1404`) offers no HLS format; not in any 4a PR's scope.

## Spec amendments in this PR

Edits to `docs/superpowers/specs/2026-09-27-phase4-apple-native-live-design.md` in this plan PR (`grep -n` on this branch; the changelog entry "2026-09-28, amended by the 4a-1b plan" lists them):

- **R44**: § State the relay adds (`:290-295`), D14 (`:225`), § Storage and bounds (`:835`, `:843`) say 21 where they said 12, with RFC 8216 § 6.2.2's arithmetic and the memory figure.
- **R45**: § Testing and gates' AVPlayer paragraph (`:1202-1209`) and § 4a-1b's manual gate (`:1399-1400`).
- **Erratum**: `Manager.AttachExisting(c, client)` takes the session's `*Channel` (§ Resume never starts a channel, `:723-730`).
- **Housekeeping**: § 4a-1b names what it also carries (R44, Q6, R29, F1; `:1394-1398`); the Done log records #529 (`:1695`); the changelog entry (`:1848-1859`).

Open questions 1-3 change spec text only once ruled.

## Review changelog

- Round 0: written against the seed `fabc663a`. Appendix A was produced in a scratch export of the seed's files, diffed there, and checked to apply with `git apply --check --whitespace=error`; the two TypeScript files it changes typecheck (`npx tsc --noEmit -p .` in a scratch copy of `e2e/` at the seed plus the hunks), and the parity guard's structural checks pass on the new rows (only `every row cites source that resolves` and `every pin resolves` fail, on the slots and on files the implementation creates).

## Appendix A — documentation and configuration

Byte-exact against `fabc663a`, except the `⟨…⟩` slots in `docs/relay-parity-matrix.md`'s rows 37-44 (Task 12) and in `e2e/COVERAGE.md`'s observation row (Task 17). Apply with Task 2's command.

<!-- appendix-A-begin -->
```diff
diff --git a/CLAUDE.md b/CLAUDE.md
index 7ebd73a..0444a27 100644
--- a/CLAUDE.md
+++ b/CLAUDE.md
@@ -72,17 +72,17 @@ scripts/check_go_stdlib_only.sh relay           # the module must stay stdlib-on
 
 Django 6 + DRF, React 19 SPA same-origin, Celery, Redis for the broker, the cache and the channel layer — **no longer for the video path** (§ State) — PostgreSQL for durable state. `apps/proxy` fell from 40,652 non-blank Python lines to 16,952 when stage 2d-4 deleted the live relay; other work landed on top of that before #405, moving it to 17,450, and #405 dropped it to 16,350 (1,100 lines) by deleting the dead `hls_proxy`, and `apps/channels` is 17,579 (both from `scripts/metrics/collect_code_health.py`'s `loc_per_app`, which is the only definition either figure has); then `epg`, `timeshift` (Xtream catch-up), `m3u`, `core` (settings registry, profiles, events), `output`, `vod`, `plugins`, `hdhr`.
 
-**Two uWSGI processes**, running the same Django app under the same urlconf and differing only in listener, worker count and concurrency: the **API** process (`docker/uwsgi.ini` / `uwsgi.modular.ini`, unix socket plus `http = 0.0.0.0:5656`, 4 workers × `gevent = 400`, `harakiri = $(DISPATCHARR_API_HARAKIRI)` default 120s, `max-requests = $(DISPATCHARR_API_MAX_REQUESTS)` default 5000) serves everything except long-lived streams, and the **relay** process (`docker/uwsgi.relay.ini`, `socket = 0.0.0.0:5657`, `workers = 1`, `gevent = $(DISPATCHARR_RELAY_GEVENT)` default 1600, **no `harakiri`**) served `/proxy/ts/stream/`, `/proxy/vod/`, `/proxy/catchup/`, `/streaming/timeshift.php`, `/proxy/relay/…` and the XC streaming roots until Phase 2 stage 2d-3, and since that flip serves the VOD and catch-up half of them only — `/proxy/vod/`, `/proxy/catchup/`, `/streaming/timeshift.php`, `/movie/`, `/series/`, `/timeshift/`, plus the nested recordings-file regex — `docker/nginx.conf`'s location table is the authority on exactly which. Both carry `gevent-early-monkey-patch` + `dispatcharr/gevent_patch.py`, and each is one `supervisord` program among several (`docker/supervisord/` holds one conf per rung, `docker/supervisord.d/` one `[program:x]` per file), alongside: Celery `default` (prefork, `--autoscale=6,1`) and `dvr` (threads ×20, for `run_recording`), Celery beat (DB scheduler — UI-editable), Daphne :8001 for WebSockets, plus Redis and PostgreSQL in the AIO image. **`DISPATCHARR_ROLE`** (`all`/`api`/`relay`/`worker`, defaulted from `DISPATCHARR_ENV`) picks which subset a container runs; `DISPATCHARR_ENV=dev` picks the `all-dev` rung instead, which runs vite and no nginx. `priority=` orders start and stop *signals*, so each program waits for its own stores through `docker/supervisord.d/wait-for-stores.sh`, and shutdown walks one priority group at a time rather than signalling everything at once. (`docker/entrypoint.aio.sh` and `docker/entrypoint.celery.sh` are deleted, not legacy.) Since Phase 2 stage 2c there is a **third** server process, `relay-go` (`docker/supervisord.d/relay-go.conf`, roles `all` and `relay`, port 5658 from `DISPATCHARR_RELAY_GO_PORT`), a Go binary built in the Dockerfile's own `relay-builder` stage. As of Phase 2 stage 2c-8 it serves the whole live surface behind that dev flag — `GET /proxy/ts/stream/<id>`, both XC live roots, all five `/proxy/relay/…` control routes — plus, unflagged, `/healthz` (liveness: a static 200 even while draining, because a supervisor that restarted the process mid-drain would defeat the drain) and `/readyz` (readiness: 503 from the moment a SIGTERM raises the drain gate, with the channel and client counts in its body, and deliberately no probe of the control plane — a relay that deregistered during a Django outage would drop viewers whose streams need nothing from Django). Since stage 2d-3 nginx routes four locations to it — `^~ /proxy/ts/stream/`, `^~ /live/`, the XC three-segment regex and `^~ /proxy/relay/` — by `proxy_pass http://relay_go`, an `upstream relay_go` sed'd at boot from `DISPATCHARR_RELAY_GO_PORT`, with `DISPATCHARR_RELAY_GO_DEV_ROUTES="1"` set in `relay-go.conf` because every route but the two probes is behind that flag. It carries the same `nice -n $(UWSGI_NICE_LEVEL)` as both uWSGIs from the same commit, and `relay/drain/supervisord_priority_test.go` asserts the shared `priority=205` by reading both confs. Its shutdown is D6's drain: fifteen seconds against `relay-go.conf`'s `stopwaitsecs=20`, spent as a five-second client grace, a concurrent channel teardown that releases every provider slot, an `http.Server.Shutdown` that is only immediate because the channels stopped first, and a three-second events flush **reserved** out of the total rather than taking what is left — so a slow teardown costs the shutdown its wait and never costs the events their delivery. It shares supervisord `priority=205` with `relay-uwsgi` deliberately — a priority of its own would add its `stopwaitsecs` to the container's stop budget as a separate group and take the sum past the 160s `stop_grace_period`. It opens no Postgres connection and no Redis connection, and links no driver for either; `scripts/check_go_stdlib_only.sh` is the mechanical backstop, run by `go-tests.yml`. Consequences constraining nearly every `apps/proxy` change:
+**Two uWSGI processes**, running the same Django app under the same urlconf and differing only in listener, worker count and concurrency: the **API** process (`docker/uwsgi.ini` / `uwsgi.modular.ini`, unix socket plus `http = 0.0.0.0:5656`, 4 workers × `gevent = 400`, `harakiri = $(DISPATCHARR_API_HARAKIRI)` default 120s, `max-requests = $(DISPATCHARR_API_MAX_REQUESTS)` default 5000) serves everything except long-lived streams, and the **relay** process (`docker/uwsgi.relay.ini`, `socket = 0.0.0.0:5657`, `workers = 1`, `gevent = $(DISPATCHARR_RELAY_GEVENT)` default 1600, **no `harakiri`**) served `/proxy/ts/stream/`, `/proxy/vod/`, `/proxy/catchup/`, `/streaming/timeshift.php`, `/proxy/relay/…` and the XC streaming roots until Phase 2 stage 2d-3, and since that flip serves the VOD and catch-up half of them only — `/proxy/vod/`, `/proxy/catchup/`, `/streaming/timeshift.php`, `/movie/`, `/series/`, `/timeshift/`, plus the nested recordings-file regex — `docker/nginx.conf`'s location table is the authority on exactly which. Both carry `gevent-early-monkey-patch` + `dispatcharr/gevent_patch.py`, and each is one `supervisord` program among several (`docker/supervisord/` holds one conf per rung, `docker/supervisord.d/` one `[program:x]` per file), alongside: Celery `default` (prefork, `--autoscale=6,1`) and `dvr` (threads ×20, for `run_recording`), Celery beat (DB scheduler — UI-editable), Daphne :8001 for WebSockets, plus Redis and PostgreSQL in the AIO image. **`DISPATCHARR_ROLE`** (`all`/`api`/`relay`/`worker`, defaulted from `DISPATCHARR_ENV`) picks which subset a container runs; `DISPATCHARR_ENV=dev` picks the `all-dev` rung instead, which runs vite and no nginx. `priority=` orders start and stop *signals*, so each program waits for its own stores through `docker/supervisord.d/wait-for-stores.sh`, and shutdown walks one priority group at a time rather than signalling everything at once. (`docker/entrypoint.aio.sh` and `docker/entrypoint.celery.sh` are deleted, not legacy.) Since Phase 2 stage 2c there is a **third** server process, `relay-go` (`docker/supervisord.d/relay-go.conf`, roles `all` and `relay`, port 5658 from `DISPATCHARR_RELAY_GO_PORT`), a Go binary built in the Dockerfile's own `relay-builder` stage. As of Phase 2 stage 2c-8 it serves the whole live surface behind that dev flag — `GET /proxy/ts/stream/<id>`, both XC live roots, all five `/proxy/relay/…` control routes, and since Phase 4a-1b the HLS session routes `GET /hls/<token>/…` and `DELETE /hls/<token>` — plus, unflagged, `/healthz` (liveness: a static 200 even while draining, because a supervisor that restarted the process mid-drain would defeat the drain) and `/readyz` (readiness: 503 from the moment a SIGTERM raises the drain gate, with the channel and client counts in its body, and deliberately no probe of the control plane — a relay that deregistered during a Django outage would drop viewers whose streams need nothing from Django). Since stage 2d-3 nginx routes four locations to it — `^~ /proxy/ts/stream/`, `^~ /live/`, the XC three-segment regex and `^~ /proxy/relay/` — and since Phase 4a-1b a fifth, `^~ /hls/`, all by `proxy_pass http://relay_go`, an `upstream relay_go` sed'd at boot from `DISPATCHARR_RELAY_GO_PORT`, with `DISPATCHARR_RELAY_GO_DEV_ROUTES="1"` set in `relay-go.conf` because every route but the two probes is behind that flag. It carries the same `nice -n $(UWSGI_NICE_LEVEL)` as both uWSGIs from the same commit, and `relay/drain/supervisord_priority_test.go` asserts the shared `priority=205` by reading both confs. Its shutdown is D6's drain: fifteen seconds against `relay-go.conf`'s `stopwaitsecs=20`, spent as a five-second client grace, a concurrent channel teardown that releases every provider slot, an `http.Server.Shutdown` that is only immediate because the channels stopped first, and a three-second events flush **reserved** out of the total rather than taking what is left — so a slow teardown costs the shutdown its wait and never costs the events their delivery. It shares supervisord `priority=205` with `relay-uwsgi` deliberately — a priority of its own would add its `stopwaitsecs` to the container's stop budget as a separate group and take the sum past the 160s `stop_grace_period`. It opens no Postgres connection and no Redis connection, and links no driver for either; `scripts/check_go_stdlib_only.sh` is the mechanical backstop, run by `go-tests.yml`. Consequences constraining nearly every `apps/proxy` change:
 
 - Four API worker processes plus the relay's one ⇒ **no channel state may live in Python memory**. The Python relay running a single worker did not relax this: an API worker, a Celery task and that relay all read the same VOD or catch-up session through Redis, and a restart replaces the process. It is no longer true of the **live** path: the Go relay opens no Redis connection at all and holds its channels in process memory (ADR 0006), which is the one place in this codebase where state in memory is correct rather than a bug.
 - Early monkey-patching ⇒ every `threading.Thread` under `apps/proxy/` is a greenlet sharing one OS thread with 400 request greenlets. **One blocking call stalls the hub.** Non-test occurrences fell from 27 to 9 at stage 2d-4, 18 of them having been inside `live_proxy/`; #405 dropped it to 5 by deleting the four in the dead `apps/proxy/hls_proxy/`, leaving only `vod_proxy`'s `multi_worker_connection_manager.py`, so the rule binds one live module. The Go relay's goroutines are real OS-scheduled threads and none of this applies to them, which is why `-race` is not optional there.
 - **Subprocesses under gevent use `os.posix_spawn`, never `Popen`**, because `fork()`-based approaches hang in gevent's `_before_fork`. `live_proxy`'s `StreamManager` was the original reason and went with the package at stage 2d-4 (`grep -rn posix_spawn apps/proxy/` is now empty); the rule still binds the two call sites left in the uWSGI processes — `apps/plugins/api_views.py:618` (GPG) and `apps/connect/handlers/script.py:39`. **Do not "simplify" either back to `Popen`.** The Go relay spawns with `os/exec` plus `SysProcAttr{Setpgid, Pdeathsig}` and none of this applies to it.
 - **DB backend differs per process**: uWSGI gets `django-db-geventpool` (MAX_CONNS=8, REUSE_CONNS=3); Celery and Daphne get plain `postgresql`, deliberately unpatched.
-- nginx **buffering off, in the directive family that location's `_pass` speaks** — `proxy_buffering off` on the three Go-bound since stage 2d-3 (`/proxy/ts/stream/`, `/live/`, the XC three-segment regex), `uwsgi_buffering off` on every relay-bound location still on `uwsgi_pass` (`/proxy/vod/`, `/proxy/catchup/`, `/movie/`, `/series/`, `/timeshift/`, `/streaming/timeshift.php`, and the nested `^/api/channels/recordings/\d+/file/$` regex — the one long-lived response under `/api/`) is load-bearing — a past bug used `proxy_buffering off` (wrong directive family for `uwsgi_pass`) and nginx spooled live TS to disk. Pinned by `e2e/tests/streaming-greybox/nginx-stream-buffering.spec.ts`, which since stage 2d-3 asserts the exact set on each side of the split — the six top-level `uwsgi_buffering off` ones and the three top-level `proxy_buffering off` ones, each its own sorted `toEqual`; the tenth (the nested recordings regex) is folded into `^~ /api/`'s own body by that spec's `parseLocationBlocks`, which walks by brace depth and never gives a nested location a `target` of its own, so it is pinned by `docker/nginx.conf` review instead. `^~ /proxy/relay/` is relay-bound too and also `proxy_pass http://relay_go` since 2d-3, but deliberately carries **no** buffering directive of either family — it serves short JSON, not a long-lived stream — pinned by that same spec's fourth test, which also asserts its `dispatcharr_api_params_proxy.conf` include, `proxy_read_timeout 30s` and `proxy_connect_timeout 60s`.
+- nginx **buffering off, in the directive family that location's `_pass` speaks** — `proxy_buffering off` on the three Go-bound since stage 2d-3 (`/proxy/ts/stream/`, `/live/`, the XC three-segment regex) and on `^~ /hls/` since Phase 4a-1b, `uwsgi_buffering off` on every relay-bound location still on `uwsgi_pass` (`/proxy/vod/`, `/proxy/catchup/`, `/movie/`, `/series/`, `/timeshift/`, `/streaming/timeshift.php`, and the nested `^/api/channels/recordings/\d+/file/$` regex — the one long-lived response under `/api/`) is load-bearing — a past bug used `proxy_buffering off` (wrong directive family for `uwsgi_pass`) and nginx spooled live TS to disk. Pinned by `e2e/tests/streaming-greybox/nginx-stream-buffering.spec.ts`, which since stage 2d-3 asserts the exact set on each side of the split — the six top-level `uwsgi_buffering off` ones and the three top-level `proxy_buffering off` ones, each its own sorted `toEqual`; the tenth (the nested recordings regex) is folded into `^~ /api/`'s own body by that spec's `parseLocationBlocks`, which walks by brace depth and never gives a nested location a `target` of its own, so it is pinned by `docker/nginx.conf` review instead. `^~ /proxy/relay/` is relay-bound too and also `proxy_pass http://relay_go` since 2d-3, but deliberately carries **no** buffering directive of either family — it serves short JSON, not a long-lived stream — pinned by that same spec's fourth test, which also asserts its `dispatcharr_api_params_proxy.conf` include, `proxy_read_timeout 30s` and `proxy_connect_timeout 60s`. `^~ /hls/` (Phase 4 spec D3) is the third kind: Go-bound and `proxy_buffering off` like the byte-path locations, but with **no** `auth_request` and no `internal;`, like `^~ /proxy/relay/` — the media-session token in its path is its whole authorization — pinned by the fifth test through its own `TOKEN_BOUND_TARGETS` list, which also asserts the blanking include, `proxy_http_version 1.1`, `proxy_read_timeout 60s` and `proxy_connect_timeout 60s`; it joins neither of the first two tests' lists, so both stay exact.
 
-**State.** PostgreSQL holds durable rows — including settings, but **`CoreSettings` is one row per settings *group*, not per setting**: `key` unique, `value` a `JSONField`, eight groups (`core/models.py:207-214`). Every group is instance-wide, so there is no scoped settings write — treat any as blast radius (E2E allowlists them; see `docs/adr/0003`). `epg_settings` has no seeding migration, so POST it before you can PATCH it. **Redis no longer holds any live video byte.** Until stage 2d-4 it held the live ownership leases, channel metadata, client sets, switch requests and **the video bytes** in a ring buffer; all of that was `apps/proxy/live_proxy/`'s and went with it. What Redis holds now is the provider-slot counters, the VOD and catch-up halves of the per-user connection scan, Django's own `channel_stream:`/`stream_profile:` assignment keys, plus Celery broker / Channels layer / Django cache. They still share **DB 0**, so the blast radius of one of them is still all of them — but the biggest tenant, the video, is gone, and its removal was the whole of Phase 3's charter (ADR 0007). `BaseConfig.BUFFER_CHUNK_SIZE` at `apps/proxy/config.py:15` survives as `188 * 1361` = 255,868 bytes and is still the effective chunk size, so a `proxy_settings` edit still moves it — the 2c-2 sentence four below says how it reaches the relay and this one no longer repeats it (round-2 note 4). `scripts/wait_for_redis.py` is wait-only — it never flushes, in any role. AIO's Redis starts empty because supervisord runs it non-persistent (`--save "" --appendonly no`), not because anything wipes it, so a control-plane restart leaves a running relay's keys untouched. Since Phase 2 stage 2c-2, the Go relay's ring is a per-channel in-process buffer, not Redis-backed: a 300-chunk / 76,760,400-byte cap and the same 60-second retention as the Python relay, whichever binds first, sized from `BUFFER_CHUNK_SIZE` on the `next-source` answer (Amendment A1.4) rather than from a Go-side constant. Since stage 2c-3, the Go relay's client registry is likewise a map in process memory with no TTL, no heartbeat and no ghost sweep, because with one process a client entry cannot outlive the goroutine that made it; `GET /proxy/relay/channels[?clients=all]` is served from it and performs no write. Since 2c-4 the Go relay serves the FFmpeg/VLC/Streamlink architecture too: Django builds the argv (`StreamProfile.build_command`) and sends it as `stream_profile.argv` (Amendment A4.1); the relay spawns it with `Setpgid` and, on Linux, `Pdeathsig SIGKILL`, kills with SIGKILL, parses stderr with `relay/ffmpeg`'s port of `log_parsers.py`, and ends the tune with `ErrBufferingTimeout` until 2c-5 wires failover. Since 2c-5 the Go relay fails over: the three triggers drive one port of `StreamManager.run`'s loops (`relay/channel/channel.go`), a clean EOF is a retried connection failure, the buffering-triggered switch counts against `MAX_STREAM_SWITCHES` and, once it is spent, is refused rather than fatal (row 6, [#221](https://github.com/D10Scot/Dispatcharr/issues/221)), the degraded fallback reads the candidate list the initial `next-source` answer carried and never a Redis key, a Redirect channel is a 302 with no channel published, and `GET /proxy/relay/channels` carries `healthy`.
+**State.** PostgreSQL holds durable rows — including settings, but **`CoreSettings` is one row per settings *group*, not per setting**: `key` unique, `value` a `JSONField`, eight groups (`core/models.py:207-214`). Every group is instance-wide, so there is no scoped settings write — treat any as blast radius (E2E allowlists them; see `docs/adr/0003`). `epg_settings` has no seeding migration, so POST it before you can PATCH it. **Redis no longer holds any live video byte.** Until stage 2d-4 it held the live ownership leases, channel metadata, client sets, switch requests and **the video bytes** in a ring buffer; all of that was `apps/proxy/live_proxy/`'s and went with it. What Redis holds now is the provider-slot counters, the VOD and catch-up halves of the per-user connection scan, Django's own `channel_stream:`/`stream_profile:` assignment keys, plus Celery broker / Channels layer / Django cache. They still share **DB 0**, so the blast radius of one of them is still all of them — but the biggest tenant, the video, is gone, and its removal was the whole of Phase 3's charter (ADR 0007). `BaseConfig.BUFFER_CHUNK_SIZE` at `apps/proxy/config.py:15` survives as `188 * 1361` = 255,868 bytes and is still the effective chunk size, so a `proxy_settings` edit still moves it — the 2c-2 sentence four below says how it reaches the relay and this one no longer repeats it (round-2 note 4). `scripts/wait_for_redis.py` is wait-only — it never flushes, in any role. AIO's Redis starts empty because supervisord runs it non-persistent (`--save "" --appendonly no`), not because anything wipes it, so a control-plane restart leaves a running relay's keys untouched. Since Phase 2 stage 2c-2, the Go relay's ring is a per-channel in-process buffer, not Redis-backed: a 300-chunk / 76,760,400-byte cap and the same 60-second retention as the Python relay, whichever binds first, sized from `BUFFER_CHUNK_SIZE` on the `next-source` answer (Amendment A1.4) rather than from a Go-side constant. Since stage 2c-3, the Go relay's client registry is likewise a map in process memory, and a TS or fMP4 client entry has no TTL, no heartbeat and no ghost sweep, because with one process it cannot outlive the goroutine that made it; `GET /proxy/relay/channels[?clients=all]` is served from it and performs no write. **An HLS session is the exception** (Phase 4a-1b; the Phase 4 spec's § The ADR 0006 amendment): it is a registry entry with no goroutine of its own, from the entry request that served its multivariant until an explicit `DELETE /hls/<token>`, an admin client stop or stream-limit termination, a stop of its channel, or the idle sweep (`relay/session`, one process-wide sweeper ticking every second) departs it after `max(12 s, 6 × TARGETDURATION)` with no request in flight — a TTL in all but name, and the one place the relay infers presence rather than observing it. Since 2c-4 the Go relay serves the FFmpeg/VLC/Streamlink architecture too: Django builds the argv (`StreamProfile.build_command`) and sends it as `stream_profile.argv` (Amendment A4.1); the relay spawns it with `Setpgid` and, on Linux, `Pdeathsig SIGKILL`, kills with SIGKILL, parses stderr with `relay/ffmpeg`'s port of `log_parsers.py`, and ends the tune with `ErrBufferingTimeout` until 2c-5 wires failover. Since 2c-5 the Go relay fails over: the three triggers drive one port of `StreamManager.run`'s loops (`relay/channel/channel.go`), a clean EOF is a retried connection failure, the buffering-triggered switch counts against `MAX_STREAM_SWITCHES` and, once it is spent, is refused rather than fatal (row 6, [#221](https://github.com/D10Scot/Dispatcharr/issues/221)), the degraded fallback reads the candidate list the initial `next-source` answer carried and never a Redis key, a Redirect channel is a 302 with no channel published, and `GET /proxy/relay/channels` carries `healthy`.
 
-**Video path.** Three locked built-in **Stream Profiles** = three architectures: *Redirect* (302 to provider — no bytes through us, no failover after connect), *Proxy* (raw HTTP into the ring buffer, no subprocess, dead-air failover only), *FFmpeg/VLC/Streamlink* (spawn, read stdout, parse stderr, full failover). Default FFmpeg profile is a remux, not a transcode. **Do not confuse Stream Profile (upstream) with Output Profile** (optional downstream transcode reading the shared buffer on `pipe:0`, shared per `(channel, profile)` clusterwide — ten AC3 clients cost one ffmpeg). Since Phase 2 stage 2c-7 the Go relay serves them too, from `relay/output`: one transcode per pair, started by the first client on that profile and stopped by the last with no shutdown delay, writing a second in-process `buffer.Ring` its clients read instead of the channel's. Its argv is `output_profiles[*].argv` off the `next-source` answer, cached per channel and refreshed by every later answer a non-degraded failover receives (an edit mid-channel reaches new clients only after the next one, where Python re-reads the row per client), and an entry with a **null** argv is Django saying `shlex` refused that profile's parameters — a 500 for the client that selects it, where a profile merely absent from the map was deactivated and that client is served with no profile at all. An fMP4 client on a profile runs **two** chained processes, `mpegts:p<id>` then `fmp4:p<id>`, exactly as the deleted `live_proxy/views.py:765-792` composed them. **There is no HLS output** — true until Phase 4a-1 adds one (ADRs 0008 and 0009, the Phase 4 spec): the deleted `live_proxy/server.py:1352`'s `_OUTPUT_FORMAT_MANAGERS` registered only `fmp4`, MPEG-TS (default) uses no output-side ffmpeg, and `apps/proxy/hls_proxy/`, which never served one, was deleted by #405. Since Phase 2 stage 2c-6 the Go relay serves fMP4 too, from `relay/output`: one remux per channel spawned by the first fMP4 client and stopped by the last, reading the channel's shared ring on `pipe:0` and writing a second in-process buffer of whole fragments (`buffer.Fragments`, not `buffer.Ring` — the write unit is a variable-length fragment and the client-positioning rules differ), so an fMP4 channel costs roughly twice a TS-only channel's resident memory. It refuses any other format 501: `hls` never had a manager in Python and has none in Go. HLS *upstreams* are handled by forcing the ffmpeg profile.
+**Video path.** Three locked built-in **Stream Profiles** = three architectures: *Redirect* (302 to provider — no bytes through us, no failover after connect), *Proxy* (raw HTTP into the ring buffer, no subprocess, dead-air failover only), *FFmpeg/VLC/Streamlink* (spawn, read stdout, parse stderr, full failover). Default FFmpeg profile is a remux, not a transcode. **Do not confuse Stream Profile (upstream) with Output Profile** (optional downstream transcode reading the shared buffer on `pipe:0`, shared per `(channel, profile)` clusterwide — ten AC3 clients cost one ffmpeg). Since Phase 2 stage 2c-7 the Go relay serves them too, from `relay/output`: one transcode per pair, started by the first client on that profile and stopped by the last with no shutdown delay, writing a second in-process `buffer.Ring` its clients read instead of the channel's. Its argv is `output_profiles[*].argv` off the `next-source` answer, cached per channel and refreshed by every later answer a non-degraded failover receives (an edit mid-channel reaches new clients only after the next one, where Python re-reads the row per client), and an entry with a **null** argv is Django saying `shlex` refused that profile's parameters — a 500 for the client that selects it, where a profile merely absent from the map was deactivated and that client is served with no profile at all. An fMP4 client on a profile runs **two** chained processes, `mpegts:p<id>` then `fmp4:p<id>`, exactly as the deleted `live_proxy/views.py:765-792` composed them. **There was no HLS output until Phase 4a-1b** (ADRs 0008 and 0009, the Phase 4 spec): the deleted `live_proxy/server.py:1352`'s `_OUTPUT_FORMAT_MANAGERS` registered only `fmp4`, MPEG-TS (default) uses no output-side ffmpeg, and `apps/proxy/hls_proxy/`, which never served one, was deleted by #405. Since 4a-1b a live tune whose format resolves to `hls` (`?output_format=hls`/`m3u8`, or an Xtream `.m3u8` URL) answers a multivariant playlist, and `relay/hls` — one re-encode per channel, restarted at every source boundary — serves its media playlists and fMP4 segments under `/hls/<token>/…`, where the token is an opaque, relay-minted media-session id with an HMAC of `SECRET_KEY` that names no channel. MPEG-TS and fMP4 clients are unchanged, and a TS-only channel starts no encode. Since Phase 2 stage 2c-6 the Go relay serves fMP4 too, from `relay/output`: one remux per channel spawned by the first fMP4 client and stopped by the last, reading the channel's shared ring on `pipe:0` and writing a second in-process buffer of whole fragments (`buffer.Fragments`, not `buffer.Ring` — the write unit is a variable-length fragment and the client-positioning rules differ), so an fMP4 channel costs roughly twice a TS-only channel's resident memory. It refuses any format but `mpegts`, `fmp4` and `hls` with 501. HLS *upstreams* are handled by forcing the ffmpeg profile.
 
 **There is no owner election on the live path any more.** Until Phase 2 stage 2d-4 one uWSGI worker owned a channel's upstream, elected by `redis.set("live:channel:{id}:owner", worker_id, nx=True, ex=30)` in `live_proxy/server.py`; followers served their own clients from the same Redis keys and asked the owner to act over `live:events:{id}`. All of it is deleted. The Go relay is **one process with one in-memory registry** (spec D2): `relay/channel`'s `Manager` holds one `Channel` per live channel behind one mutex, so ownership is a map entry rather than a lease, a follower is a goroutine rather than a second process, and there is nothing to fence. What survives unchanged is the byte layout: `relay/buffer`'s ring realigns to 188-byte TS packets before writing chunks, and **the chunk index is monotonic for the channel's life, never reset by a stream switch** — why a switch doesn't touch clients; new clients still start ~5s behind live.
 
@@ -90,9 +90,9 @@ Failover: three independent triggers, ported verbatim into `relay/channel/channe
 
 VOD is deliberately different: no ring buffer (`iter_content(8192)` passthrough), one upstream per session, stateless across workers, pre-stream failover only. Its stream counter's four Lua scripts bypass the metadata lock **on purpose** — a real bug fix, pinned by `vod_proxy/tests/test_vod_lock_contention.py`.
 
-**Auth — two opposite defaults.** REST API is deny-by-default (`DEFAULT_PERMISSION_CLASSES = IsAdmin`): views are admin-only unless they opt down; authorization runs on `user_level` (Streamer 0 / Standard 1 / Admin 10) plus M2M to `ChannelProfile` — Django's Group/Permission tables are vestigial. Streaming is the opposite: `stream_ts` is `AllowAny` and a channel UUID is still the capability, but since Phase 1 PR 5 every relay-served surface authorizes through one function, `apps/proxy/authorize.py`'s `authorize_stream`, reached by nginx `auth_request` once per tune and inline where there is no nginx. It applies the STREAMS ACL (XC_API on the XC catch-up path), the principal, `user_level`, Channel Profile membership, `hidden_from_output`, the user's `hide_adult_content` against `Channel.is_adult`, the Output Profile and the live stream limit. An anonymous request with a valid UUID still streams an ordinary channel; a channel marked `hidden_from_output` no longer streams to anyone but an admin or an internal principal. `auth_request` runs on every relay-bound nginx location except the two the spec's S8 names; the marker `X-Dispatcharr-Authorized` (an HMAC of `SECRET_KEY`) and the six `X-Relay-*` params are overridden to empty on every other location — by `dispatcharr_api_params.conf`'s `uwsgi_param … ""` lines, and since stage 2d-3 by `dispatcharr_api_params_proxy.conf`'s `proxy_set_header … ""` twin on `^~ /proxy/relay/`, so `apps/proxy/authorize.py` is the only place the decision is made, never a header a client could hand-craft. The WebSocket consumer marks stats events admin-only. **A channel UUID is a secret; treat it as one.** Since Phase 1 PR 7 there is a second internal surface, the mirror image of `/api/relay/…`: `/proxy/relay/…` on the relay, five routes Django calls through `apps/proxy/relay_client.py` so no control-plane process reads a relay-owned Redis key. Both surfaces take the same two headers — the static `X-Dispatcharr-Internal` and the per-request `X-Dispatcharr-Internal-Request`, which binds method, full path (query string included), body and a 120-second window — and neither is `IsAdmin`. `^~ /proxy/relay/` is deliberately **not** `internal;` in nginx: Django dials it as an ordinary client, from the `worker` role across the compose network and from the `api` role through its own nginx.
+**Auth — two opposite defaults.** REST API is deny-by-default (`DEFAULT_PERMISSION_CLASSES = IsAdmin`): views are admin-only unless they opt down; authorization runs on `user_level` (Streamer 0 / Standard 1 / Admin 10) plus M2M to `ChannelProfile` — Django's Group/Permission tables are vestigial. Streaming is the opposite: `stream_ts` is `AllowAny` and a channel UUID is still the capability, but since Phase 1 PR 5 every relay-served surface authorizes through one function, `apps/proxy/authorize.py`'s `authorize_stream`, reached by nginx `auth_request` once per tune and inline where there is no nginx. It applies the STREAMS ACL (XC_API on the XC catch-up path), the principal, `user_level`, Channel Profile membership, `hidden_from_output`, the user's `hide_adult_content` against `Channel.is_adult`, the Output Profile and the live stream limit. An anonymous request with a valid UUID still streams an ordinary channel; a channel marked `hidden_from_output` no longer streams to anyone but an admin or an internal principal. `auth_request` runs on every relay-bound nginx location except the two the spec's S8 names and, since Phase 4a-1b, `^~ /hls/`, which the relay authorizes by the media-session token alone (Phase 4 spec D3, ruling R13); the marker `X-Dispatcharr-Authorized` (an HMAC of `SECRET_KEY`) and the six `X-Relay-*` params are overridden to empty on every other location — by `dispatcharr_api_params.conf`'s `uwsgi_param … ""` lines, and since stage 2d-3 by `dispatcharr_api_params_proxy.conf`'s `proxy_set_header … ""` twin on `^~ /proxy/relay/` (and on `^~ /hls/` since 4a-1b), so `apps/proxy/authorize.py` is the only place the decision is made, never a header a client could hand-craft. The WebSocket consumer marks stats events admin-only. **A channel UUID is a secret; treat it as one.** Since Phase 1 PR 7 there is a second internal surface, the mirror image of `/api/relay/…`: `/proxy/relay/…` on the relay, five routes Django calls through `apps/proxy/relay_client.py` so no control-plane process reads a relay-owned Redis key. Both surfaces take the same two headers — the static `X-Dispatcharr-Internal` and the per-request `X-Dispatcharr-Internal-Request`, which binds method, full path (query string included), body and a 120-second window — and neither is `IsAdmin`. `^~ /proxy/relay/` is deliberately **not** `internal;` in nginx: Django dials it as an ordinary client, from the `worker` role across the compose network and from the `api` role through its own nginx.
 
-**Routing.** `dispatcharr/urls.py` mounts Xtream endpoints (`player_api.php`, `get.php`, `/<user>/<pass>/<id>`) at the site root **before** the SPA catch-all — root-level route additions shadow the frontend. Client surface: `/proxy/{ts/stream/<uuid>,vod,catchup}`, `/output/{m3u,epg}`, `/hdhr/`, plus the XC API's 17 actions. **Every `/proxy/ts/` endpoint is keyed by the channel's UUID *string*, never its numeric id** — six of the seven routes capture `<str:channel_id>` (the collection form `/proxy/ts/status` captures nothing) and the identifier reaches the relay unresolved, with no DB lookup. Since Phase 2 stage 2d-2 the five admin views live in `apps/proxy/ts_admin_views.py`, registered by `apps/proxy/ts_admin_urls.py`, and `apps/proxy/stream_routes.py` registers only `stream/` — kept, with both XC live patterns, because `apps/proxy/authorize_views.py`'s `_surface_for()` resolves the tune URI through Django's own urlconf and keys on the view's `__name__`, so deleting them would 403 every live tune behind nginx; the XC live roots are served by the Go relay, and Django's `stream_ts`/`stream_xc` are 501 stubs (`apps/proxy/stream_routes.py`) that exist only to be resolved by the authorize hop, never to be called behind nginx. Passing `channel.id` to `/status/`, `/change_stream/`, `/next_stream/` or `/stop/` 404s for every channel, always. No SSDP/UPnP discovery for the HDHomeRun emulation; the generated M3U emits no `catchup=` attributes (advertised only via XC `tv_archive`).
+**Routing.** `dispatcharr/urls.py` mounts Xtream endpoints (`player_api.php`, `get.php`, `/<user>/<pass>/<id>`) at the site root **before** the SPA catch-all — root-level route additions shadow the frontend. Client surface: `/proxy/{ts/stream/<uuid>,vod,catchup}`, `/output/{m3u,epg}`, `/hdhr/`, the XC API's 17 actions, and since Phase 4a-1b `/hls/<token>/…` (the HLS session resources, reached only from a multivariant playlist) and `/api/mino/capabilities/` (the Mino app's capability document, `AllowAny` behind the `XC_API` network ACL). **Every `/proxy/ts/` endpoint is keyed by the channel's UUID *string*, never its numeric id** — six of the seven routes capture `<str:channel_id>` (the collection form `/proxy/ts/status` captures nothing) and the identifier reaches the relay unresolved, with no DB lookup. Since Phase 2 stage 2d-2 the five admin views live in `apps/proxy/ts_admin_views.py`, registered by `apps/proxy/ts_admin_urls.py`, and `apps/proxy/stream_routes.py` registers only `stream/` — kept, with both XC live patterns, because `apps/proxy/authorize_views.py`'s `_surface_for()` resolves the tune URI through Django's own urlconf and keys on the view's `__name__`, so deleting them would 403 every live tune behind nginx; the XC live roots are served by the Go relay, and Django's `stream_ts`/`stream_xc` are 501 stubs (`apps/proxy/stream_routes.py`) that exist only to be resolved by the authorize hop, never to be called behind nginx. Passing `channel.id` to `/status/`, `/change_stream/`, `/next_stream/` or `/stop/` 404s for every channel, always. No SSDP/UPnP discovery for the HDHomeRun emulation; the generated M3U emits no `catchup=` attributes (advertised only via XC `tv_archive`).
 
 **Observing a channel.** `GET /proxy/ts/status/<uuid>` (admin-only) is the only status surface, and since Phase 1 PR 7 it is a thin wrapper over `GET /proxy/relay/channels/<uuid>` on the relay — the control plane no longer reads a relay Redis key to answer it. Two fields still mislead and one no longer does. `owner` falls back to the literal string `'unknown'`, never null — truthiness checks pass when nobody owns the channel. `total_bytes`, `avg_bitrate_kbps`, `stream_id`, `stream_name` can be **absent entirely** (not null), which the DRF serializer preserves deliberately. `ffmpeg_speed` is a **float on both endpoints** and `state` is **`null` rather than `'unknown'`** when the channel has never recorded one: PR 7 put both payloads behind one serializer, which is not a thing that can carry the disagreement they used to have. `source_fps` still disagrees — a string on the per-channel endpoint, a float on the collection one — and is carried, not fixed. Since Phase 1 PR 6, `relay_event` is pushed over the WebSocket for `channel_failover`, `stream_switch` and `client_disconnect` (`core/relay_events.py`), admin-only like `channel_stats` (`dispatcharr/consumers.py`), its payload a field whitelist that never carries a provider URL. `channel_stats` is still the only *stats* emission and still a JSON-encoded *string* under `data.stats`, broadcast as a side effect of polling the bare `GET /proxy/ts/status`. Observe transitions by polling the per-channel endpoint.
 
diff --git a/README.md b/README.md
index 2e8c359..9c6afce 100644
--- a/README.md
+++ b/README.md
@@ -150,7 +150,7 @@ We welcome **PRs, issues, ideas, and suggestions**!
 - 📁 **Media Library** — Import local files and serve them over XC API
 - 👥 **Enhanced User Management** — Customizable XC API output per user account
 - 🔌 **Fallback Videos** — Automatic fallback content when channels are unavailable
-- 📡 **HLS Output** — Serve streams as HLS alongside existing container formats
+- 📡 **HLS Output** — Live channels are served as HLS today (fMP4 segments, re-encoded for Apple devices, alongside MPEG-TS and fMP4); VOD, catch-up and recordings over HLS are still upcoming
 
 ---
 
diff --git a/docker/dispatcharr_api_params_proxy.conf b/docker/dispatcharr_api_params_proxy.conf
index 1fd81df..0fc5465 100644
--- a/docker/dispatcharr_api_params_proxy.conf
+++ b/docker/dispatcharr_api_params_proxy.conf
@@ -1,6 +1,8 @@
-# The proxy_pass twin of dispatcharr_api_params.conf, included by the one
-# relay-bound location that is Go-relay-bound AND deliberately outside the
-# authorize hop: ^~ /proxy/relay/ (spec amendment S8).
+# The proxy_pass twin of dispatcharr_api_params.conf, included by the two
+# relay-bound locations that are Go-relay-bound AND deliberately outside the
+# authorize hop: ^~ /proxy/relay/ (spec amendment S8) and, since Phase 4a-1b,
+# ^~ /hls/ (Phase 4 spec D3), whose media-session token is its whole
+# authorization.
 #
 # Why it exists: proxy_pass_request_headers is on by default, so a client's
 # own X-Dispatcharr-Authorized or X-Relay-* header would otherwise reach the
@@ -19,10 +21,13 @@
 # nginx.conf declares at :51-56 (X-Real-IP, X-Forwarded-For,
 # X-Forwarded-Host, X-Forwarded-Proto, Host, X-Forwarded-Port). The three
 # byte-path locations re-declare all six because a viewer's address is
-# externally observable there (parity-matrix row 17); this location's client
-# is Django, not a viewer, and the Go control API reads neither a forwarded
-# address nor a forwarded Host. Losing Host: $host on a JSON API between two
-# internal processes is inert.
+# externally observable there (parity-matrix row 17). ^~ /proxy/relay/'s
+# client is Django, not a viewer, and the Go control API reads neither a
+# forwarded address nor a forwarded Host. Losing Host: $host on a JSON API
+# between two internal processes is inert. ^~ /hls/'s client IS a viewer,
+# but its handlers read neither either: a session's address and user agent
+# are the ones its entry request recorded through the hop, and the
+# playlists carry absolute-path and relative URIs that need no Host.
 #
 # There is no `include uwsgi_params;` counterpart: uwsgi_params exists to
 # build the uwsgi wire protocol's variable block, which proxy_pass does not
diff --git a/docker/docker-compose.aio.yml b/docker/docker-compose.aio.yml
index be0080d..14a4fc0 100644
--- a/docker/docker-compose.aio.yml
+++ b/docker/docker-compose.aio.yml
@@ -48,6 +48,9 @@ services:
     # Optional for hardware acceleration
     #devices:
     #  - /dev/dri:/dev/dri  # For Intel/AMD GPU acceleration (VA-API)
+    #    The same device is Intel Quick Sync for the live HLS output's
+    #    encode (Phase 4, ADR 0009). Without /dev/dri the relay encodes HLS
+    #    in software (libx264), logs that once at WARNING, and never refuses.
     # Uncomment the following lines for NVIDIA GPU support
     # NVidia GPU support (requires NVIDIA Container Toolkit)
     #deploy:
diff --git a/docker/docker-compose.dev.yml b/docker/docker-compose.dev.yml
index 6308432..e83432b 100644
--- a/docker/docker-compose.dev.yml
+++ b/docker/docker-compose.dev.yml
@@ -42,6 +42,12 @@ services:
     # Uncomment to enable high priority for streaming (required if UWSGI_NICE_LEVEL < 0)
     #cap_add:
     #  - SYS_NICE
+    #
+    # Optional: Intel Quick Sync for the live HLS output's encode (Phase 4,
+    # ADR 0009). Without /dev/dri the relay encodes HLS in software
+    # (libx264), logs that once at WARNING, and never refuses.
+    #devices:
+    #  - /dev/dri:/dev/dri
 
   pgadmin:
     image: dpage/pgadmin4
diff --git a/docker/docker-compose.yml b/docker/docker-compose.yml
index b74bac6..d3d4f30 100644
--- a/docker/docker-compose.yml
+++ b/docker/docker-compose.yml
@@ -203,6 +203,9 @@ services:
     #  #- render  # Uncomment if your GPU requires it
     #devices:
     #  - /dev/dri:/dev/dri  # For Intel/AMD GPU acceleration (VA-API)
+    #    The same device is Intel Quick Sync for the live HLS output's
+    #    encode (Phase 4, ADR 0009). Without /dev/dri the relay encodes HLS
+    #    in software (libx264), logs that once at WARNING, and never refuses.
 
   # ============================================================================
   # Celery Service - Background task worker
diff --git a/docker/nginx.conf b/docker/nginx.conf
index dff66bd..8f6a728 100644
--- a/docker/nginx.conf
+++ b/docker/nginx.conf
@@ -52,10 +52,10 @@ upstream relay_go {
 # scale-out assignment would route (ADR 0005).
 # Since stage 2d-3 every location still passing to
 # $relay_upstream runs the hop, so $relay_name is always set and `default`
-# is a fallback rather than a route: the two relay-bound locations that run
-# no subrequest -- ^~ /proxy/relay/ and the nested recordings regex -- name
-# their upstream group literally and never consulted this map even before
-# the flip.
+# is a fallback rather than a route: the three relay-bound locations that
+# run no subrequest -- ^~ /proxy/relay/, the nested recordings regex and
+# (since Phase 4a-1b) ^~ /hls/ -- name their upstream group literally, and
+# the first two never consulted this map even before the flip.
 map $relay_name $relay_upstream {
     default relay_py;
     py      relay_py;
@@ -66,8 +66,8 @@ map $relay_name $relay_upstream {
 # :207) -- none of which builds absolute URLs. Every other proxy_pass
 # location declares its own proxy_set_header set instead (/ws/ its own
 # two; the three relay_go byte locations re-declare all six, with their
-# own comment explaining why) or blanks them (/proxy/relay/, also
-# commented) -- a location that declares any proxy_set_header of its own
+# own comment explaining why) or blanks them (/proxy/relay/ and /hls/,
+# also commented) -- a location that declares any proxy_set_header of its own
 # inherits none of the server block's. The uwsgi_pass locations
 # deliberately get no X-Forwarded-* of nginx's own:
 # uwsgi_pass_request_headers (default on; see dispatcharr_api_params.conf)
@@ -458,6 +458,37 @@ server {
         proxy_connect_timeout 60s;
         proxy_pass http://relay_go;
     }
+    # The HLS session resources (Phase 4a-1b; Phase 4 spec D3): media
+    # playlists, init and media segments under /hls/<token>/..., and
+    # DELETE /hls/<token>, the explicit leave. Every URI here comes from a
+    # multivariant playlist the relay answered on an ordinary live tune,
+    # which ran the hop.
+    #
+    # Deliberately outside the authorize hop, like ^~ /proxy/relay/: the
+    # media-session token in the path is the whole authorization, verified
+    # by the relay (ruling R13), so Django is not asked once per segment.
+    # NOT `internal;`: a player fetches these as an ordinary client. The
+    # blanking include is still here, so a client-supplied
+    # X-Dispatcharr-Authorized or X-Relay-* header never reaches the relay
+    # on this path -- which ignores both on /hls/ anyway.
+    #
+    # proxy_buffering off: a media segment runs to megabytes, and a media
+    # playlist request long-polls for up to 20 s for its first segment.
+    # proxy_read_timeout 60s sits above the relay's own 20 s waits, and
+    # proxy_connect_timeout 60s is explicit for the byte-path locations'
+    # reason (the server block's 75 would otherwise be inherited). None of
+    # the six server-level proxy_set_header lines is re-declared: the
+    # playlists carry absolute-path and relative URIs, so nothing here
+    # needs Host or the scheme, and a session's client address is the one
+    # its entry request recorded (spec D3).
+    location ^~ /hls/ {
+        include /etc/nginx/dispatcharr_api_params_proxy.conf;
+        proxy_buffering off;
+        proxy_http_version 1.1;
+        proxy_read_timeout 60s;
+        proxy_connect_timeout 60s;
+        proxy_pass http://relay_go;
+    }
     location ^~ /live/ {
         auth_request /_dispatcharr/authorize;
         auth_request_set $relay_name    $upstream_http_x_relay_name;
diff --git a/docs/relay-parity-matrix.md b/docs/relay-parity-matrix.md
index af14d84..ae44f06 100644
--- a/docs/relay-parity-matrix.md
+++ b/docs/relay-parity-matrix.md
@@ -203,9 +203,17 @@ PR's first, which is the distance git needs to merge them cleanly.
 | 30 | A credential an authenticator explicitly REJECTS (a malformed Bearer JWT, an unknown API key) is refused 401; a credential merely DECLINED — no header presented at all — falls through to the anonymous principal, which still streams an ordinary channel by UUID | `apps/proxy/authorize.py:258-259` (`except AuthenticationFailed: raise AuthorizeDenied(401, ...)`) vs `apps/proxy/authorize.py:260-265` (`except APIException: return None`, and the no-match fall-through), over the authenticator set at `apps/proxy/authorize.py:93-97` | `relay/httpapi/authorize_test.go::TestADenialReachesTheViewerWithItsOwnStatus` | Found by 2a-5, recorded as a porting hazard in a docstring only; inherited by 2a-7 and pinned here. A port that flattens both exits to "anonymous" fails no other test in the suite, and the failure it introduces is silent — a request carrying a credential the control plane rejected streams anyway. **The pin is driven at `GET /_dispatcharr/authorize`, not at `/proxy/ts/stream/<uuid>` directly** — `stream_ts` is `@api_view` with no `authentication_classes` override, so DRF's own `dispatch()` runs the project `DEFAULT_AUTHENTICATION_CLASSES` (`JWTAuthentication`, `ApiKeyAuthentication`) and refuses a rejected Bearer token or API key with DRF's own body shape *before* `resolve_authorization()`/`_drf_user()` ever runs — verified for both credential types by driving each directly at the stream URL and reading the response body, not assumed. A Go relay that faithfully ports this module and is then driven at a bare streaming URL with no `auth_request` in front of it would diverge from Python's behaviour there not because the port got `authorize.py` wrong, but because Python itself never runs `_drf_user`'s disposition logic on that path for these two credential types — a D5 parity fact about which surface makes this decision, not a footnote. Filed as [#247](https://github.com/D10Scot/Dispatcharr/issues/247), a 2c carry-forward in the same shape as #235, for the implementer who is not reading this table row by row. The Go pin covers the RELAY's share of this row and not the decision: it asks Django the whole question and obeys the answer exactly. The decision itself is Django's, made by authorize_stream, and the Python and e2e pins above are what cover it. |
 <!-- block: phase 4 -->
 | 31 | An HLS generation's segments are 2.000 s plus or minus one frame, each starting with a sync sample: the segmenter accumulates the encoder's fragments until the 2 s grid from the generation's first video frame is reached and cuts only before a fragment that opens on a sync sample | `relay/hls/segmenter.go:238-275`, `relay/hls/argv.go:340-393` | `relay/hls/real_test.go::TestRealThe1080iFixtureGivesAligned2sSegmentsOnThreeRenditions`, `relay/hls/pipeline_test.go::TestSegmentsAccumulateToTheGridAndCutOnlyAtASyncSample` | Phase 4a-1a (spec D6, D8). The real pin runs 12 s of the 4a-0 `h264-1080i-aac-ac3` fixture through the software transcode (`-force_key_frames expr:gte(t,n_forced*2)`, `-g` and `-keyint_min` at round(2R)) and checks every segment but the generation's flushed last one. The stand-in pin feeds one-second fragments, a non-sync one on a grid line included, so the accumulation and the sync rule are held without a real encoder. Inert until 4a-1b serves the store. |
-| 32 | A source boundary (every new upstream connection: a failover or a same-URL reconnect) ends the HLS generation at the boundary's first chunk, and the next generation's first segment carries `EXT-X-DISCONTINUITY` and a new `EXT-X-MAP` while the media sequence continues | `relay/channel/boundary.go:38-63`, `relay/channel/channel.go:603-605`, `relay/hls/feed.go:61-104`, `relay/hls/store.go:107-136`, `relay/hls/store.go:209-241` | `relay/hls/real_test.go::TestRealABoundaryGivesTwoGenerationsAndADiscontinuity`, `relay/channel/boundary_test.go::TestEveryConnectionAttemptRecordsASourceBoundary` | Phase 4a-1a (spec D10, M3). The real pin feeds two 4a-0 fixtures with different PIDs across a recorded boundary; one encoder fed straight across it silently drops the second source, which is the break-check. `buffer.Ring.MarkBoundary` publishes the old connection's pending whole packets before the boundary, so the chunk at the boundary index is the new connection's own. |
+| 32 | A source boundary (every new upstream connection: a failover or a same-URL reconnect) ends the HLS generation at the boundary's first chunk, and the next generation's first segment carries `EXT-X-DISCONTINUITY` and a new `EXT-X-MAP` while the media sequence continues | `relay/channel/boundary.go:38-63`, `relay/channel/channel.go:603-605`, `relay/hls/feed.go:61-104`, `relay/hls/store.go:107-136`, `relay/hls/store.go:209-241` | `relay/hls/real_test.go::TestRealABoundaryGivesTwoGenerationsAndADiscontinuity`, `relay/channel/boundary_test.go::TestEveryConnectionAttemptRecordsASourceBoundary`, `e2e/tests/streaming/hls-failover.spec.ts::a failover to a different asset starts a new generation behind EXT-X-DISCONTINUITY` | Phase 4a-1a (spec D10, M3). The real pin feeds two 4a-0 fixtures with different PIDs across a recorded boundary; one encoder fed straight across it silently drops the second source, which is the break-check. `buffer.Ring.MarkBoundary` publishes the old connection's pending whole packets before the boundary, so the chunk at the boundary index is the new connection's own. |
 | 33 | Each HLS generation is probed where it starts: the first from the join point behind live, every later one from its boundary index, so the second generation's probe describes the second source | `relay/hls/pipeline.go:328-444`, `relay/hls/pipeline.go:468-549` | `relay/hls/real_test.go::TestRealABoundaryGivesTwoGenerationsAndADiscontinuity` | Phase 4a-1a (spec D9). The probe's feed stops at the next boundary as the generation's does. It is bounded at 3 s or 3,000,000 bytes, with one re-probe at 8 s or 5 MB when the video has no geometry or field order (ruling R30; the long-GOP case is `relay/hls/real_test.go::TestRealALongGOPIsReprobedAtTheFullBound`); on an MPEG-TS pipe ffprobe reads to its bound whatever it has found, so the bound is the probe's share of the failover gap (Q6). A connection that ends at the next boundary before it can be probed is skipped rather than failing the output, at generation 0 as at any later one (plan review, round 1 finding 3 and ruling R39); a ring that closes under a probe is a stop (R40). |
 | 34 | With no usable Quick Sync the HLS encoder runs in software and never refuses: a missing render node, a failing one-frame detection encode or its timeout selects libx264, and Quick Sync is written off for the process only when a software retry succeeds where it failed and the detection encode, re-run, fails | `relay/hls/detect.go:89-173`, `relay/hls/pipeline.go:574-606` | `relay/hls/detect_test.go::TestDetection`, `relay/hls/real_test.go::TestRealDetectionWithoutQuickSyncGivesSoftware`, `relay/hls/pipeline_test.go::TestASourceCausedEarlyFailureDoesNotWriteQuickSyncOff`, `relay/hls/pipeline_test.go::TestQuickSyncIsWrittenOffOnlyWhenSoftwareSucceedsAndRedetectionFails`, `relay/hls/detect_test.go::TestADetectionCutShortByTheCallerIsNotCached` | Phase 4a-1a (spec D11, finding 5). A detection or re-check cut short by the caller's own context is no evidence and writes nothing off (plan review, finding 1). The QSV argv itself has not run on Quick Sync hardware (Q1); these pins hold the selection and the write-off rule, not the device. |
 | 35 | An audio stream that does not qualify (no known codec, 0 channels or a 0 sample rate, which is what a PMT-declared PID carrying no packets probes as) declares no HLS rendition and is never mapped into the encoder's argv | `relay/hls/probe.go:167-173`, `relay/hls/argv.go:124-154`, `relay/hls/argv.go:260-294` | `relay/hls/real_test.go::TestRealADeclaredButEmptyAudioPIDIsNotMapped`, `relay/hls/argv_test.go::TestANonQualifyingAudioStreamIsNotMapped` | Phase 4a-1a (spec § Encoder argv, finding 7). Mapping such a stream fails every output of the generation (ffmpeg 9.0.1: `sample rate not set`). The real pin strips the AC-3 PID's packets from the 4a-0 1080i fixture and keeps its PMT entry. |
 | 36 | A stalled HLS encoder is a death: a generation that writes no new video fragment for max(10 s, 5 x TARGETDURATION) of the channel's ring advancing is killed and counted against the restart bound, while an encoder starved by an idle ring is left alone | `relay/hls/pipeline.go:38`, `relay/hls/pipeline.go:731`, `relay/hls/pipeline.go:802-839` | `relay/hls/pipeline_test.go::TestAStalledEncoderIsKilledAsADeath`, `relay/hls/pipeline_test.go::TestAStarvedEncoderIsNotKilled` | Phase 4a-1a (ruling R33, R38). The ring, not the bytes fed, is the measure of input advancing, because a wedged encoder that stops reading its stdin stops the feed too. The clock starts at the first ring advance after the latest fragment and resets whenever the ring is idle for half the timeout, so the watchdog is inert below roughly 410 kb/s (a 255,868-byte chunk less often than every 5 s). |
+| 37 | A live tune whose output format resolves to `hls` answers a multivariant playlist rather than bytes: `?output_format=hls` or `m3u8` through the hop's aliases, or an Xtream `.m3u8` URL on either XC root through the relay's extension override, gets 200 `application/vnd.apple.mpegurl` with `Cache-Control: no-store` once the first generation that writes a complete set of init segments has done so, every URI under `/hls/<token>/`; not ready within 20 s is 503 with `Retry-After: 1` and leaves no client | `apps/proxy/authorize.py:⟨_FORMAT_ALIASES⟩`, `relay/httpapi/xc.go:⟨xcForcedFormat⟩`, `relay/httpapi/stream.go:⟨identify's output-format check⟩`, `relay/httpapi/hls.go:⟨serveHLSEntry⟩` | `relay/httpapi/hls_test.go::TestAnHLSTuneAnswersAMultivariantPlaylistRatherThanBytes`, `relay/httpapi/hls_test.go::TestAnXCM3U8URLForcesHLSOnBothRoots`, `relay/httpapi/hls_test.go::TestAnEntryWhoseInitsNeverArriveIs503AndLeavesNoClient`, `e2e/tests/streaming/hls-entry.spec.ts::an hls tune answers a multivariant playlist on all three entry forms` | Phase 4a-1b (spec D2, D3, § Entry). The multivariant carries a fresh token on every entry, hence `no-store`. `X-Relay-Output` is ignored on an `hls` tune (D12), so the client's `output_profile_id` is null. `hls` is never a deployment or user default (D2, R23). |
+| 38 | `/hls/` is authorized by the media-session token alone: `v1.<sid>.<mac>`, a 128-bit random sid and an HMAC-SHA256 of `SECRET_KEY` over `media-session`, `v1` and the sid, naming no channel; a GET whose token is malformed or whose MAC is wrong, or whose sid is unknown (left, ended by an admin, past its resume window, or minted before a relay restart), is 403 with one body and no detail; a GET on a session whose channel stopped is 410 once and 403 after; `X-Relay-*` and `X-Dispatcharr-Authorized` are ignored there | `relay/control/mediasession.go:⟨MediaSessionToken, VerifyMediaSession⟩`, `relay/session/table.go:⟨Begin⟩`, `relay/httpapi/hls.go:⟨the /hls/ GET handler⟩` | `relay/control/mediasession_test.go::TestAMediaSessionTokenIsRefusedWhenForgedOrTampered`, `relay/httpapi/hls_test.go::TestAStoppedSessionIs410OnceThen403AndADeleteIs204`, `relay/httpapi/hls_test.go::TestARejectedTokensTextNeverReachesTheLog`, `e2e/tests/streaming/hls-sessions.spec.ts::a tampered token, a left session and a stopped client are refused` | Phase 4a-1b (spec D4, § The media-session token; R13, R22). No expiry field: the token lives exactly as long as its session (R22). The MAC is compared with `hmac.Equal` before any table lookup. The token is never logged by the relay; nginx's access log records it as it records XC credentials (spec § Risks). |
+| 39 | An HLS viewer is a client in the channel's registry exactly while its session is live: it arrives with its multivariant (`client_connect`), is active on every request carrying its token, and leaves, with `client_disconnect` (`duration`, `bytes_sent`) and its Attach release, on `DELETE /hls/<token>` (204, idempotent), on an admin client stop or stream-limit termination, or once `max(12 s, 6 x TARGETDURATION)` has passed with no request in flight | `relay/session/table.go:⟨Leave, EndClient, Sweep⟩`, `relay/session/departure.go:⟨Run⟩`, `relay/httpapi/control.go:⟨ClientHandler⟩` | `relay/session/table_test.go::TestAnIdleSessionDepartsAfterTheIdleTimeoutAndNotBefore`, `relay/session/table_test.go::TestARequestInFlightHoldsASessionActive`, `relay/httpapi/hls_test.go::TestALeaveEndsTheSessionAtOnceAndIsIdempotent`, `relay/httpapi/hls_test.go::TestAnAdminClientStopEndsAnHLSSession`, `e2e/tests/streaming/hls-sessions.spec.ts::an hls client is listed while it plays and leaves at once on DELETE` | Phase 4a-1b (spec D5, § Presence). The one place the relay infers presence rather than observing it (spec § The ADR 0006 amendment). The per-user stream limit counts these clients because it counts the registry; a departed session is not a client. |
+| 40 | A stopped channel's HLS sessions become STOPPED on the goroutine that decided the stop, never synchronously on the channel's own: an admin stop and the drain in `Manager.Stop`, the last client's release in `stopIfStillIdle`, and a run that ended by itself or an HLS output that failed on a fresh goroutine, which drops their client entries (`client_disconnect`, no release) and then makes the manager's idle decision, so no stop waits on its own `done` | `relay/channel/manager.go:⟨Stop, stopIfStillIdle, StopIfIdle, EndHLSSessions, runEnded⟩`, `relay/channel/channel.go:⟨fireRunEnd⟩`, `relay/httpapi/hls.go:⟨watchHLS⟩` | `relay/httpapi/hls_test.go::TestSelfStopRunEnded`, `relay/httpapi/hls_test.go::TestSelfStopHLSFailedWithNoOtherClient`, `relay/httpapi/hls_test.go::TestSelfStopHLSFailedWithATSClient`, `relay/httpapi/hls_test.go::TestAnAdminChannelStopEndsItsHLSSessions` | Phase 4a-1b (spec § Presence, Who ends sessions). The run-ended case is the break-check's oracle: done synchronously from `run()`'s defers, the stop waits out `StopWait` on its own `done` and logs `source goroutine did not return in time`. |
+| 41 | A resume never starts a channel or reserves a slot: a request on a departed session within 300 s re-attaches through the non-starting `AttachExisting`, and only to the very channel and HLS pipeline its playlists name; a channel absent or restarted, a pipeline no longer running, or a stop between the lookup and the commit answers 410 and leaves no client and no table entry | `relay/channel/manager.go:⟨AttachExisting⟩`, `relay/channel/hlsoutput.go:⟨AttachHLSExisting⟩`, `relay/httpapi/hls.go:⟨resume⟩`, `relay/session/table.go:⟨ResumeCommit⟩` | `relay/httpapi/hls_test.go::TestAResumeNeverStartsAChannel`, `relay/httpapi/hls_test.go::TestAResumeThatLosesTheRaceToAStopReleasesItsAttachment`, `relay/httpapi/hls_test.go::TestADepartedSessionResumesOnItsRunningPipeline` | Phase 4a-1b (spec § Resume never starts a channel). A `/hls/` request ran no authorize hop and no stream-limit check, which is why it may never start anything. A resumed session is not re-checked against the stream limit, bounded by the 300 s window (spec § Risks). |
+| 42 | A Redirect-profile channel is served over HLS through the relay, as Proxy: an `hls` tune reserves and holds the provider slot and reads the provider itself, where a TS tune on the same channel, while it is not running, still gets its 302 | `relay/httpapi/stream.go:⟨startTune's Redirect arm⟩` | `relay/httpapi/hls_test.go::TestARedirectChannelIsServedOverHLSAsProxy`, `e2e/tests/streaming/hls-entry.spec.ts::a Redirect-profile channel is served over HLS through the relay` | Phase 4a-1b (spec D13, R23). HLS is made from bytes the relay holds; a 302 to an endless provider TS is what AVPlayer cannot play (ADR 0008). |
+| 43 | Live HLS media playlists conform and their segments stay fetchable: `VERSION:7`, `TARGETDURATION:2`, `INDEPENDENT-SEGMENTS`, `EXT-X-PROGRAM-DATE-TIME` on every segment, at most 10 listed and at least 6 once the channel has run 12 s, a media sequence that only advances; `Cache-Control: no-cache` and a `Last-Modified` from the newest segment; and a segment that leaves the list stays in the store for its duration plus the playlist's | `relay/hls/store.go:⟨StoreSegments, publish, MediaPlaylist⟩`, `relay/httpapi/hls.go:⟨the media-playlist branch⟩` | `relay/hls/store_test.go::TestARemovedSegmentStaysAvailableForItsDurationPlusThePlaylists`, `relay/hls/store_test.go::TestTheMediaPlaylist`, `relay/httpapi/hls_test.go::TestAMediaPlaylistWaitsForItsFirstSegmentAndCarriesItsHeaders`, `e2e/tests/streaming/hls-playlists.spec.ts::a media playlist conforms and its init and segments parse` | Phase 4a-1b (spec D7, § Session resources; ruling R44 for the store's 21, RFC 8216 § 6.2.2). Apple 8.4, 8.11 (the 6-segment minimum), 8.24, 9.11-9.12. |
+| 44 | A failed HLS output marks the channel, not a pipeline: its sessions become STOPPED, its pipeline is torn down, and new HLS entries answer 502 until the channel's next source boundary, which only clears the mark and starts nothing; the channel and its TS clients are unaffected | `relay/channel/hlsoutput.go:⟨AttachHLS, FailHLS, clearHLSFailed⟩`, `relay/channel/boundary.go:⟨markBoundary⟩`, `relay/httpapi/hls.go:⟨watchHLS⟩` | `relay/httpapi/hls_test.go::TestAFailedHLSOutputRefusesEntriesUntilTheNextBoundaryAndStartsNothingThere` | Phase 4a-1b (spec § Encoder argv, failure; R19: a TS-only channel starts no encode, so the boundary only clears). The 502's body names the reason: `no video stream in the source` for `hls.ErrNoVideo`, `HLS output failed` otherwise. |
 <!-- end of matrix -->
diff --git a/e2e/COVERAGE.md b/e2e/COVERAGE.md
index 916370d..f61a8a2 100644
--- a/e2e/COVERAGE.md
+++ b/e2e/COVERAGE.md
@@ -207,6 +207,12 @@ resolve (see the G8/G10 Gap rows).
 | Upstream | **Gap, `e2e-upstream`'s scope:** the provider's `ScenarioLog` records `method`, `path` and `status` but no request headers (`e2e-upstream/src/server.ts:logRequest`), so nothing Dispatcharr sends upstream as a `User-Agent` — including `stream_settings.default_user_agent`, the unowned-`CoreSettings` gap above — is observable through it. Closing it is one field on the log entry | G14 | todo |
 | Sources | **Gap:** the bulk-path fuzzy "no match" characterization test (would have been test 8) was implemented, its own assertions and the file's typecheck passed, and it was cut before shipping — see `epg-matching.spec.ts`'s header. Mechanism: `_active_epg_fuzzy_queryset` admits every active source's `EPGData` with no scoping to the test's own source; two `seed.channel()`/`seed.generatedName('epg')`-shaped names (worker/run/test-id digits, stripped to nothing by `normalize_name`) share enough character-level structure to land inside the bulk path's `[50, 80)` ML band by coincidence — measured at fuzzy 56.91 against a leftover row from an unrelated `epg-ingest.spec.ts` run — triggering `get_sentence_transformer()` and a real ~88 MB model download, then matching the two unrelated generated names via the ML "desperate last resort" branch at cosine 0.91 (the aggressive-ML finding, folded in here rather than filed separately). The test's own ws-based settle signal also resolved before the ML-delayed match actually committed — a second, independent defect in the test design, not just in the pair choice. What a future owner needs: a fixture-scoped way to deactivate other sources during the test, or a dedicated single-worker project. G14's own shipped tests 6, 7, 10, 11, 12 and 13 each leave behind an active upstream EPG source with a generated-shape `EPGData` name of exactly this kind — six more candidates per run for the next test that lands in this band by coincidence, not just the one leftover row measured above | G14 | todo |
 | Upstream | Phase 4a codec fixtures: six named looping TS assets (`mpeg2-576i-mp2`, `h264-1080i-aac-ac3`, `hevc-aac`, `h264-gop10-aac`, `h264-eac3`, `h264-noaudio`) beside the default `loop`, and a scenario channel's optional `asset` field choosing one. Each fixture's streams, PIDs and keyframe spacing are a `CONTRACT.md` guarantee, checked by `scripts/make-asset.sh` at image build; the field, the routing and the name list are covered by `e2e-upstream`'s vitest suite. No E2E spec consumes them yet: 4a-1b onwards does | 4a-0 | done |
+| Streaming | Live HLS entry (Phase 4a-1b): an `hls` tune answers a multivariant playlist, not bytes, on all three entry forms — `/proxy/ts/stream/<uuid>?output_format=hls`, `/live/<u>/<p>/<id>.m3u8` and the bare `/<u>/<p>/<id>.m3u8` — with `application/vnd.apple.mpegurl`, `Cache-Control: no-store` and every URI under `/hls/<token>/`; `player_api.php` advertises `m3u8`, `get.php?output=m3u8` emits `.m3u8` URLs, and `/api/mino/capabilities/` answers anonymously. A Redirect-profile channel is served over HLS through the relay (spec D13). `tests/streaming/hls-entry.spec.ts` | 4a-1b | done |
+| Streaming | Live HLS playlists per codec fixture: the audio groups and `CODECS` of the multivariant on `h264-eac3` (three groups, `mp4a.40.2`, `ac-3`, `ec-3`), `h264-noaudio` (one `aac` group, relay-synthesised silence), `mpeg2-576i-mp2` (720×576, `FRAME-RATE=50.000`, `aac` only) and `h264-1080i-aac-ac3` (1920×1080 at 50, `aac` and `ac3`); a media playlist conforms (`VERSION:7`, `TARGETDURATION:2`, `INDEPENDENT-SEGMENTS`, PDT on every segment, at least 6 listed, the media sequence advancing across reloads), and an init segment and two media segments parse in TypeScript with the durations their `EXTINF` claims and no edit list. `tests/streaming/hls-playlists.spec.ts` | 4a-1b | done |
+| Streaming | Live HLS sessions: a tampered token, a left session and a client stopped through `/proxy/ts/stop_client/` are refused 403; a session on a stopped channel is refused 410 once and 403 after; `/proxy/ts/status/<uuid>` lists an `hls` client that disappears at once on `DELETE /hls/<token>` beside a TS client that stays, with no wait for the idle timeout. `tests/streaming/hls-sessions.spec.ts` | 4a-1b | done |
+| Streaming | Live HLS failover: an upstream fault on `h264-1080i-aac-ac3` switches the channel to an alternate carrying `mpeg2-576i-mp2`, and the next media playlist carries `EXT-X-DISCONTINUITY` and a new `EXT-X-MAP` with the media sequence continuing and the multivariant's `CODECS` unchanged. `tests/streaming/hls-failover.spec.ts` | 4a-1b | done |
+| Streaming | **Observation (spec Q6, ruling R29), measured on CI's software encoder, not a gate:** the failover gap from the switch (the first status poll naming the alternate) to the new generation's first segment was ⟨Q6: min-max s over the PR's CI runs⟩; the software transcode of `h264-1080i-aac-ac3` (1080i → 1080p50, libx264) published ⟨R29: segments per wall-clock second, as a fraction of real time⟩ over a 40 s window under the `streaming` project's two workers. ⟨If R29 is below 1.0: "below real time — raised as finding #N"⟩. `tests/streaming/hls-failover.spec.ts`, `tests/streaming/hls-realtime.spec.ts` | 4a-1b | done |
+| Streaming | **Gap, pinned in Go only:** idle departure (`max(12 s, 6 × TARGETDURATION)`), the resume within 300 s, the sweeper's removals and the self-stop paths are pinned by `relay/session` and `relay/httpapi` tests with an injected clock and a stand-in encoder, never by an E2E that waits out a timeout (ruling R24). No E2E plays HLS in a browser or in AVPlayer: hls.js is 4a-2's `frontend` project, and AVPlayer is the manual gate recorded in the 4a-1b PR body (spec § Testing and gates). | 4a-1b | done |
 
 The ten G1 rows above are covered by these specs (the two seeding rows
 share one file, as do the two principal rows):
diff --git a/e2e/fixtures/types.ts b/e2e/fixtures/types.ts
index 442b54b..c5105b7 100644
--- a/e2e/fixtures/types.ts
+++ b/e2e/fixtures/types.ts
@@ -509,6 +509,13 @@ export type ChannelStatus = {
   width?: string;
   height?: string;
   video_bitrate?: string;
+  /**
+   * Phase 4a-1b: present only while the channel runs an HLS pipeline.
+   * `hls_encoder` is `'qsv'` or `'software'` once the first generation has
+   * chosen its engine; `hls_generation` is the current generation number.
+   */
+  hls_encoder?: 'qsv' | 'software';
+  hls_generation?: number;
 };
 
 /* ------------------------------------------------------------------------ *
diff --git a/e2e/tests/guards/parity-matrix.ts b/e2e/tests/guards/parity-matrix.ts
index 76763c5..d0298a8 100644
--- a/e2e/tests/guards/parity-matrix.ts
+++ b/e2e/tests/guards/parity-matrix.ts
@@ -592,7 +592,7 @@ export const WHITE_BOX_ONLY: readonly WhiteBoxRow[] = [
  * close a row** — rows are added only by a deliberate extension of the matrix,
  * which is exactly the edit that should take two places and a stated reason.
  */
-export const HIGHEST_ROW_ID = 36;
+export const HIGHEST_ROW_ID = 44;
 
 /**
  * Gate 1's own switch. Flipped to `true` by the PR that closes the last owed
diff --git a/e2e/tests/streaming-greybox/nginx-stream-buffering.spec.ts b/e2e/tests/streaming-greybox/nginx-stream-buffering.spec.ts
index 64fc776..2d3f94f 100644
--- a/e2e/tests/streaming-greybox/nginx-stream-buffering.spec.ts
+++ b/e2e/tests/streaming-greybox/nginx-stream-buffering.spec.ts
@@ -122,6 +122,15 @@ function parseLocationBlocks(config: string): LocationBlock[] {
  * the server block declares -- and a config that pastes the working uwsgi
  * block and changes only _pass passes every other assertion here while
  * reporting nginx's own address as every viewer's ip_address.
+ *
+ * Phase 4a-1b adds a third kind of location, pinned by the fifth test: the
+ * HLS session resources under `^~ /hls/`. They are Go-bound and unbuffered
+ * like the byte-path locations, but run NO hop, like `^~ /proxy/relay/`:
+ * the media-session token in the path is their whole authorization, which
+ * the relay verifies (Phase 4 spec D3, ruling R13). So `/hls/` joins neither
+ * `PROXY_BOUND_TARGETS` (the first test filters by its own list, so both
+ * halves stay exact) nor `RELAY_BOUND_TARGETS` (the second requires the hop
+ * on every member).
  */
 
 /**
@@ -575,3 +584,82 @@ test(
     ).toBe(true);
   }
 );
+
+/**
+ * The HLS session resources (Phase 4a-1b, Phase 4 spec D3): media
+ * playlists, init and media segments under `/hls/<token>/...`, and
+ * `DELETE /hls/<token>`. A list rather than a bare string so the set
+ * assertion below fails on a lost or duplicated block, as the first test's
+ * do.
+ */
+const TOKEN_BOUND_TARGETS = ['/hls/'];
+
+test(
+  'the HLS session resources reach the relay unbuffered and run no authorize hop',
+  { tag: '@contract' },
+  async () => {
+    const { stdout } = await execFileAsync('docker', ['exec', CONTAINER_NAME, 'nginx', '-T']);
+    const blocks = parseLocationBlocks(stdout);
+    const found = blocks.filter((b) => TOKEN_BOUND_TARGETS.includes(b.target));
+    expect(
+      found.map((b) => b.target).sort(),
+      `expected the token-bound location(s) ${TOKEN_BOUND_TARGETS.join(', ')} in nginx -T's ` +
+        `output; found blocks: ${blocks.map((b) => b.header).join(', ')}`
+    ).toEqual([...TOKEN_BOUND_TARGETS].sort());
+
+    for (const block of found) {
+      const has = (re: RegExp) => block.body.some((line) => re.test(line));
+      const body = block.body.join('\n');
+
+      // Relay-bound, by the same literal group as the byte-path locations.
+      expect(
+        has(/^\s*proxy_pass\s+http:\/\/relay_go\s*;/),
+        `location "${block.header}" must proxy_pass to relay_go:\n${body}`
+      ).toBe(true);
+
+      // A media segment runs to megabytes; buffered, nginx would spool it.
+      expect(
+        has(/^\s*proxy_buffering\s+off\s*;/),
+        `location "${block.header}" does not set proxy_buffering off:\n${body}`
+      ).toBe(true);
+
+      // The token is the whole gate (R13): the hop must not sit in front of
+      // it, or every segment asks Django -- and a URI that names no channel
+      // would 404 in authorize_stream() anyway.
+      expect(
+        has(/^\s*auth_request\s+\//),
+        `location "${block.header}" must not run the authorize subrequest:\n${body}`
+      ).toBe(false);
+
+      // A player fetches these as an ordinary client; `internal;` would 404
+      // every one of them.
+      expect(
+        has(/^\s*internal\s*;/),
+        `location "${block.header}" must not be internal:\n${body}`
+      ).toBe(false);
+
+      // A client-supplied X-Relay-* or trust marker never reaches the relay.
+      expect(
+        has(/dispatcharr_api_params_proxy\.conf\s*;/),
+        `location "${block.header}" must blank the trust params:\n${body}`
+      ).toBe(true);
+
+      expect(
+        has(/^\s*proxy_http_version\s+1\.1\s*;/),
+        `location "${block.header}" does not set proxy_http_version 1.1:\n${body}`
+      ).toBe(true);
+
+      // Above the relay's own 20 s waits (the entry's init wait, a media
+      // playlist's first-segment wait), and the byte-path locations' own
+      // connect budget rather than the server block's inherited 75.
+      expect(
+        has(/^\s*proxy_read_timeout\s+60s\s*;/),
+        `location "${block.header}" does not set proxy_read_timeout 60s:\n${body}`
+      ).toBe(true);
+      expect(
+        has(/^\s*proxy_connect_timeout\s+60s\s*;/),
+        `location "${block.header}" does not set proxy_connect_timeout 60s:\n${body}`
+      ).toBe(true);
+    }
+  }
+);
```
<!-- appendix-A-end -->
