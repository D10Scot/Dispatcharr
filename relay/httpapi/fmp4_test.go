package httpapi

import (
	"encoding/json"
	"io"
	"net/http"
	"path/filepath"
	"testing"
	"time"

	"github.com/D10Scot/Dispatcharr/relay/control"
	"github.com/D10Scot/Dispatcharr/relay/internal/relaytest"
	"github.com/D10Scot/Dispatcharr/relay/output"
)

// standInRemux is the stand-in as a remux, spawned instead of ffmpeg.
//
// The channel's own upstream is still a real fake provider and the ring is
// still the real ring; only the OUTPUT process is a stand-in, because every
// test in this file is about the relay's reaction to a remux -- the bytes a
// real remuxer produces are relay/output's real-ffmpeg test's subject, and it
// drives the production argv.
func standInRemux(t *testing.T, args ...string) output.Remux {
	t.Helper()
	t.Setenv(relaytest.StandInEnv, "1")
	command, argv := relaytest.StandInCommand(args...)
	return output.Remux{Command: command, Argv: argv, ArgvNoBSF: argv}
}

// tuneFMP4 opens an fMP4 stream over the trusted path, the way the authorize
// hop opens one: X-Relay-Output-Format carries the format apps/proxy/
// authorize.py:501 resolved.
func (r *rig) tuneFMP4(t *testing.T, channelID, clientID string) *http.Response {
	t.Helper()
	header := http.Header{}
	header.Set(control.HeaderAuthorized, control.RelayTrustToken(testSecret))
	header.Set("X-Relay-Channel", channelID)
	header.Set("X-Relay-Client", clientID)
	header.Set("X-Relay-Client-IP", "198.51.100.4")
	header.Set("X-Relay-User", "7")
	header.Set("X-Relay-Output-Format", output.FormatFMP4)
	response := r.tune(t, "/proxy/ts/stream/"+channelID, header)
	if response.StatusCode != http.StatusOK {
		_ = response.Body.Close()
		t.Fatalf("fMP4 tune for %s answered %d, want 200", clientID, response.StatusCode)
	}
	return response
}

// readAtLeast reads until the body holds n bytes or the deadline passes, and
// returns what it got. It never fails on the caller's behalf, so the caller's
// message names its own subject.
func readAtLeast(body io.Reader, n int, within time.Duration) []byte {
	deadline := time.Now().Add(within)
	buf := make([]byte, 32*1024)
	var out []byte
	for len(out) < n && time.Now().Before(deadline) {
		read, err := body.Read(buf)
		out = append(out, buf[:read]...)
		if err != nil {
			break
		}
	}
	return out
}

// THE FIRST BYTES AN fMP4 CLIENT RECEIVES ARE THE INIT SEGMENT, then fragments
// -- output/fmp4/generator.py:131-140, and the Go counterpart of
// test_fmp4_output.py::test_an_fmp4_client_receives_an_init_segment_and_fragments.
// The Content-Type is views.py:805's video/mp4 where a TS tune sends
// video/mp2t (:817).
func TestAnFMP4TuneIsServedAsVideoMP4WithTheInitSegmentFirst(t *testing.T) {
	r := fanRig(t, relaytest.Config{Rate: 4}, nil,
		withRemux(standInRemux(t, "--fmp4-fragments", "20", "--fmp4-interval", "0.02")))

	response := r.tuneFMP4(t, "c-fmp4", "client-a")
	defer func() { _ = response.Body.Close() }()

	if got := response.Header.Get("Content-Type"); got != ContentTypeFMP4 {
		t.Fatalf("the response Content-Type is %q, want %q", got, ContentTypeFMP4)
	}
	if got := response.Header.Get("Cache-Control"); got != "no-cache" {
		t.Fatalf("the response Cache-Control is %q, want no-cache", got)
	}

	// Two fragments' worth, so the body carries a boundary and not just a
	// header: the shape helper needs a moof followed by an mdat to pass.
	body := readAtLeast(response.Body, len(relaytest.SyntheticFMP4Init())+2*len(relaytest.SyntheticFMP4Fragment(0)), 15*time.Second)
	if problem := relaytest.FMP4ShapeProblem(body); problem != "" {
		t.Fatalf("the %d bytes an fMP4 client received are not an init segment followed by a fragment: %s", len(body), problem)
	}
	// And the init segment is FIRST, byte for byte, not merely present: a
	// client handed fragments before the moov cannot decode any of them.
	init := relaytest.SyntheticFMP4Init()
	if len(body) < len(init) || string(body[:len(init)]) != string(init) {
		t.Fatalf("the first %d bytes are not the init segment the remux produced", len(init))
	}
}

// ONE REMUX PER (CHANNEL, FORMAT): ten fMP4 clients cost one output ffmpeg, the
// spec's own words for this PR.
//
// COUNTED BY SPAWNS, NOT BY REGISTRY ENTRIES, and the difference is the whole
// value of this test. An earlier version asserted that the channel held exactly
// one entry under "fmp4" -- which a relay that started a SECOND remux per
// client and overwrote the map entry would also satisfy, leaking the first
// process and answering the question "how many entries are in a map" rather
// than "how many processes were started". Demonstrated: with AttachOutput's
// reuse branch disabled, the registry assertion stayed green and this one
// reddens. The spawn log is the mechanism output_support.py:83's
// spawn_logging_standin uses for the same claim on the Python side.
func TestTwoFMP4ClientsShareOneRemux(t *testing.T) {
	log := filepath.Join(t.TempDir(), "remux-spawns.log")
	r := fanRig(t, relaytest.Config{Rate: 4}, nil,
		withRemux(standInRemux(t, "--spawn-log", log, "--fmp4-fragments", "60", "--fmp4-interval", "0.02")))

	first := r.tuneFMP4(t, "c-share", "client-a")
	defer func() { _ = first.Body.Close() }()
	if got := readAtLeast(first.Body, len(relaytest.SyntheticFMP4Init()), 15*time.Second); len(got) == 0 {
		t.Fatal("the first client received no bytes at all")
	}

	second := r.tuneFMP4(t, "c-share", "client-b")
	defer func() { _ = second.Body.Close() }()
	if got := readAtLeast(second.Body, len(relaytest.SyntheticFMP4Init()), 15*time.Second); len(got) == 0 {
		t.Fatal("the second client received no bytes at all")
	}

	if got := relaytest.SpawnCount(log); got != 1 {
		t.Fatalf("the relay spawned %d remuxes for two fMP4 clients on one channel, want 1", got)
	}

	ch := r.Manager.Get("c-share")
	if ch == nil {
		t.Fatal("the channel is gone")
	}
	if formats := ch.OutputFormats(); len(formats) != 1 || formats[0] != output.FormatFMP4 {
		t.Fatalf("the channel's output registry holds %v, want exactly one fmp4", formats)
	}
	if got := ch.Clients(); got != 2 {
		t.Fatalf("the channel has %d clients, want 2", got)
	}
}

// A TS CLIENT AND AN fMP4 CLIENT SHARE THE CHANNEL AND THE UPSTREAM, and only
// the output differs: views.py:789-818 branches after the channel is up and the
// client is registered, on the client's own resolved format.
func TestATSClientAndAnFMP4ClientShareOneUpstream(t *testing.T) {
	r := fanRig(t, relaytest.Config{Rate: 4}, nil,
		withRemux(standInRemux(t, "--fmp4-fragments", "60", "--fmp4-interval", "0.02")))

	ts := r.tuneAs(t, "c-mixed", "client-ts")
	defer func() { _ = ts.Body.Close() }()
	if got := ts.Header.Get("Content-Type"); got != "video/mp2t" {
		t.Fatalf("the TS client's Content-Type is %q, want video/mp2t", got)
	}
	waitForHead(t, r, "c-mixed", 1)

	fmp4 := r.tuneFMP4(t, "c-mixed", "client-fmp4")
	defer func() { _ = fmp4.Body.Close() }()
	if got := readAtLeast(fmp4.Body, len(relaytest.SyntheticFMP4Init()), 15*time.Second); len(got) == 0 {
		t.Fatal("the fMP4 client received no bytes")
	}

	if got := r.Upstream.Requests(); got != 1 {
		t.Fatalf("the provider saw %d requests, want 1: the two formats share one upstream", got)
	}
	if got := len(r.Control.RequestsTo("/next-source")); got != 1 {
		t.Fatalf("the relay made %d next-source calls, want 1", got)
	}
}

// THE CLIENT REGISTRY CARRIES THE FORMAT THE CLIENT IS ACTUALLY BEING SERVED,
// which is what 2c-3's ErrUnsupportedOutput comment refused to lie about: "a
// relay that logged fmp4 in its registry and then wrote MPEG-TS would be wrong
// in a way nothing on the wire says". Now that it serves both, the payload has
// to say which. channel_status.py:567 renders `output_format or 'mpegts'` from
// the client's own metadata hash, which client_manager.py:242 wrote from
// views.py:749's resolved_output_format.
func TestTheListPayloadNamesEachClientsOwnOutputFormat(t *testing.T) {
	r := fanRig(t, relaytest.Config{Rate: 4}, nil,
		withRemux(standInRemux(t, "--fmp4-fragments", "60", "--fmp4-interval", "0.02")))

	ts := r.tuneAs(t, "c-listed", "client-ts")
	defer func() { _ = ts.Body.Close() }()
	fmp4 := r.tuneFMP4(t, "c-listed", "client-fmp4")
	defer func() { _ = fmp4.Body.Close() }()
	if got := readAtLeast(fmp4.Body, len(relaytest.SyntheticFMP4Init()), 15*time.Second); len(got) == 0 {
		t.Fatal("the fMP4 client received no bytes")
	}

	status, body := r.listChannels(t, "?clients=all")
	if status != http.StatusOK {
		t.Fatalf("the list endpoint answered %d, want 200", status)
	}
	var payload channelListPayload
	if err := json.Unmarshal(body, &payload); err != nil {
		t.Fatalf("parsing the list payload: %v", err)
	}
	formats := map[string]string{}
	for _, ch := range payload.Channels {
		for _, client := range ch.Clients {
			formats[client.ClientID] = client.OutputFormat
		}
	}
	if got := formats["client-ts"]; got != OutputFormatMPEGTS {
		t.Fatalf("the TS client is listed with output_format %q, want %q", got, OutputFormatMPEGTS)
	}
	if got := formats["client-fmp4"]; got != output.FormatFMP4 {
		t.Fatalf("the fMP4 client is listed with output_format %q, want %q: the registry must name what the client is actually being served",
			got, output.FormatFMP4)
	}
}

// THE LAST fMP4 CLIENT LEAVING STOPS THE REMUX, AND THE CHANNEL KEEPS RUNNING.
// Python's disconnect sweep (server.py:1206-1214) reads every remaining
// client's output_format and stops any manager no longer named, and it runs
// BEFORE the `if total == 0` branch at :1221 that honours
// channel_shutdown_delay -- so the remux stops at once while the channel does
// not stop at all, because a TS client is still watching.
func TestTheLastFMP4ClientLeavingStopsTheRemuxAndNotTheChannel(t *testing.T) {
	r := fanRig(t, relaytest.Config{Rate: 4}, nil,
		withRemux(standInRemux(t, "--fmp4-fragments", "200", "--fmp4-interval", "0.02")))

	ts := r.tuneAs(t, "c-outlives", "client-ts")
	defer func() { _ = ts.Body.Close() }()
	waitForHead(t, r, "c-outlives", 1)

	fmp4 := r.tuneFMP4(t, "c-outlives", "client-fmp4")
	if got := readAtLeast(fmp4.Body, len(relaytest.SyntheticFMP4Init()), 15*time.Second); len(got) == 0 {
		t.Fatal("the fMP4 client received no bytes")
	}
	ch := r.Manager.Get("c-outlives")
	if ch == nil {
		t.Fatal("the channel is gone")
	}
	if got := len(ch.OutputFormats()); got != 1 {
		t.Fatalf("the channel runs %d output pipelines, want 1 before the fMP4 client leaves", got)
	}

	_ = fmp4.Body.Close()

	deadline := time.Now().Add(15 * time.Second)
	for len(ch.OutputFormats()) != 0 && time.Now().Before(deadline) {
		time.Sleep(20 * time.Millisecond)
	}
	if got := ch.OutputFormats(); len(got) != 0 {
		t.Fatalf("the channel still runs output pipelines %v fifteen seconds after its last fMP4 client left", got)
	}
	if r.Manager.Get("c-outlives") == nil {
		t.Fatal("the channel stopped too: a remux's last client leaving must not end a channel a TS client is still watching")
	}
	if ch.Ring().Closed() {
		t.Fatal("the channel's ring closed when the fMP4 client left")
	}
}

// A REMUX THAT PRODUCES NO INIT SEGMENT GIVES THE CLIENT AN EMPTY 200, not a
// 500 and not a hang: views.py builds the StreamingHttpResponse before its
// generator runs, so the status is already sent when _wait_for_fmp4_ready
// (generator.py:175-200) gives up. test_fmp4_output.py's own docstring records
// this as the shape.
//
// The child here writes NOTHING to fd 1 and exits, so the buffer closes with no
// segment -- which is what makes this test fast rather than a fifteen-second
// wait. The timeout arm proper is not driven: a test that waited out
// InitSegmentTimeout would add fifteen seconds to every run to assert the same
// empty body, and the two arms return through the same line.
func TestAnFMP4TuneWhoseRemuxProducesNoInitSegmentGetsAnEmptyTwoHundred(t *testing.T) {
	r := fanRig(t, relaytest.Config{Rate: 4}, nil,
		withRemux(standInRemux(t, "--fmp4-fragments", "0", "--fmp4-exit")))

	response := r.tuneFMP4(t, "c-noinit", "client-a")
	defer func() { _ = response.Body.Close() }()

	body, err := io.ReadAll(response.Body)
	if err != nil {
		t.Fatalf("reading the body: %v", err)
	}
	if len(body) != 0 {
		t.Fatalf("the client received %d bytes from a remux that produced no init segment, want an empty 200", len(body))
	}
}

// STOPPING THE CHANNEL STOPS ITS REMUX: stop_all_output_formats
// (server.py:1397-1400) from stop_channel's local cleanup at :1771. Without it
// a channel that ended would leave an ffmpeg reading a ring nobody fills, held
// alive by nothing, until the process exits.
func TestStoppingTheChannelStopsItsRemux(t *testing.T) {
	r := fanRig(t, relaytest.Config{Rate: 4}, nil,
		withRemux(standInRemux(t, "--fmp4-fragments", "200", "--fmp4-interval", "0.02")))

	response := r.tuneFMP4(t, "c-stopped", "client-a")
	defer func() { _ = response.Body.Close() }()
	if got := readAtLeast(response.Body, len(relaytest.SyntheticFMP4Init()), 15*time.Second); len(got) == 0 {
		t.Fatal("the fMP4 client received no bytes")
	}
	ch := r.Manager.Get("c-stopped")
	if ch == nil {
		t.Fatal("the channel is gone")
	}
	pipeline := ch.OutputFormats()
	if len(pipeline) != 1 {
		t.Fatalf("the channel runs %d output pipelines before the stop, want 1", len(pipeline))
	}

	// The client is STILL ATTACHED, so nothing but the channel stop can be
	// what ends the pipeline: the refcount is one and the release has not run.
	r.Manager.Stop("c-stopped")

	deadline := time.Now().Add(15 * time.Second)
	for len(ch.OutputFormats()) != 0 && time.Now().Before(deadline) {
		time.Sleep(20 * time.Millisecond)
	}
	if got := ch.OutputFormats(); len(got) != 0 {
		t.Fatalf("the stopped channel still runs output pipelines %v, with its only client still attached", got)
	}
}

// A REMUX THAT CANNOT BE SPAWNED IS A 500 WITH views.py:797's OWN BODY, before
// any of the response exists -- not a 200 whose body turns out to be empty.
// The two failures are different and a client that reads the body can tell
// them apart in Python, so it must be able to here.
func TestAnFMP4TuneWhoseRemuxCannotBeSpawnedIsAFiveHundred(t *testing.T) {
	r := fanRig(t, relaytest.Config{Rate: 4}, nil,
		withRemux(output.Remux{Command: "/nonexistent/dispatcharr-remux", Argv: []string{}, ArgvNoBSF: []string{}}))

	header := http.Header{}
	header.Set(control.HeaderAuthorized, control.RelayTrustToken(testSecret))
	header.Set("X-Relay-Channel", "c-nospawn")
	header.Set("X-Relay-Output-Format", output.FormatFMP4)
	response := r.tune(t, "/proxy/ts/stream/c-nospawn", header)
	defer func() { _ = response.Body.Close() }()

	if response.StatusCode != http.StatusInternalServerError {
		t.Fatalf("a tune whose remux could not be spawned answered %d, want 500", response.StatusCode)
	}
	body, err := io.ReadAll(response.Body)
	if err != nil {
		t.Fatalf("reading the body: %v", err)
	}
	// views.py:797's exact JSON. Asserted because it is one of the few error
	// bodies views.py spells out rather than leaving to a default.
	const want = `{"error": "Failed to start output format remux"}`
	if string(body) != want {
		t.Fatalf("the 500 body is %q, want views.py:797's %q", body, want)
	}
	// And the path it names must never carry the command: an operator's remux
	// command is not a credential, but the tune-failure rule is that no error
	// text reaches a client, and this body is a fixed string for that reason.
	if len(body) != len(want) {
		t.Fatalf("the body is %d bytes, want the fixed %d", len(body), len(want))
	}
}

// PARITY-MATRIX ROW 12, issue #222, REPRODUCED AND NOT FIXED (spec D5).
//
// An fMP4 client whose fragments stop arriving is disconnected
// stream_timeout + failover_grace_period later, on elapsed time ALONE -- no
// health check, no url_switching exemption, no keepalive -- while a TS client
// on the SAME channel, silent for at least as long, stays connected because
// serveClient's own timeout is gated on the channel being unhealthy and this
// channel is healthy throughout.
//
// The Go counterpart of test_fmp4_client_timeout.py::
// FMP4ClientTimeoutTests::test_a_stalled_fmp4_client_is_dropped_while_a_ts_client_is_not,
// and it is driven the same way: the timeout and the grace period are
// compressed (they are wire settings, so the rig sends them), and the health
// monitor's own thresholds are LEFT ALONE, because an unhealthy channel would
// start the TS keepalives and blur which of the two mechanisms held the TS
// client open.
//
// THE STALL IS ON THE REMUX, NOT ON THE UPSTREAM, and that is what makes the
// contrast sharp: the channel's ring keeps filling, so the channel stays
// healthy and the TS client keeps receiving bytes, while the fragment buffer
// goes quiet. A stalled UPSTREAM would eventually make the channel unhealthy
// and fail over, and the test would be about the failover.
func TestAStalledFMP4ClientIsDroppedWhileATSClientIsNot(t *testing.T) {
	const (
		streamTimeout = 1.0
		failoverGrace = 1.0
	)
	// THE STALL IS ON THE UPSTREAM, so BOTH clients go quiet -- which is what
	// makes the contrast mean anything. An earlier version stalled only the
	// remux, leaving the TS client still receiving bytes: its "the TS client
	// is still connected" assertion was then true because that client was
	// never silent, and removing the TS loop's health gate did not redden it.
	// Demonstrated by break-check, and corrected here rather than explained
	// away. test_fmp4_client_timeout.py stalls its source for the same reason.
	//
	// CONNECTION_TIMEOUT IS DELIBERATELY NOT COMPRESSED. The wire settings
	// this test does compress are the two _is_timeout sums (1 + 1 = 2s against
	// a default of 20 + 20 = 40); the health monitor keeps its own default, so
	// the channel is still HEALTHY when the fMP4 client is dropped two seconds
	// in, and the TS client's timeout gate is therefore still shut. An
	// unhealthy channel would start the TS keepalives and blur which of the
	// two mechanisms held that client open -- the Python test says the same
	// and for the same reason.
	upstreamStall := 200_000
	r := fanRig(t, relaytest.Config{Rate: 8, DeadAirAfterBytes: upstreamStall}, map[string]any{
		"STREAM_TIMEOUT":        streamTimeout,
		"FAILOVER_GRACE_PERIOD": failoverGrace,
	}, withRemux(standInRemux(t, "--fmp4-fragments", "200", "--fmp4-interval", "0.02")))

	ts := r.tuneAs(t, "c-row12", "client-ts")
	defer func() { _ = ts.Body.Close() }()
	waitForHead(t, r, "c-row12", 1)

	fmp4 := r.tuneFMP4(t, "c-row12", "client-fmp4")
	defer func() { _ = fmp4.Body.Close() }()

	// THE CLOCK IS TAKEN BEFORE THE THING IT MEASURES STARTS: everything after
	// this point only makes the measured gap LONGER, never shorter, so the
	// lower-bound assertion below cannot pass by being early.
	started := time.Now()

	// Read to EOF. The body ends only when serveFMP4Client returns, which for
	// this client is the row-12 disconnect.
	drained := make(chan int, 1)
	go func() {
		body, _ := io.ReadAll(fmp4.Body)
		drained <- len(body)
	}()

	var sent int
	select {
	case sent = <-drained:
	case <-time.After(30 * time.Second):
		t.Fatal("the fMP4 client was still connected thirty seconds into a stall, against a two-second client timeout: row 12's disconnect did not happen")
	}
	took := time.Since(started)

	if sent == 0 {
		t.Fatal("the fMP4 client received nothing at all, so it was not dropped mid-stream and this is not row 12's disconnect")
	}
	// A LOWER BOUND ONLY, and it exists to catch a FALSE POSITIVE: a teardown
	// that ended the response before the timeout could have. It fails in one
	// direction and is silent in the other, which is the only shape a clock is
	// allowed to take here. The pin is the two facts around it -- the fMP4
	// response ended and the TS response did not.
	if want := time.Duration((streamTimeout + failoverGrace) * float64(time.Second)); took < want {
		t.Fatalf("the fMP4 client was dropped %s after the tune, sooner than stream_timeout + failover_grace_period (%s): this is not the _is_timeout disconnect", took, want)
	}

	// AND THE CONTRAST, which is the whole content of row 12: the TS client on
	// the same channel, silent for at least as long, is still connected. Its
	// own timeout carries the health gate the fMP4 loop lacks, and this channel
	// is still healthy.
	ch := r.Manager.Get("c-row12")
	if ch == nil {
		t.Fatal("the channel stopped, so both clients ended for a reason that is not row 12")
	}
	if !ch.Healthy() {
		t.Fatal("the channel went unhealthy, which opens the TS client's own timeout gate: the contrast this test asserts would then be about the health monitor rather than about row 12")
	}
	if got := ch.Clients(); got != 1 {
		t.Fatalf("the channel has %d clients after the fMP4 one was dropped, want 1 (the TS client, still connected)", got)
	}
}
