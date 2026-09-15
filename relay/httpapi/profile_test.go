package httpapi

import (
	"encoding/json"
	"io"
	"net/http"
	"path/filepath"
	"strconv"
	"sync"
	"testing"
	"time"

	"github.com/D10Scot/Dispatcharr/relay/buffer"
	"github.com/D10Scot/Dispatcharr/relay/channel"
	"github.com/D10Scot/Dispatcharr/relay/control"
	"github.com/D10Scot/Dispatcharr/relay/internal/relaytest"
	"github.com/D10Scot/Dispatcharr/relay/output"
)

// transcodePID is the PID the stand-in transcode rewrites every packet to.
//
// IT IS WHAT MAKES "THE CLIENT READ THE TRANSCODE'S RING" OBSERVABLE. A
// pass-through stand-in copies its input, so a profile client's bytes and a
// plain client's bytes are identical and no assertion on them can fail --
// a fixture that patches away its own subject. Rewriting the PID keeps the
// output a valid, same-length transport stream and makes its provenance
// readable from any packet, which is what an Output Profile does in miniature:
// its fd 1 is not its fd 0.
const transcodePID = 0x1FF

// assetPID is the PID relaytest.SyntheticTS stamps on the channel's own
// stream, which fanRig builds its upstream from.
const assetPID = 0x100

// pidsIn reads the PID of every whole packet in data.
//
// THE TRAILING PARTIAL PACKET IS DROPPED RATHER THAN FAILED ON, because these
// bodies are read to a byte count and a reader that stops mid-packet is the
// reader's own boundary and not a misalignment of the stream. Every whole
// packet is still checked for its sync byte, which is the alignment claim
// rows 7 and 9 pin and which relaytest.AlignmentProblem would make on a body
// that happened to end on a boundary and miss on every body that did not.
func pidsIn(t *testing.T, data []byte) map[int]int {
	t.Helper()
	whole := (len(data) / relaytest.PacketSize) * relaytest.PacketSize
	if whole == 0 {
		t.Fatalf("the client received %d bytes, which is less than one packet", len(data))
	}
	counts := map[int]int{}
	for offset := 0; offset < whole; offset += relaytest.PacketSize {
		packet := data[offset : offset+relaytest.PacketSize]
		if packet[0] != relaytest.SyncByte {
			t.Fatalf("byte %d is %#02x, not the sync byte %#02x: the client's stream is misaligned",
				offset, packet[0], relaytest.SyncByte)
		}
		counts[relaytest.PacketPID(packet)]++
	}
	return counts
}

// standInProfileArgv is an Output Profile whose built command line spawns this
// test binary as a pass-through: `-i pipe:0` makes RunStandIn copy fd 0 to
// fd 1, which is structurally what an Output Profile does (raw MPEG-TS in on
// pipe:0, MPEG-TS out on pipe:1 -- core/models.py:173-174).
//
// COMMAND FIRST, as OutputProfileRefSerializer sends it
// (apps/proxy/serializers.py:230, and the literal in
// apps/proxy/tests/test_next_source_api.py:551). A fixture that sent the
// stream_profile shape instead would spawn the wrong argv and this file's
// tests would fail for a reason that is not their subject.
func standInProfileArgv(t *testing.T, args ...string) []string {
	t.Helper()
	t.Setenv(relaytest.StandInEnv, "1")
	command, argv := relaytest.StandInCommand(
		append(args, "--ts-pid", strconv.Itoa(transcodePID), "-i", "pipe:0")...)
	return append([]string{command}, argv...)
}

// profileRig is fanRig with one active Output Profile on the next-source
// answer.
func profileRig(t *testing.T, id string, entry relaytest.OutputProfileConfig, up relaytest.Config, overrides map[string]any) *rig {
	t.Helper()
	return fanRigWith(t, relaytest.ControlPlaneConfig{
		OutputProfiles: map[string]relaytest.OutputProfileConfig{id: entry},
	}, up, overrides)
}

// tuneProfile opens a stream under an Output Profile, the way the authorize
// hop opens one: X-Relay-Output carries the id apps/proxy/authorize.py:483-488
// resolved. It returns the response without asserting its status, so a caller
// whose subject IS the status can read it.
func (r *rig) tuneProfile(t *testing.T, channelID, clientID, profileID, format string) *http.Response {
	t.Helper()
	header := http.Header{}
	header.Set(control.HeaderAuthorized, control.RelayTrustToken(testSecret))
	header.Set("X-Relay-Channel", channelID)
	header.Set("X-Relay-Client", clientID)
	header.Set("X-Relay-Client-IP", "198.51.100.4")
	header.Set("X-Relay-User", "7")
	header.Set("X-Relay-Output", profileID)
	if format != "" {
		header.Set("X-Relay-Output-Format", format)
	}
	return r.tune(t, "/proxy/ts/stream/"+channelID, header)
}

// PARITY-MATRIX ROW 11: one transcode process per active (channel, profile)
// pair, whatever the client count. "Ten AC3 clients cost one ffmpeg."
//
// COUNTED BY SPAWNS, NOT BY REGISTRY ENTRIES, which is Global Constraint 35
// and the reason this test can fail at all. A relay that started a SECOND
// transcode per client and overwrote its map entry satisfies "the registry
// holds one pipeline" while leaking a process; the spawn log answers "how many
// processes were started" directly. It is
// apps/proxy/live_proxy/tests/output_support.py:83's spawn_logging_standin and
// :111's spawn_count in Go, and the Python pin it mirrors is
// test_output_profile_sharing.py::OutputProfileSharingTests::
// test_two_clients_on_one_output_profile_share_a_single_transcode.
func TestTwoClientsOnOneOutputProfileShareOneTranscode(t *testing.T) {
	log := filepath.Join(t.TempDir(), "profile-spawns.log")
	r := profileRig(t, "3", relaytest.OutputProfileConfig{
		ID:   3,
		Argv: standInProfileArgv(t, "--spawn-log", log),
	}, relaytest.Config{Rate: 4}, nil)

	first := r.tuneProfile(t, "c-share-profile", "client-a", "3", "")
	defer func() { _ = first.Body.Close() }()
	if first.StatusCode != http.StatusOK {
		t.Fatalf("the first profile tune answered %d, want 200", first.StatusCode)
	}
	firstBytes := readAtLeast(first.Body, 20*buffer.TSPacketSize, 15*time.Second)
	if len(firstBytes) < 20*buffer.TSPacketSize {
		t.Fatalf("the first client received %d bytes, want at least 20 packets", len(firstBytes))
	}
	if got := pidsIn(t, firstBytes); got[transcodePID] == 0 || got[assetPID] != 0 {
		t.Fatalf("the first client's packets carry PIDs %v, want only the transcode's %#x", got, transcodePID)
	}

	second := r.tuneProfile(t, "c-share-profile", "client-b", "3", "")
	defer func() { _ = second.Body.Close() }()
	if second.StatusCode != http.StatusOK {
		t.Fatalf("the second profile tune answered %d, want 200", second.StatusCode)
	}
	secondBytes := readAtLeast(second.Body, 20*buffer.TSPacketSize, 15*time.Second)
	if len(secondBytes) < 20*buffer.TSPacketSize {
		t.Fatalf("the second client received %d bytes, want at least 20 packets", len(secondBytes))
	}
	// BOTH CLIENTS ARE READING THE TRANSCODE, which is what "share" means. A
	// second client silently served the channel's own ring would also produce
	// one spawn.
	if got := pidsIn(t, secondBytes); got[transcodePID] == 0 || got[assetPID] != 0 {
		t.Fatalf("the second client's packets carry PIDs %v, want only the transcode's %#x", got, transcodePID)
	}

	if got := relaytest.SpawnCount(log); got != 1 {
		t.Fatalf("the relay spawned %d transcodes for two clients on one Output Profile, want 1", got)
	}

	// Complementary, not redundant, and in the same spirit as the Python
	// test's own second assertion: the key it is registered under is the one
	// output/profile/manager.py builds for itself.
	ch := r.Manager.Get("c-share-profile")
	if ch == nil {
		t.Fatal("the channel is gone")
	}
	if formats := ch.OutputFormats(); len(formats) != 1 || formats[0] != "mpegts:p3" {
		t.Fatalf("the channel's output registry holds %v, want exactly one mpegts:p3", formats)
	}
	if got := ch.Clients(); got != 2 {
		t.Fatalf("the channel has %d clients, want 2", got)
	}
	// ONE UPSTREAM AND ONE next-source FOR BOTH, which is what makes the
	// single transcode a SHARING claim rather than a coincidence of two
	// separate channels.
	if got := r.Upstream.Requests(); got != 1 {
		t.Fatalf("the provider saw %d requests, want 1", got)
	}
	if got := len(r.Control.RequestsTo("/next-source")); got != 1 {
		t.Fatalf("the relay made %d next-source calls, want 1", got)
	}
}

// A PROFILE CLIENT READS THE TRANSCODE'S RING AND A PLAIN CLIENT READS THE
// CHANNEL'S, on one channel and one upstream: views.py:773-776's get_buffer
// (channel, profile) is the only thing that differs between them.
//
// PROVED IN THE BYTES, through the PID the stand-in transcode rewrites: the
// profile client's packets carry the transcode's PID and the plain client's
// carry the asset's. Without that rewrite a pass-through stand-in would make
// the two streams identical and the assertion could not fail -- see
// transcodePID above.
func TestAProfileClientAndAPlainClientShareOneUpstream(t *testing.T) {
	log := filepath.Join(t.TempDir(), "profile-spawns.log")
	r := profileRig(t, "3", relaytest.OutputProfileConfig{
		ID:   3,
		Argv: standInProfileArgv(t, "--spawn-log", log),
	}, relaytest.Config{Rate: 4}, nil)

	plain := r.tuneAs(t, "c-mixed-profile", "client-plain")
	defer func() { _ = plain.Body.Close() }()
	waitForHead(t, r, "c-mixed-profile", 1)

	profiled := r.tuneProfile(t, "c-mixed-profile", "client-profile", "3", "")
	defer func() { _ = profiled.Body.Close() }()
	if profiled.StatusCode != http.StatusOK {
		t.Fatalf("the profile tune answered %d, want 200", profiled.StatusCode)
	}
	profiledBytes := readAtLeast(profiled.Body, 20*buffer.TSPacketSize, 15*time.Second)
	if len(profiledBytes) < 20*buffer.TSPacketSize {
		t.Fatalf("the profile client received %d bytes, want at least 20 packets", len(profiledBytes))
	}
	plainBytes := readAtLeast(plain.Body, 20*buffer.TSPacketSize, 15*time.Second)
	if len(plainBytes) < 20*buffer.TSPacketSize {
		t.Fatalf("the plain client received %d bytes, want at least 20 packets", len(plainBytes))
	}

	// THE TWO ASSERTIONS ARE OPPOSITE HALVES OF ONE CLAIM, and both are made:
	// a relay that sent every client the transcode's ring would pass the first
	// and fail the second, and one that ignored the profile entirely -- which
	// is the defect this whole PR could regress into -- fails the first.
	if got := pidsIn(t, profiledBytes); got[transcodePID] == 0 || got[assetPID] != 0 {
		t.Fatalf("the profile client's packets carry PIDs %v, want only the transcode's %#x", got, transcodePID)
	}
	if got := pidsIn(t, plainBytes); got[assetPID] == 0 || got[transcodePID] != 0 {
		t.Fatalf("the plain client's packets carry PIDs %v, want only the asset's %#x", got, assetPID)
	}

	if got := relaytest.SpawnCount(log); got != 1 {
		t.Fatalf("the relay spawned %d transcodes, want 1: the plain client must not have one", got)
	}
	if got := r.Upstream.Requests(); got != 1 {
		t.Fatalf("the provider saw %d requests, want 1: the two clients share one upstream", got)
	}
}

// AN fMP4 CLIENT ON AN OUTPUT PROFILE RUNS TWO PROCESSES, CHAINED, and that is
// Python's composition rather than a choice here. views.py runs
// ensure_output_profile first (:765-767), resolves get_buffer(channel,
// profile) second (:773-776), and hands THAT buffer to ensure_output_format as
// the remux's source under the compound key f'fmp4:p{id}' (:731-734, :790-792).
// So the transcode writes a TS ring under `mpegts:p3` and the remux reads it
// and writes fragments under `fmp4:p3`.
//
// TWO SPAWNS AND TWO REGISTRY KEYS ARE BOTH ASSERTED, because either alone is
// satisfiable by the wrong thing: two spawns with one key would be a leak, and
// two keys with one spawn would mean a pipeline that never started.
func TestAnFMP4ClientOnAnOutputProfileRunsTheTranscodeAndTheRemuxChained(t *testing.T) {
	dir := t.TempDir()
	transcodeLog := filepath.Join(dir, "transcode-spawns.log")
	remuxLog := filepath.Join(dir, "remux-spawns.log")
	// WHAT THE REMUX WAS FED, which nothing else here can see: the stand-in
	// remux writes synthetic fMP4 and IGNORES its input, so without this the
	// chained test passes whether the remux read the transcode's ring or the
	// channel's -- a fixture that patches away its own subject. Demonstrated:
	// the break-check that dropped Source from the remux's OutputSpec stayed
	// GREEN until this file was added.
	remuxInput := filepath.Join(dir, "remux-stdin-pid")
	r := fanRigWith(t, relaytest.ControlPlaneConfig{
		OutputProfiles: map[string]relaytest.OutputProfileConfig{
			"3": {ID: 3, Argv: standInProfileArgv(t, "--spawn-log", transcodeLog)},
		},
	}, relaytest.Config{Rate: 4}, nil,
		withRemux(standInRemux(t, "--spawn-log", remuxLog, "--stdin-pid-log", remuxInput,
			"--fmp4-fragments", "60", "--fmp4-interval", "0.02")))

	response := r.tuneProfile(t, "c-chained", "client-a", "3", output.FormatFMP4)
	defer func() { _ = response.Body.Close() }()
	if response.StatusCode != http.StatusOK {
		t.Fatalf("the fMP4 profile tune answered %d, want 200", response.StatusCode)
	}
	if got := response.Header.Get("Content-Type"); got != ContentTypeFMP4 {
		t.Fatalf("the Content-Type is %q, want %q", got, ContentTypeFMP4)
	}
	body := readAtLeast(response.Body, len(relaytest.SyntheticFMP4Init()), 15*time.Second)
	if len(body) == 0 {
		t.Fatal("the chained client received no bytes at all")
	}
	if problem := relaytest.FMP4ShapeProblem(body); problem != "" && len(body) > 2*len(relaytest.SyntheticFMP4Init()) {
		t.Fatalf("the chained client's bytes are not fMP4: %s", problem)
	}

	ch := r.Manager.Get("c-chained")
	if ch == nil {
		t.Fatal("the channel is gone")
	}
	keys := map[string]bool{}
	for _, key := range ch.OutputFormats() {
		keys[key] = true
	}
	if len(keys) != 2 || !keys["mpegts:p3"] || !keys["fmp4:p3"] {
		t.Fatalf("the channel's output registry holds %v, want exactly mpegts:p3 and fmp4:p3", ch.OutputFormats())
	}
	if got := relaytest.SpawnCount(transcodeLog); got != 1 {
		t.Fatalf("the relay spawned %d Output Profile transcodes, want 1", got)
	}
	if got := relaytest.SpawnCount(remuxLog); got != 1 {
		t.Fatalf("the relay spawned %d remuxes, want 1", got)
	}
	// AND THE CHAIN RUNS IN THE RIGHT ORDER: the remux's fd 0 carries the
	// TRANSCODE's packets, not the channel's. views.py:790-792 hands
	// ensure_output_format the profile's buffer as source_buffer, and this is
	// the only thing that can tell whether that happened.
	deadline := time.Now().Add(15 * time.Second)
	for relaytest.StdinPacketPID(remuxInput) == -1 && time.Now().Before(deadline) {
		time.Sleep(20 * time.Millisecond)
	}
	switch got := relaytest.StdinPacketPID(remuxInput); got {
	case transcodePID:
	case -1:
		t.Fatal("the remux read no transport-stream packet at all on fd 0 within fifteen seconds")
	default:
		t.Fatalf("the remux's fd 0 carried PID %#x, want the transcode's %#x (the channel's own ring is %#x): "+
			"the fMP4 remux must read the Output Profile's output, not the channel's", got, transcodePID, assetPID)
	}
}

// THE LIST PAYLOAD NAMES THE PROFILE THE CLIENT IS ACTUALLY BEING SERVED
// UNDER. channel_status.py:579-582 sets output_profile_id on BOTH branches, so
// the key is never absent -- null for a client with no profile, the integer id
// for one with.
//
// ASSERTED ON THE LIVE ENDPOINT, not on the golden fixture, for 2c-6's Ruling
// R11 reason: the golden already carries an integer and a null on its two
// clients, so it pins the SERIALIZER and pins nothing about whether a real
// tune puts the id in the registry. That is a property of identify and the
// handler.
func TestTheListPayloadNamesEachClientsOwnOutputProfile(t *testing.T) {
	r := profileRig(t, "3", relaytest.OutputProfileConfig{
		ID:   3,
		Argv: standInProfileArgv(t),
	}, relaytest.Config{Rate: 4}, nil)

	plain := r.tuneAs(t, "c-listed-profile", "client-plain")
	defer func() { _ = plain.Body.Close() }()
	profiled := r.tuneProfile(t, "c-listed-profile", "client-profile", "3", "")
	defer func() { _ = profiled.Body.Close() }()
	if profiled.StatusCode != http.StatusOK {
		t.Fatalf("the profile tune answered %d, want 200", profiled.StatusCode)
	}
	if got := readAtLeast(profiled.Body, buffer.TSPacketSize, 15*time.Second); len(got) == 0 {
		t.Fatal("the profile client received no bytes")
	}

	status, body := r.listChannels(t, "?clients=all")
	if status != http.StatusOK {
		t.Fatalf("the list endpoint answered %d, want 200", status)
	}
	var payload channelListPayload
	if err := json.Unmarshal(body, &payload); err != nil {
		t.Fatalf("parsing the list payload: %v", err)
	}
	seen := map[string]*int{}
	for _, ch := range payload.Channels {
		for _, client := range ch.Clients {
			seen[client.ClientID] = client.OutputProfileID
		}
	}
	if got := seen["client-profile"]; got == nil || *got != 3 {
		t.Fatalf("the profile client is listed with output_profile_id %v, want 3", got)
	}
	if got := seen["client-plain"]; got != nil {
		t.Fatalf("the plain client is listed with output_profile_id %v, want null", *got)
	}
	// AND THE KEY IS PRESENT ON BOTH, which is the half a value check misses:
	// channel_status.py sets it on both branches, so a relay that omitted it
	// for the plain client would render a payload Django never produces.
	raw := map[string]any{}
	if err := json.Unmarshal(body, &raw); err != nil {
		t.Fatalf("re-parsing the list payload: %v", err)
	}
	channels, _ := raw["channels"].([]any)
	for _, entry := range channels {
		object, _ := entry.(map[string]any)
		clients, _ := object["clients"].([]any)
		for _, c := range clients {
			row, _ := c.(map[string]any)
			if _, present := row["output_profile_id"]; !present {
				t.Fatalf("a client row has no output_profile_id key at all: %v", row)
			}
		}
	}
}

// A PROFILE DEACTIVATED BETWEEN THE AUTHORIZE HOP AND THE TUNE IS SERVED
// WITHOUT ONE, and the client's registry row says null.
//
// Python's own behaviour and not a fallback invented here: the hop resolved
// the id with is_active=True (apps/proxy/authorize.py:203-222) and put it in
// X-Relay-Output; views.py:150-155 then re-reads the row with is_active=True
// and gets None, and :725-751 registers the client with that None and serves
// it plain TS. The Go relay reaches the same answer because the deactivated
// profile is no longer in the next-source map.
func TestAProfileMissingFromTheAnswerIsServedWithoutOne(t *testing.T) {
	// An answer carrying a DIFFERENT active profile, so the map is known and
	// non-empty and the only thing missing is the one this tune names -- a
	// fixture with an empty map would also pass a relay that treated "no
	// profiles at all" as its own special case.
	r := profileRig(t, "8", relaytest.OutputProfileConfig{
		ID:   8,
		Argv: standInProfileArgv(t),
	}, relaytest.Config{Rate: 4}, nil)

	response := r.tuneProfile(t, "c-gone", "client-a", "3", "")
	defer func() { _ = response.Body.Close() }()
	if response.StatusCode != http.StatusOK {
		t.Fatalf("a tune naming a deactivated profile answered %d, want 200", response.StatusCode)
	}
	served := readAtLeast(response.Body, 20*buffer.TSPacketSize, 15*time.Second)
	if len(served) < 20*buffer.TSPacketSize {
		t.Fatalf("the client received %d bytes, want the channel's own stream", len(served))
	}
	if got := pidsIn(t, served); got[assetPID] == 0 || got[transcodePID] != 0 {
		t.Fatalf("the client's packets carry PIDs %v, want only the asset's %#x: no transcode should exist", got, assetPID)
	}

	ch := r.Manager.Get("c-gone")
	if ch == nil {
		t.Fatal("the channel is gone")
	}
	if got := ch.OutputFormats(); len(got) != 0 {
		t.Fatalf("the channel runs output pipelines %v for a profile that is not active", got)
	}
	clients := ch.ClientSnapshot()
	if len(clients) != 1 {
		t.Fatalf("the channel has %d clients, want 1", len(clients))
	}
	if clients[0].OutputProfileID != nil {
		t.Fatalf("the client is registered with output_profile_id %d, want null: the profile it named is not active",
			*clients[0].OutputProfileID)
	}
}

// THE DEACTIVATED-PROFILE CORRECTION DOES NOT RACE THE LIST ENDPOINT, which is
// the one place this PR writes to a *channel.Client the channel already holds.
//
// FOUND BY REVIEW, NOT BY DESIGN. attachOutputProfile's not-found arm corrects
// the client's registry row to null, and an earlier draft did it twice -- once
// through Channel.SetClientOutputProfile, which takes the channel's write lock,
// and once as a bare `client.OutputProfileID = nil` on the struct the caller
// already holds. The second looks free: same field, same value, a pointer this
// goroutine created. It is a data race, because Attach put that pointer in the
// channel's registry and ClientSnapshot reads the field under RLock. `-race`
// reported it as a write at httpapi/profile.go against a read at
// channel/channel.go's ClientSnapshot.
//
// THE ASSERTION IS THE REGISTRY VALUE, NOT "NO RACE". A test whose only oracle
// is the detector passes on any run where the two goroutines happen not to
// overlap, which is the "silence read as pass" shape. So this asserts what the
// correction is FOR -- the client ends up listed with a null profile -- and the
// detector is what makes the concurrent reader worth having. Run it with
// -race or it pins only the value.
func TestTheDeactivatedProfileCorrectionDoesNotRaceTheListEndpoint(t *testing.T) {
	// An answer carrying a DIFFERENT active profile, so the map is known and
	// non-empty and the only thing missing is the one this tune names -- the
	// arm that performs the correction.
	r := profileRig(t, "8", relaytest.OutputProfileConfig{
		ID:   8,
		Argv: standInProfileArgv(t),
	}, relaytest.Config{Rate: 4}, nil)

	// A reader hammering ClientSnapshot for the whole of the tune, which is
	// the exact call GET /proxy/relay/channels?clients=all makes.
	stop := make(chan struct{})
	var readers sync.WaitGroup
	readers.Add(1)
	go func() {
		defer readers.Done()
		for {
			select {
			case <-stop:
				return
			default:
			}
			if ch := r.Manager.Get("c-race"); ch != nil {
				_ = ch.ClientSnapshot()
			}
		}
	}()

	response := r.tuneProfile(t, "c-race", "client-a", "3", "")
	defer func() { _ = response.Body.Close() }()
	close(stop)
	readers.Wait()

	if response.StatusCode != http.StatusOK {
		t.Fatalf("the tune answered %d, want 200", response.StatusCode)
	}
	ch := r.Manager.Get("c-race")
	if ch == nil {
		t.Fatal("the channel is gone")
	}
	clients := ch.ClientSnapshot()
	if len(clients) != 1 {
		t.Fatalf("the channel has %d clients, want 1", len(clients))
	}
	if clients[0].OutputProfileID != nil {
		t.Fatalf("the client is registered with output_profile_id %d, want null: "+
			"the profile it named is not in the answer's map", *clients[0].OutputProfileID)
	}
}

// A PROFILE DJANGO COULD NOT BUILD IS A 500 WITH views.py:771's OWN BODY.
//
// The wire says `argv: null`, which is _with_output_profiles reporting that
// shlex refused the profile's parameters -- a row OutputProfileSerializer
// validates nothing against, so it can already be in the database. Python
// reaches the same failure one statement later (build_command() raises inside
// stream_ts's try) and answers 500 too; the BODY diverges, because Python's
// carries shlex's message and this relay has never seen it.
func TestAProfileWhoseArgvDjangoCouldNotBuildIsAFiveHundred(t *testing.T) {
	r := profileRig(t, "3", relaytest.OutputProfileConfig{ID: 3, ArgvNull: true},
		relaytest.Config{Rate: 4}, nil)

	response := r.tuneProfile(t, "c-unbuildable", "client-a", "3", "")
	defer func() { _ = response.Body.Close() }()
	if response.StatusCode != http.StatusInternalServerError {
		t.Fatalf("a tune naming an unbuildable profile answered %d, want 500", response.StatusCode)
	}
	body, err := io.ReadAll(response.Body)
	if err != nil {
		t.Fatalf("reading the body: %v", err)
	}
	if string(body) != profileNotStartedBody {
		t.Fatalf("the 500 body is %q, want views.py:771's %q", body, profileNotStartedBody)
	}
}

// A TRANSCODE THAT CANNOT BE SPAWNED IS THE SAME 500, which is
// ensure_output_profile returning False (server.py:1532-1538, views.py:767-772)
// rather than build_command raising.
func TestATranscodeThatCannotBeSpawnedIsAFiveHundred(t *testing.T) {
	r := profileRig(t, "3", relaytest.OutputProfileConfig{
		ID:   3,
		Argv: []string{"/nonexistent/dispatcharr-transcode", "-i", "pipe:0"},
	}, relaytest.Config{Rate: 4}, nil)

	response := r.tuneProfile(t, "c-nospawn-profile", "client-a", "3", "")
	defer func() { _ = response.Body.Close() }()
	if response.StatusCode != http.StatusInternalServerError {
		t.Fatalf("a tune whose transcode could not be spawned answered %d, want 500", response.StatusCode)
	}
	body, _ := io.ReadAll(response.Body)
	if string(body) != profileNotStartedBody {
		t.Fatalf("the 500 body is %q, want views.py:771's %q", body, profileNotStartedBody)
	}
}

// A CONTROL PLANE THAT SENDS NO output_profiles AT ALL IS A CONTRACT MISMATCH,
// not "this deployment has no profiles".
//
// Django has sent the key on every answer since Phase 2 PR 2b-2 and sends an
// EMPTY OBJECT when nothing is active, which
// apps/proxy/tests/test_next_source_api.py::
// test_no_active_profiles_is_an_empty_object_not_a_missing_key pins. An absent
// key therefore means the relay is newer than the control plane, and serving
// the client plain TS would hand a device the wrong audio codec silently. 502,
// the same answer an absent proxy_settings key gets.
func TestATuneNamingAProfileAgainstAnOlderControlPlaneIsABadGateway(t *testing.T) {
	r := fanRigWith(t, relaytest.ControlPlaneConfig{OutputProfilesAbsent: true},
		relaytest.Config{Rate: 4}, nil)

	response := r.tuneProfile(t, "c-oldcp", "client-a", "3", "")
	defer func() { _ = response.Body.Close() }()
	if response.StatusCode != http.StatusBadGateway {
		t.Fatalf("a tune naming a profile against a control plane with no output_profiles answered %d, want 502",
			response.StatusCode)
	}

	// AND A TUNE THAT NAMES NO PROFILE IS UNAFFECTED, which is what stops this
	// from being a blanket refusal: an older control plane serves every
	// ordinary client exactly as before.
	plain := r.tuneAs(t, "c-oldcp", "client-plain")
	defer func() { _ = plain.Body.Close() }()
	if got := readAtLeast(plain.Body, buffer.TSPacketSize, 15*time.Second); len(got) == 0 {
		t.Fatal("a tune with no Output Profile received nothing against a control plane with no output_profiles")
	}
}

// THE PROFILE SET IS REFRESHED BY A FAILOVER'S next-source ANSWER, AND NOT BY
// A DEGRADED ONE. Ruling R5's mechanism, pinned in both directions.
//
// WHY IT NEEDS A TEST AT ALL. R5 argues the relay should refresh the cached set
// on every answer rather than snapshot it at channel start, because Python
// re-reads the OutputProfile row per client and a start-time snapshot would go
// stale for a channel's whole life. That argument is only worth anything if the
// refresh happens: deleting `channel/failover.go`'s two-line assignment left the
// ENTIRE suite green before this test existed, found by review.
//
// BOTH ARMS IN ONE TEST, deliberately. The refresh and its exception are one
// rule -- refresh from an answer, never from the cache -- and a test that only
// proved the first would pass a relay that refreshed from the degraded
// candidate list too, which is the failure R5 actually warns about: that list
// was cached at channel start and carries no profile set at all, so refreshing
// from it would clear the map rather than update it.
//
// The primary and the first alternate each stop after two chunks, so each is
// exhausted after three quick EOFs -- TestAFailoverFallsBackToTheCachedCandidates
// WhenTheControlPlaneIsDown's own fixture shape, for the same reason.
func TestAFailoverRefreshesTheProfileSetAndADegradedOneDoesNot(t *testing.T) {
	second := relaytest.NewUpstream(relaytest.Config{Payload: relaytest.SyntheticTS(rigAssetPackets, assetPID), StopAfterBytes: rigChunkBytes * 2})
	t.Cleanup(second.Close)
	third := relaytest.NewUpstream(relaytest.Config{Payload: relaytest.SyntheticTS(rigAssetPackets, assetPID)})
	t.Cleanup(third.Close)

	// At the tune, profile 3 is the only active one.
	cp := relaytest.ControlPlaneConfig{
		Alternates: []relaytest.AlternateConfig{
			{StreamID: 2, URL: second.URL()},
			{StreamID: 3, URL: third.URL()},
		},
		OutputProfiles: map[string]relaytest.OutputProfileConfig{
			"3": {ID: 3, Argv: standInProfileArgv(t)},
		},
	}
	r := fanRigWith(t, cp, relaytest.Config{Payload: relaytest.SyntheticTS(rigAssetPackets, assetPID), StopAfterBytes: rigChunkBytes * 2}, nil)

	response := r.tuneAs(t, "c-refresh", "client-a")
	defer func() { _ = response.Body.Close() }()
	waitForHead(t, r, "c-refresh", 1)

	ch := r.Manager.Get("c-refresh")
	if ch == nil {
		t.Fatal("the channel is gone")
	}
	if _, found := ch.OutputProfiles().Lookup("3"); !found {
		t.Fatal("the channel did not cache the tune's own profile set")
	}
	if _, found := ch.OutputProfiles().Lookup("9"); found {
		t.Fatal("the channel already holds profile 9, which no answer has carried")
	}

	// THE OPERATOR EDITS THE SET between answers: 3 is deactivated and 9
	// appears. Nothing tells the running channel; only its next answer can.
	r.Control.SetOutputProfiles(map[string]relaytest.OutputProfileConfig{
		"9": {ID: 9, Argv: standInProfileArgv(t)},
	})

	// The primary exhausts, the failover reaches Django, and the answer it
	// gets carries the NEW set.
	waitFor(t, "the failover to the second stream", 15*time.Second, func() bool { return second.Requests() >= 1 })
	deadline := time.Now().Add(15 * time.Second)
	for time.Now().Before(deadline) {
		if _, found := ch.OutputProfiles().Lookup("9"); found {
			break
		}
		time.Sleep(20 * time.Millisecond)
	}
	if _, found := ch.OutputProfiles().Lookup("9"); !found {
		t.Fatalf("the channel still holds %v after a failover whose answer carried profile 9: "+
			"the refresh at channel/failover.go did not happen", ch.OutputProfiles().ByID)
	}
	if _, found := ch.OutputProfiles().Lookup("3"); found {
		t.Fatal("the channel still holds profile 3: the set is REPLACED by an answer, not merged into")
	}

	// AND THE DEGRADED ARM. The control plane goes down, the second stream
	// exhausts, and the failover falls back to the candidate list cached at
	// channel start -- which carries no profile set. The channel must keep
	// the one it has rather than clear it.
	r.Control.SetStatus(http.StatusServiceUnavailable)
	waitFor(t, "the degraded failover to the third stream", 20*time.Second, func() bool { return third.Requests() >= 1 })
	if _, found := ch.OutputProfiles().Lookup("9"); !found {
		t.Fatalf("a DEGRADED failover cleared the profile set to %v: the cached candidate list "+
			"carries no answer, so Resolved.OutputProfiles.Known is false and the channel keeps what it had",
			ch.OutputProfiles().ByID)
	}
	if !ch.OutputProfiles().Known {
		t.Fatal("a degraded failover made the channel's set unknown, which would 502 every later profile tune")
	}
}

// THE LAST PROFILE CLIENT LEAVING STOPS THE TRANSCODE AND NOT THE CHANNEL.
//
// Python's disconnect sweep reads every remaining client's output_profile_id
// and stops any transcode no longer named (server.py:1216-1219), and it runs
// BEFORE the `if total == 0` branch at :1221 that honours
// channel_shutdown_delay -- so the transcode stops at once while the channel
// keeps running for the plain client still watching.
func TestTheLastProfileClientLeavingStopsTheTranscodeAndNotTheChannel(t *testing.T) {
	r := profileRig(t, "3", relaytest.OutputProfileConfig{
		ID:   3,
		Argv: standInProfileArgv(t),
	}, relaytest.Config{Rate: 4}, nil)

	plain := r.tuneAs(t, "c-outlives-profile", "client-plain")
	defer func() { _ = plain.Body.Close() }()
	waitForHead(t, r, "c-outlives-profile", 1)

	profiled := r.tuneProfile(t, "c-outlives-profile", "client-profile", "3", "")
	if profiled.StatusCode != http.StatusOK {
		t.Fatalf("the profile tune answered %d, want 200", profiled.StatusCode)
	}
	if got := readAtLeast(profiled.Body, buffer.TSPacketSize, 15*time.Second); len(got) == 0 {
		t.Fatal("the profile client received no bytes")
	}
	ch := r.Manager.Get("c-outlives-profile")
	if ch == nil {
		t.Fatal("the channel is gone")
	}
	if got := len(ch.OutputFormats()); got != 1 {
		t.Fatalf("the channel runs %d output pipelines before the profile client leaves, want 1", got)
	}

	_ = profiled.Body.Close()

	deadline := time.Now().Add(15 * time.Second)
	for len(ch.OutputFormats()) != 0 && time.Now().Before(deadline) {
		time.Sleep(20 * time.Millisecond)
	}
	if got := ch.OutputFormats(); len(got) != 0 {
		t.Fatalf("the channel still runs %v fifteen seconds after its last profile client left", got)
	}
	if r.Manager.Get("c-outlives-profile") == nil {
		t.Fatal("the channel stopped: a transcode's last client leaving must not end a channel a plain client is still watching")
	}
	if ch.Ring().Closed() {
		t.Fatal("the channel's ring closed when the profile client left")
	}
}

// STOPPING THE CHANNEL STOPS ITS TRANSCODE, with the client still attached --
// stop_all_output_profiles (server.py:1563-1566) from stop_channel's local
// cleanup at :1772, which reaches the Go registry through run's deferred
// stopOutputs.
func TestStoppingTheChannelStopsItsProfileTranscode(t *testing.T) {
	r := profileRig(t, "3", relaytest.OutputProfileConfig{
		ID:   3,
		Argv: standInProfileArgv(t),
	}, relaytest.Config{Rate: 4}, nil)

	response := r.tuneProfile(t, "c-stopped-profile", "client-a", "3", "")
	defer func() { _ = response.Body.Close() }()
	if response.StatusCode != http.StatusOK {
		t.Fatalf("the profile tune answered %d, want 200", response.StatusCode)
	}
	if got := readAtLeast(response.Body, buffer.TSPacketSize, 15*time.Second); len(got) == 0 {
		t.Fatal("the profile client received no bytes")
	}
	ch := r.Manager.Get("c-stopped-profile")
	if ch == nil {
		t.Fatal("the channel is gone")
	}
	if got := len(ch.OutputFormats()); got != 1 {
		t.Fatalf("the channel runs %d output pipelines before the stop, want 1", got)
	}

	// A SECOND REFERENCE NOBODY RELEASES, which is what makes this test about
	// stopOutputs and not about the refcount.
	//
	// Found by break-check: with `defer c.stopOutputs()` removed from
	// Channel.run this test stayed GREEN, because a stopped channel closes its
	// ring, the pass-through transcode reaches EOF on fd 0 and exits, its own
	// ring closes, the client's loop ends and its deferred release empties the
	// registry. The refcount covered for the mechanism under test. (2c-6's
	// TestStoppingTheChannelStopsItsRemux does NOT have this hole, because its
	// stand-in remux keeps producing fragments after fd 0 closes and its
	// client therefore never releases -- a difference in the stand-in, not in
	// the relay.) Holding a reference the test never drops leaves stopOutputs
	// as the only thing that can empty the map.
	profiles := ch.OutputProfiles()
	profile, found := profiles.Lookup("3")
	if !found {
		t.Fatal("the channel does not hold the Output Profile the tune used")
	}
	if _, _, err := ch.AttachOutput(output.ProfileKey(profile.ID), channel.OutputSpec{Profile: &profile}); err != nil {
		t.Fatalf("taking a second reference on the transcode: %v", err)
	}

	r.Manager.Stop("c-stopped-profile")

	deadline := time.Now().Add(15 * time.Second)
	for len(ch.OutputFormats()) != 0 && time.Now().Before(deadline) {
		time.Sleep(20 * time.Millisecond)
	}
	if got := ch.OutputFormats(); len(got) != 0 {
		t.Fatalf("the stopped channel still runs %v with a reference on it that was never released", got)
	}
}
