package httpapi

import (
	"bytes"
	"encoding/json"
	"io"
	"net/http"
	"os"
	"path/filepath"
	"regexp"
	"strings"
	"sync"
	"testing"
	"time"

	"github.com/D10Scot/Dispatcharr/relay/control"
	"github.com/D10Scot/Dispatcharr/relay/ffmpeg"
	"github.com/D10Scot/Dispatcharr/relay/hls"
	"github.com/D10Scot/Dispatcharr/relay/internal/relaytest"
)

// The HLS output's end-to-end tests at the relay's HTTP surface (Phase 4a-1b).
//
// "Stand-in" throughout: the encoder and the probe are the re-executed test
// binary (relaytest/standin.go) writing relaytest.HLSVideoStream, HLSAACStream
// and HLSProbeJSON output, so the subject is the relay's REACTION -- its
// playlists, its sessions, its lifecycle -- never what an encoder makes. The
// real encoder is relay/hls/real_test.go's and the E2E's. Where a test says a
// session departs or expires "(driven ticks)", it advances rig.SessionClock
// past the threshold and then calls rig.tick(t): ticks alone cannot age one.

var multivariantURI = regexp.MustCompile(`/hls/([A-Za-z0-9._-]+)/video\.m3u8`)

// hlsFixture is what a test's HLS stand-ins are made of.
type hlsFixture struct {
	t          *testing.T
	dir        string
	mode       string
	probe      []byte
	probeLog   string
	encoderLog string
	// The flaky mode's two flag files: creating fail lets the encoder's
	// attempt exit non-zero, and creating ok makes every later attempt a
	// healthy one that produces full output.
	fail, ok string
	// gate is the file the gated modes wait for; touch it to release them.
	gate  string
	hooks *hlsHooks

	readyWait, playlistWait time.Duration
}

const (
	modeGood     = "good"     // full streams, then waits for its stdin's EOF
	modeInitOnly = "initonly" // both inits and no fragment at all
	modeNoInit   = "noinit"   // writes nothing and never exits on stdin EOF
	modeStubborn = "stubborn" // full streams and a straggler that outlives the encoder's kill
	modeFlaky    = "flaky"    // init-only and fails on cue, or healthy once ok exists

	// Phase 4a-1c: an entry, and a long-poll, held open for as long as a test
	// chooses, released by creating the gate file.
	modeGatedInit     = "gatedinit"     // writes nothing until the gate exists, then healthy output
	modeGatedSegments = "gatedsegments" // both inits, then the rest of the streams once the gate exists
)

func newHLSFixture(t *testing.T, mode string, probe []byte) *hlsFixture {
	t.Helper()
	t.Setenv(relaytest.StandInEnv, "1")
	f := &hlsFixture{t: t, dir: t.TempDir(), mode: mode, probe: probe, hooks: &hlsHooks{}}
	f.probeLog = filepath.Join(f.dir, "probe-spawns")
	f.encoderLog = filepath.Join(f.dir, "encoder-spawns")
	f.fail = filepath.Join(f.dir, "fail")
	f.ok = filepath.Join(f.dir, "ok")
	f.write("probe.json", probe)
	f.gate = filepath.Join(f.dir, "gate")
	vfull, afull := relaytest.HLSVideoStream(20, 50), relaytest.HLSAACStream(200)
	vinit, ainit := relaytest.HLSVideoStream(0, 50), relaytest.HLSAACStream(0)
	f.write("vfull.mp4", vfull)
	f.write("afull.mp4", afull)
	f.write("vinit.mp4", vinit)
	f.write("ainit.mp4", ainit)
	// The gated-segments mode writes an init, waits, then writes the rest of
	// the full stream, so the init has to be a byte prefix of it.
	for _, pair := range []struct {
		name       string
		init, full []byte
	}{{"video", vinit, vfull}, {"audio", ainit, afull}} {
		if !bytes.HasPrefix(pair.full, pair.init) {
			t.Fatalf("the %s init is not a byte prefix of its full stream; the gated-segments mode cannot split it", pair.name)
		}
	}
	f.write("vrest.mp4", vfull[len(vinit):])
	f.write("arest.mp4", afull[len(ainit):])
	return f
}

func (f *hlsFixture) path(name string) string { return filepath.Join(f.dir, name) }

func (f *hlsFixture) write(name string, data []byte) {
	f.t.Helper()
	if err := os.WriteFile(f.path(name), data, 0o600); err != nil {
		f.t.Fatal(err)
	}
}

func (f *hlsFixture) touch(path string) {
	f.t.Helper()
	if err := os.WriteFile(path, nil, 0o600); err != nil {
		f.t.Fatal(err)
	}
}

func (f *hlsFixture) probeSpawns() int   { return relaytest.SpawnCount(f.probeLog) }
func (f *hlsFixture) encoderSpawns() int { return relaytest.SpawnCount(f.encoderLog) }

// command is HLSDeps.Command for this fixture's mode.
func (f *hlsFixture) command(hls.Spawn) (string, []string) {
	switch f.mode {
	case modeGood:
		return relaytest.StandInCommand("--spawn-log", f.encoderLog,
			"--fd-file", relaytest.FDFileArg(1, f.path("vfull.mp4")),
			"--fd-file", relaytest.FDFileArg(3, f.path("afull.mp4")),
			"--wait-stdin-eof")
	case modeInitOnly:
		return relaytest.StandInCommand("--spawn-log", f.encoderLog,
			"--fd-file", relaytest.FDFileArg(1, f.path("vinit.mp4")),
			"--fd-file", relaytest.FDFileArg(3, f.path("ainit.mp4")),
			"--wait-stdin-eof")
	case modeGatedInit:
		return "sh", []string{"-c", `LOG=` + f.encoderLog + ` GATE=` + f.gate + ` VFULL=` + f.path("vfull.mp4") + ` AFULL=` + f.path("afull.mp4") + `; ` +
			`echo x >> "$LOG"; while [ ! -e "$GATE" ]; do sleep 0.05; done; cat "$VFULL"; cat "$AFULL" >&3; while true; do sleep 1; done`}
	case modeGatedSegments:
		return "sh", []string{"-c", `LOG=` + f.encoderLog + ` GATE=` + f.gate + ` VINIT=` + f.path("vinit.mp4") + ` AINIT=` + f.path("ainit.mp4") +
			` VREST=` + f.path("vrest.mp4") + ` AREST=` + f.path("arest.mp4") + `; ` +
			`echo x >> "$LOG"; cat "$VINIT"; cat "$AINIT" >&3; while [ ! -e "$GATE" ]; do sleep 0.05; done; cat "$VREST"; cat "$AREST" >&3; while true; do sleep 1; done`}
	case modeNoInit:
		return relaytest.StandInCommand("--spawn-log", f.encoderLog, "--ignore-stdin-eof")
	case modeStubborn:
		// A shell that leaves a straggler in a process group of its OWN
		// (job control), holding the encoder's pipes: the relay's SIGKILL of
		// the encoder's group does not reach it, so reaping the encoder waits
		// out ffmpeg.KillWait for the pipes, as a real encoder with a wedged
		// child would. That makes the pipeline's Stop take a known minimum.
		return "sh", []string{"-c", "echo x >> " + f.encoderLog + "; set -m; cat " + f.path("vfull.mp4") +
			"; cat " + f.path("afull.mp4") + " >&3; sleep 3 & wait"}
	}
	// modeFlaky: a shell, because the stand-in has no "exit on cue". It writes
	// what the flag files say: healthy output forever once ok exists, else
	// the inits alone and a non-zero exit as soon as fail exists. The relay
	// spawns it with fd 3 open, as it spawns the real encoder.
	script := `echo x >> "$LOG"
if [ -e "$OK" ]; then
  cat "$VFULL"; cat "$AFULL" >&3
  while true; do sleep 1; done
fi
cat "$VINIT"; cat "$AINIT" >&3
while [ ! -e "$FAIL" ]; do sleep 0.05; done
exit 1`
	return "sh", []string{"-c", "LOG=" + f.encoderLog + " OK=" + f.ok + " FAIL=" + f.fail +
		" VFULL=" + f.path("vfull.mp4") + " AFULL=" + f.path("afull.mp4") +
		" VINIT=" + f.path("vinit.mp4") + " AINIT=" + f.path("ainit.mp4") + "; " + script}
}

// option installs the stand-ins and the hooks on a rig.
func (f *hlsFixture) option() rigOption {
	return func(d *StreamDeps) {
		d.HLS.Command = f.command
		d.HLS.ProbeCommand = func(int) (string, []string) {
			return relaytest.StandInCommand("--spawn-log", f.probeLog, "--fd-file", relaytest.FDFileArg(1, f.path("probe.json")))
		}
		d.HLS.ExitGrace = 300 * time.Millisecond
		d.HLS.ReadyWait = f.readyWait
		d.HLS.PlaylistWait = f.playlistWait
		d.hooks = f.hooks
	}
}

// hlsRig is a rig with the fixture's stand-ins, on a channel that stops as
// soon as it has no client, and a provider fast enough to keep the ring fed.
func hlsRig(t *testing.T, f *hlsFixture, overrides map[string]any) *rig {
	t.Helper()
	return fanRigWith(t, relaytest.ControlPlaneConfig{}, relaytest.Config{Rate: 4}, overrides, f.option())
}

func hlsHeader(channelID, clientID string) http.Header {
	h := http.Header{}
	h.Set(control.HeaderAuthorized, control.RelayTrustToken(testSecret))
	h.Set("X-Relay-Channel", channelID)
	h.Set("X-Relay-Client", clientID)
	h.Set("X-Relay-Client-IP", "198.51.100.4")
	h.Set("X-Relay-User", "7")
	h.Set("X-Relay-Output-Format", OutputFormatHLS)
	return h
}

// do makes one request and returns the status, the headers and the body.
func (r *rig) do(t *testing.T, method, path string, header http.Header) (int, http.Header, []byte) {
	t.Helper()
	request, err := http.NewRequestWithContext(t.Context(), method, r.Relay.URL+path, nil)
	if err != nil {
		t.Fatalf("building %s %s: %v", method, path, err)
	}
	for name, values := range header {
		for _, v := range values {
			request.Header.Add(name, v)
		}
	}
	// A redirect is an ANSWER here, never followed: a Redirect-profile channel
	// that 302s to the provider would otherwise be followed into an endless
	// TS body.
	client := *r.Relay.Client()
	client.CheckRedirect = func(*http.Request, []*http.Request) error { return http.ErrUseLastResponse }
	response, err := client.Do(request)
	if err != nil {
		t.Fatalf("%s %s: %v", method, path, err)
	}
	defer func() { _ = response.Body.Close() }()
	body, err := io.ReadAll(response.Body)
	if err != nil {
		t.Fatalf("reading %s %s: %v", method, path, err)
	}
	return response.StatusCode, response.Header, body
}

// hlsSession is one live media session as its player holds it.
type hlsSession struct {
	token string
	sid   string
	body  string
}

// enter makes an HLS entry request and returns its raw answer.
func (r *rig) enter(t *testing.T, channelID, clientID string) (int, http.Header, []byte) {
	t.Helper()
	return r.do(t, http.MethodGet, "/proxy/ts/stream/"+channelID, hlsHeader(channelID, clientID))
}

// session enters and requires a 200 multivariant, and reads its token.
func (r *rig) session(t *testing.T, channelID, clientID string) hlsSession {
	t.Helper()
	status, _, body := r.enter(t, channelID, clientID)
	if status != http.StatusOK {
		t.Fatalf("the HLS entry for %s answered %d, want 200: %s", clientID, status, body)
	}
	match := multivariantURI.FindStringSubmatch(string(body))
	if match == nil {
		t.Fatalf("the multivariant carries no /hls/<token>/video.m3u8 URI:\n%s", body)
	}
	sid, ok := control.VerifyMediaSession(testSecret, match[1])
	if !ok {
		t.Fatalf("the multivariant's token %q does not verify", match[1])
	}
	return hlsSession{token: match[1], sid: sid, body: string(body)}
}

func (s hlsSession) path(rest string) string { return "/hls/" + s.token + "/" + rest }

func (r *rig) getHLS(t *testing.T, path string) (int, http.Header, []byte) {
	t.Helper()
	return r.do(t, http.MethodGet, path, nil)
}

func (r *rig) leave(t *testing.T, token string) int {
	t.Helper()
	status, _, _ := r.do(t, http.MethodDelete, "/hls/"+token, nil)
	return status
}

// listedClient is one row of the channel list's clients.
type listedClient struct {
	ClientID        string `json:"client_id"`
	OutputFormat    string `json:"output_format"`
	OutputProfileID *int   `json:"output_profile_id"`
}

// listedClients is the registry as the list endpoint shows it for one channel.
func (r *rig) listedClients(t *testing.T, channelID string) []listedClient {
	t.Helper()
	status, raw := r.listChannels(t, "?clients=all")
	if status != http.StatusOK {
		t.Fatalf("listing channels answered %d", status)
	}
	var list struct {
		Channels []struct {
			ChannelID string         `json:"channel_id"`
			Clients   []listedClient `json:"clients"`
		} `json:"channels"`
	}
	if err := json.Unmarshal(raw, &list); err != nil {
		t.Fatalf("decoding the list: %v", err)
	}
	for _, ch := range list.Channels {
		if ch.ChannelID == channelID {
			return ch.Clients
		}
	}
	return nil
}

func clientIDs(clients []listedClient) []string {
	out := make([]string, 0, len(clients))
	for _, c := range clients {
		out = append(out, c.ClientID)
	}
	return out
}

func sameIDs(got []string, want ...string) bool {
	if len(got) != len(want) {
		return false
	}
	seen := map[string]bool{}
	for _, g := range got {
		seen[g] = true
	}
	for _, w := range want {
		if !seen[w] {
			return false
		}
	}
	return true
}

// bytesSent is a client's bytes_sent off the detail endpoint.
func (r *rig) bytesSent(t *testing.T, channelID, clientID string) int64 {
	t.Helper()
	status, raw := r.internalCall(t, http.MethodGet, "/proxy/relay/channels/"+channelID, nil)
	if status != http.StatusOK {
		t.Fatalf("the detail endpoint answered %d: %s", status, raw)
	}
	var detail struct {
		Clients []struct {
			ClientID  string `json:"client_id"`
			BytesSent *int64 `json:"bytes_sent"`
		} `json:"clients"`
	}
	if err := json.Unmarshal(raw, &detail); err != nil {
		t.Fatal(err)
	}
	for _, c := range detail.Clients {
		if c.ClientID == clientID && c.BytesSent != nil {
			return *c.BytesSent
		}
	}
	t.Fatalf("no bytes_sent for %s in %s", clientID, raw)
	return 0
}

func (r *rig) eventsOf(typ string) []relaytest.RecordedEvent { return r.Control.EventsOfType(typ) }

func channelGone(r *rig, id string) func() bool {
	return func() bool { return r.Manager.Get(id) == nil }
}

// ---------------------------------------------------------------------------

func TestAnHLSTuneAnswersAMultivariantPlaylistRatherThanBytes(t *testing.T) {
	f := newHLSFixture(t, modeGood, relaytest.HLSProbeJSON(true, true))
	r := hlsRig(t, f, nil)

	header := hlsHeader("c-hls", "client-hls")
	header.Set("X-Relay-Output", "3") // an Output Profile the HLS output must ignore (Decision 12)
	status, responseHeader, body := r.do(t, http.MethodGet, "/proxy/ts/stream/c-hls", header)
	if status != http.StatusOK {
		t.Fatalf("the HLS tune answered %d: %s", status, body)
	}
	if got := responseHeader.Get("Content-Type"); got != "application/vnd.apple.mpegurl" {
		t.Errorf("Content-Type %q, want application/vnd.apple.mpegurl", got)
	}
	if got := responseHeader.Get("Cache-Control"); got != "no-store" {
		t.Errorf("Cache-Control %q, want no-store", got)
	}
	text := string(body)
	for _, want := range []string{"#EXTM3U", "#EXT-X-STREAM-INF"} {
		if !strings.Contains(text, want) {
			t.Errorf("the multivariant has no %q:\n%s", want, text)
		}
	}
	match := multivariantURI.FindStringSubmatch(text)
	if match == nil {
		t.Fatalf("no /hls/<token>/video.m3u8 URI in:\n%s", text)
	}
	if _, ok := control.VerifyMediaSession(testSecret, match[1]); !ok {
		t.Fatalf("the URI's token %q does not verify", match[1])
	}

	clients := r.listedClients(t, "c-hls")
	if len(clients) != 1 || clients[0].ClientID != "client-hls" || clients[0].OutputFormat != "hls" {
		t.Fatalf("the registry lists %+v, want the one client with output_format hls", clients)
	}
	if clients[0].OutputProfileID != nil {
		t.Errorf("output_profile_id is %d, want null: X-Relay-Output is ignored on an hls tune", *clients[0].OutputProfileID)
	}
	waitFor(t, "client_connect", 10*time.Second, func() bool { return len(r.eventsOf("client_connect")) == 1 })
}

func TestAnXCM3U8URLForcesHLSOnBothRoots(t *testing.T) {
	f := newHLSFixture(t, modeGood, relaytest.HLSProbeJSON(true, true))
	r := hlsRig(t, f, nil)

	for _, tc := range []struct{ path, channel, client string }{
		{"/live/u/p/12.m3u8", "c-xc-live", "client-live"},
		{"/u/p/12.m3u8", "c-xc-bare", "client-bare"},
	} {
		header := hlsHeader(tc.channel, tc.client)
		// The hop resolved the URI's format as mpegts: the .m3u8 extension is
		// the view's own override, and it must win.
		header.Set("X-Relay-Output-Format", OutputFormatMPEGTS)
		status, _, body := r.do(t, http.MethodGet, tc.path, header)
		if status != http.StatusOK || !strings.Contains(string(body), "#EXT-X-STREAM-INF") {
			t.Fatalf("%s answered %d, want the multivariant: %s", tc.path, status, body)
		}
	}
}

func TestAnEntryWhoseInitsNeverArriveIs503AndLeavesNoClient(t *testing.T) {
	f := newHLSFixture(t, modeNoInit, relaytest.HLSProbeJSON(true, true))
	f.readyWait = 300 * time.Millisecond
	r := hlsRig(t, f, nil)

	status, header, _ := r.enter(t, "c-noinit", "client-a")
	if status != http.StatusServiceUnavailable || header.Get("Retry-After") != "1" {
		t.Fatalf("the entry answered %d with Retry-After %q, want 503 and 1", status, header.Get("Retry-After"))
	}
	if r.Sessions.Len() != 0 {
		t.Fatalf("%d sessions remain after a failed entry", r.Sessions.Len())
	}
	waitFor(t, "the lone channel to stop", 10*time.Second, channelGone(r, "c-noinit"))
}

func TestANoVideoProbeIs502AndTheTSClientIsUnaffected(t *testing.T) {
	f := newHLSFixture(t, modeGood, relaytest.HLSProbeJSON(false, true))
	r := hlsRig(t, f, nil)

	// The watcher is held for the whole exchange, so only the entry's own
	// FailHLS can have marked the channel when the second entry arrives.
	gate := make(chan struct{})
	release := sync.OnceFunc(func() { close(gate) })
	f.hooks.beforeWatchMark = func() { <-gate }
	t.Cleanup(release)

	ts := r.tuneAs(t, "c-novideo", "client-ts")
	defer func() { _ = ts.Body.Close() }()
	packetRun(t, "the TS client before the HLS entry", ts.Body, 50)

	status, _, body := r.enter(t, "c-novideo", "client-hls")
	if status != http.StatusBadGateway || string(body) != `{"error": "no video stream in the source"}` {
		t.Fatalf("the first entry answered %d %q, want 502 and the no-video body", status, body)
	}
	// R50: the mark, not a re-probe, answers the second.
	status, _, body = r.enter(t, "c-novideo", "client-hls-2")
	if status != http.StatusBadGateway || string(body) != `{"error": "no video stream in the source"}` {
		t.Fatalf("the second entry answered %d %q, want 502 and the no-video body", status, body)
	}
	if n := f.probeSpawns(); n != 1 {
		t.Fatalf("%d probes across two entries, want exactly one: the channel's mark must answer the second", n)
	}
	if n := f.encoderSpawns(); n != 0 {
		t.Fatalf("%d encoders spawned for a source with no video", n)
	}
	release()

	readAligned(t, ts.Body, 50)
	if clients := r.listedClients(t, "c-novideo"); !sameIDs(clientIDs(clients), "client-ts") {
		t.Fatalf("the registry lists %v, want only the TS client", clientIDs(clients))
	}
}

func TestAMediaPlaylistWaitsForItsFirstSegmentAndCarriesItsHeaders(t *testing.T) {
	f := newHLSFixture(t, modeGood, relaytest.HLSProbeJSON(true, true))
	r := hlsRig(t, f, nil)
	s := r.session(t, "c-playlist", "client-a")

	status, header, playlist := r.getHLS(t, s.path("video.m3u8"))
	if status != http.StatusOK {
		t.Fatalf("the media playlist answered %d: %s", status, playlist)
	}
	if got := header.Get("Cache-Control"); got != "no-cache" {
		t.Errorf("playlist Cache-Control %q, want no-cache", got)
	}
	if got := header.Get("Content-Type"); got != "application/vnd.apple.mpegurl" {
		t.Errorf("playlist Content-Type %q", got)
	}
	if _, err := http.ParseTime(header.Get("Last-Modified")); err != nil {
		t.Errorf("Last-Modified %q does not parse: %v", header.Get("Last-Modified"), err)
	}
	segment := regexp.MustCompile(`(?m)^video/(\d+)\.m4s$`).FindStringSubmatch(string(playlist))
	if segment == nil {
		t.Fatalf("the playlist lists no video segment:\n%s", playlist)
	}

	// Init and segment: types and caching.
	before := r.bytesSent(t, "c-playlist", "client-a")
	status, header, initBytes := r.getHLS(t, s.path("video/init-0.mp4"))
	if status != http.StatusOK || header.Get("Content-Type") != "video/mp4" || header.Get("Cache-Control") != "private, max-age=86400" {
		t.Fatalf("video init: %d %q %q", status, header.Get("Content-Type"), header.Get("Cache-Control"))
	}
	status, header, _ = r.getHLS(t, s.path("aac/init-0.mp4"))
	if status != http.StatusOK || header.Get("Content-Type") != "audio/mp4" {
		t.Fatalf("audio init: %d %q", status, header.Get("Content-Type"))
	}
	status, header, media := r.getHLS(t, s.path("video/"+segment[1]+".m4s"))
	if status != http.StatusOK || header.Get("Content-Type") != "video/mp4" || header.Get("Cache-Control") != "private, max-age=86400" {
		t.Fatalf("video segment: %d %q %q", status, header.Get("Content-Type"), header.Get("Cache-Control"))
	}
	if after := r.bytesSent(t, "c-playlist", "client-a"); after < before+int64(len(initBytes)+len(media)) {
		t.Errorf("bytes_sent grew from %d to %d, want at least the %d bytes served", before, after, len(initBytes)+len(media))
	}

	for _, path := range []string{"ac3.m3u8", "video/nope.bin", "video/999999.m4s", "video/init-99.mp4", "ac3/init-0.mp4"} {
		if status, _, _ := r.getHLS(t, s.path(path)); status != http.StatusNotFound {
			t.Errorf("GET %s answered %d, want 404", path, status)
		}
	}
}

// With inits and no segment, the first media playlist request waits its
// PlaylistWait and then answers 503, rather than an empty playlist.
func TestAMediaPlaylistWithNoSegmentYetIs503(t *testing.T) {
	f := newHLSFixture(t, modeInitOnly, relaytest.HLSProbeJSON(true, true))
	f.playlistWait = 300 * time.Millisecond
	r := hlsRig(t, f, nil)
	s := r.session(t, "c-nosegment", "client-a")

	status, header, _ := r.getHLS(t, s.path("video.m3u8"))
	if status != http.StatusServiceUnavailable || header.Get("Retry-After") != "1" {
		t.Fatalf("a playlist with no segment answered %d with Retry-After %q, want 503 and 1", status, header.Get("Retry-After"))
	}
}

func TestTheHLSRoutesIgnoreTheTrustHeaders(t *testing.T) {
	f := newHLSFixture(t, modeGood, relaytest.HLSProbeJSON(true, true))
	r := hlsRig(t, f, nil)
	s := r.session(t, "c-trust", "client-a")

	// The trust marker is valid and names ANOTHER channel; neither is read.
	header := http.Header{}
	header.Set(control.HeaderAuthorized, control.RelayTrustToken(testSecret))
	header.Set("X-Relay-Channel", "some-other-channel")
	status, _, body := r.do(t, http.MethodGet, s.path("video.m3u8"), header)
	if status != http.StatusOK || !strings.Contains(string(body), "#EXT-X-TARGETDURATION") {
		t.Fatalf("a GET carrying trust headers answered %d: %s", status, body)
	}
}

func TestALeaveEndsTheSessionAtOnceAndIsIdempotent(t *testing.T) {
	f := newHLSFixture(t, modeGood, relaytest.HLSProbeJSON(true, true))
	r := hlsRig(t, f, nil)

	// The hook is set for session A's entry only: it is copied into A's
	// Releases when A's entry adds its session, and B's entry sees none.
	released := make(chan struct{})
	f.hooks.beforeLeaveClientRelease = func() {
		time.Sleep(200 * time.Millisecond)
		close(released)
	}
	a := r.session(t, "c-leave", "client-a")
	f.hooks.beforeLeaveClientRelease = nil
	b := r.session(t, "c-leave", "client-b")
	if status, _, _ := r.getHLS(t, a.path("video.m3u8")); status != http.StatusOK {
		t.Fatalf("A's playlist answered %d before the leave", status)
	}

	if status := r.leave(t, a.token); status != http.StatusNoContent {
		t.Fatalf("DELETE answered %d, want 204", status)
	}
	select {
	case <-released:
	default:
		select {
		case <-released:
			t.Fatal("the 204 was written before A's client release ran: the leave must answer after its side effects")
		case <-time.After(time.Second):
			t.Fatal("DELETE answered 204 but A's client was never released: the leave did not end the session")
		}
	}
	if got := clientIDs(r.listedClients(t, "c-leave")); !sameIDs(got, "client-b") {
		t.Fatalf("the registry lists %v the moment the 204 arrived, want only B", got)
	}
	waitFor(t, "client_disconnect", 10*time.Second, func() bool { return len(r.eventsOf("client_disconnect")) == 1 })
	disconnect := r.eventsOf("client_disconnect")[0]
	if disconnect.ClientID != "client-a" || disconnect.Details["duration"] == nil || disconnect.Details["bytes_sent"] == nil {
		t.Fatalf("client_disconnect = %+v, want A's with duration and bytes_sent", disconnect)
	}

	if status, _, _ := r.getHLS(t, a.path("video.m3u8")); status != http.StatusForbidden {
		t.Errorf("A's GET after its leave answered %d, want 403", status)
	}
	if status := r.leave(t, a.token); status != http.StatusNoContent {
		t.Errorf("a second DELETE answered %d, want 204 (idempotent)", status)
	}
	sid, err := control.NewMediaSessionID()
	if err != nil {
		t.Fatal(err)
	}
	if status := r.leave(t, control.MediaSessionToken(testSecret, sid)); status != http.StatusNoContent {
		t.Errorf("DELETE of an unknown but genuine token answered %d, want 204", status)
	}
	if status := r.leave(t, a.token[:len(a.token)-1]+"A"); status != http.StatusForbidden && status != http.StatusNoContent {
		t.Errorf("DELETE of a tampered token answered %d", status)
	}
	tampered := []byte(b.token)
	if tampered[len(tampered)-1] == 'A' {
		tampered[len(tampered)-1] = 'B'
	} else {
		tampered[len(tampered)-1] = 'A'
	}
	if status := r.leave(t, string(tampered)); status != http.StatusForbidden {
		t.Errorf("DELETE of a tampered token answered %d, want 403", status)
	}
	if got := clientIDs(r.listedClients(t, "c-leave")); !sameIDs(got, "client-b") {
		t.Errorf("a refused DELETE changed the registry: %v", got)
	}
}

func TestAStoppedSessionIs410OnceThen403AndADeleteIs204(t *testing.T) {
	f := newHLSFixture(t, modeGood, relaytest.HLSProbeJSON(true, true))
	r := hlsRig(t, f, nil)
	a := r.session(t, "c-stopped", "client-a")
	b := r.session(t, "c-stopped", "client-b")

	if status, raw := r.internalCall(t, http.MethodDelete, "/proxy/relay/channels/c-stopped", nil); status != http.StatusOK {
		t.Fatalf("stopping the channel answered %d: %s", status, raw)
	}
	stoppedAt := time.Now()
	status, _, body := r.getHLS(t, a.path("video.m3u8"))
	if status != http.StatusGone || string(body) != `{"error": "channel stopped"}` {
		t.Fatalf("a GET on a stopped channel's session answered %d %q, want 410 and the body", status, body)
	}
	if time.Since(stoppedAt) > time.Second {
		t.Errorf("the 410 took %v after the stop returned", time.Since(stoppedAt))
	}
	if status, _, _ := r.getHLS(t, a.path("video.m3u8")); status != http.StatusForbidden {
		t.Errorf("the second GET answered %d, want 403", status)
	}
	if status := r.leave(t, b.token); status != http.StatusNoContent {
		t.Errorf("DELETE on a stopped session answered %d, want 204", status)
	}
}

func TestAnAdminClientStopEndsAnHLSSession(t *testing.T) {
	f := newHLSFixture(t, modeGood, relaytest.HLSProbeJSON(true, true))
	r := hlsRig(t, f, nil)
	s := r.session(t, "c-admin", "client-a")
	ts := r.tuneAs(t, "c-admin", "client-ts") // keeps the channel up
	defer func() { _ = ts.Body.Close() }()

	status, raw := r.internalCall(t, http.MethodDelete, "/proxy/relay/channels/c-admin/clients/client-a", nil)
	if status != http.StatusOK {
		t.Fatalf("the client stop answered %d: %s", status, raw)
	}
	if body := decodeObject(t, raw); body["locally_processed"] != true {
		t.Errorf("locally_processed = %v, want true", body["locally_processed"])
	}
	if status, _, _ := r.getHLS(t, s.path("video.m3u8")); status != http.StatusForbidden {
		t.Errorf("the stopped session's GET answered %d, want 403 (the client stop must end the session)", status)
	}
	waitFor(t, "client_disconnect", 10*time.Second, func() bool {
		for _, e := range r.eventsOf("client_disconnect") {
			if e.ClientID == "client-a" {
				return true
			}
		}
		return false
	})
}

// Global constraint 2: the token and its sid are never logged, in any form.
func TestARejectedTokensTextNeverReachesTheLog(t *testing.T) {
	f := newHLSFixture(t, modeGood, relaytest.HLSProbeJSON(true, true))
	r := hlsRig(t, f, nil)

	forged := []string{
		"v1." + strings.Repeat("A", 22) + ".FORGEDMARKERONEabcdefghijklmnopqrstuvwxy",
		"v1." + strings.Repeat("B", 22) + ".FORGEDMARKERTWOabcdefghijklmnopqrstuvwxy",
		"FORGEDMARKERTHREE",
	}
	for _, token := range forged {
		if status, _, _ := r.getHLS(t, "/hls/"+token+"/video.m3u8"); status != http.StatusForbidden {
			t.Fatalf("a forged token's GET answered %d, want 403", status)
		}
		if status := r.leave(t, token); status != http.StatusForbidden {
			t.Fatalf("a forged token's DELETE answered %d, want 403", status)
		}
	}

	// A valid session's whole life: entry, playlist, segment, leave.
	s := r.session(t, "c-log", "client-a")
	_, _, playlist := r.getHLS(t, s.path("video.m3u8"))
	if seg := regexp.MustCompile(`(?m)^video/(\d+)\.m4s$`).FindStringSubmatch(string(playlist)); seg != nil {
		r.getHLS(t, s.path("video/"+seg[1]+".m4s"))
	}
	if status := r.leave(t, s.token); status != http.StatusNoContent {
		t.Fatalf("leave answered %d", status)
	}

	logged := r.Log.String()
	if logged == "" {
		t.Fatal("the rig captured no log at all; the assertion below would prove nothing")
	}
	for _, secret := range append(forged, s.token, s.sid, "FORGEDMARKER") {
		if strings.Contains(logged, secret) {
			t.Fatalf("the log carries %q (a media-session token or sid):\n%s", secret, logged)
		}
	}
}

// Spec case (i), and the break-check's oracle: every source exhausted with two
// sessions attached. Both are STOPPED, the channel leaves the map and its Done
// closes within a second of the run ending -- which is only possible if the
// self-stop runs on a goroutine of its own, since the stop it leads to waits
// on the very Done the run's defers close.
func TestSelfStopRunEnded(t *testing.T) {
	f := newHLSFixture(t, modeGood, relaytest.HLSProbeJSON(true, true))
	r := fanRigWith(t, relaytest.ControlPlaneConfig{},
		relaytest.Config{Rate: 1, StopAfterBytes: 1_200_000},
		map[string]any{"MAX_RETRIES": 1}, f.option())

	a := r.session(t, "c-runend", "client-a")
	b := r.session(t, "c-runend", "client-b")
	ch := r.Manager.Get("c-runend")
	if ch == nil {
		t.Fatal("no channel after two entries")
	}

	waitFor(t, "the run to end", 30*time.Second, func() bool { return ch.Ring().Closed() })
	endedAt := time.Now()
	select {
	case <-ch.Done():
	case <-time.After(time.Second):
		t.Fatalf("Done did not close within 1s of the run ending: the self-stop is waiting on its own goroutine")
	}
	waitFor(t, "the channel to leave the map", time.Second, channelGone(r, "c-runend"))
	for name, s := range map[string]hlsSession{"A": a, "B": b} {
		if status, _, _ := r.getHLS(t, s.path("video.m3u8")); status != http.StatusGone {
			t.Errorf("%s's GET after the run ended answered %d, want 410", name, status)
		}
	}
	if time.Since(endedAt) > 2*time.Second {
		t.Errorf("the whole self-stop took %v", time.Since(endedAt))
	}
	if strings.Contains(r.Log.String(), "source goroutine did not return in time") {
		t.Fatalf("the stop waited out StopWait on its own goroutine:\n%s", r.Log.String())
	}
}

// Spec case (ii): the HLS output fails with no other client on the channel.
func TestSelfStopHLSFailedWithNoOtherClient(t *testing.T) {
	f := newHLSFixture(t, modeFlaky, relaytest.HLSProbeJSON(true, true))
	r := hlsRig(t, f, nil)
	a := r.session(t, "c-hlsfail", "client-a")
	b := r.session(t, "c-hlsfail", "client-b")

	f.touch(f.fail) // every attempt now exits before its first segment

	waitFor(t, "the channel to be stopped and removed", 15*time.Second, channelGone(r, "c-hlsfail"))
	for name, s := range map[string]hlsSession{"A": a, "B": b} {
		if status, _, _ := r.getHLS(t, s.path("video.m3u8")); status != http.StatusGone {
			t.Errorf("%s's GET after the failure answered %d, want 410", name, status)
		}
	}
	waitFor(t, "the slot release", 10*time.Second, func() bool { return len(r.Control.RequestsTo("/release")) == 1 })
}

// Spec case (iii): the same failure with a TS client on the channel.
func TestSelfStopHLSFailedWithATSClient(t *testing.T) {
	f := newHLSFixture(t, modeFlaky, relaytest.HLSProbeJSON(true, true))
	r := hlsRig(t, f, nil)
	ts := r.tuneAs(t, "c-hlsfail-ts", "client-ts")
	defer func() { _ = ts.Body.Close() }()
	a := r.session(t, "c-hlsfail-ts", "client-a")

	f.touch(f.fail)

	waitFor(t, "the session to be stopped", 15*time.Second, func() bool {
		status, _, _ := r.getHLS(t, a.path("video.m3u8"))
		return status == http.StatusGone
	})
	if r.Manager.Get("c-hlsfail-ts") == nil {
		t.Fatal("the channel was stopped although a TS client is still on it")
	}
	readAligned(t, ts.Body, 50)
}

func TestAnAdminChannelStopEndsItsHLSSessions(t *testing.T) {
	f := newHLSFixture(t, modeGood, relaytest.HLSProbeJSON(true, true))
	r := hlsRig(t, f, nil)
	r.session(t, "c-chstop", "client-a")
	r.session(t, "c-chstop", "client-b")

	if status, raw := r.internalCall(t, http.MethodDelete, "/proxy/relay/channels/c-chstop", nil); status != http.StatusOK {
		t.Fatalf("stopping the channel answered %d: %s", status, raw)
	}
	waitFor(t, "a client_disconnect for each connected session", 10*time.Second, func() bool {
		return len(r.eventsOf("client_disconnect")) == 2
	})
}

// Row 44, the spec's failure-and-recovery test.
func TestAFailedHLSOutputRefusesEntriesUntilTheNextBoundaryAndStartsNothingThere(t *testing.T) {
	f := newHLSFixture(t, modeFlaky, relaytest.HLSProbeJSON(true, true))
	alternate := relaytest.NewUpstream(relaytest.Config{Payload: relaytest.SyntheticTS(rigAssetPackets, 0x100), Rate: 4})
	t.Cleanup(alternate.Close)
	cp := relaytest.ControlPlaneConfig{Alternates: []relaytest.AlternateConfig{{StreamID: 2, URL: alternate.URL()}}}
	r := fanRigWith(t, cp, relaytest.Config{Rate: 4}, nil, f.option())

	ts := r.tuneAs(t, "c-recover", "client-ts")
	defer func() { _ = ts.Body.Close() }()
	a := r.session(t, "c-recover", "client-a")

	f.touch(f.fail)
	waitFor(t, "the session to be stopped", 15*time.Second, func() bool {
		status, _, _ := r.getHLS(t, a.path("video.m3u8"))
		return status == http.StatusGone
	})
	if status, _, _ := r.getHLS(t, a.path("video.m3u8")); status != http.StatusForbidden {
		t.Errorf("the second GET after the stop answered %d, want 403", status)
	}

	status, _, body := r.enter(t, "c-recover", "client-b")
	if status != http.StatusBadGateway || string(body) != `{"error": "HLS output failed"}` {
		t.Fatalf("an entry while the channel is marked answered %d %q, want 502 and the failed body", status, body)
	}
	spawnedWhileMarked, probedWhileMarked := f.encoderSpawns(), f.probeSpawns()

	// An operator advance is a real source boundary: it clears the mark and
	// starts nothing.
	if status, raw := r.internalCall(t, http.MethodPost, "/proxy/relay/channels/c-recover/advance",
		advanceBody(t, alternate.URL(), 2, true)); status != http.StatusOK {
		t.Fatalf("the advance answered %d: %s", status, raw)
	}
	waitFor(t, "the alternate to be contacted", 15*time.Second, func() bool { return alternate.Requests() >= 1 })
	waitFor(t, "the mark to clear", 10*time.Second, func() bool {
		ch := r.Manager.Get("c-recover")
		return ch != nil && ch.HLSFailed() == nil
	})
	// An absence has to be waited for: a boundary that DID start a pipeline
	// would probe and spawn an encoder within a few hundred milliseconds of
	// clearing the mark, and asserting the instant it clears would pass
	// before that.
	time.Sleep(1500 * time.Millisecond)
	if got := f.encoderSpawns(); got != spawnedWhileMarked {
		t.Fatalf("%d encoder spawns after the boundary against %d before: a boundary must start nothing (R19)", got, spawnedWhileMarked)
	}
	if n := f.probeSpawns(); n != probedWhileMarked {
		t.Fatalf("%d probes after the boundary against %d before it", n, probedWhileMarked)
	}

	f.touch(f.ok)
	c := r.session(t, "c-recover", "client-c")
	if got := f.encoderSpawns(); got != spawnedWhileMarked+1 {
		t.Fatalf("%d encoder spawns after the fresh entry, want %d: it must start a fresh pipeline", got, spawnedWhileMarked+1)
	}
	if status, _, _ := r.getHLS(t, c.path("video.m3u8")); status != http.StatusOK {
		t.Errorf("the fresh session's playlist answered %d", status)
	}
	readAligned(t, ts.Body, 50)
}

// Row 41, the spec's first resume case.
func TestAResumeNeverStartsAChannel(t *testing.T) {
	f := newHLSFixture(t, modeGood, relaytest.HLSProbeJSON(true, true))
	r := hlsRig(t, f, nil)
	ts := r.tuneAs(t, "c-resume0", "client-ts") // holds the channel while the session departs
	defer func() { _ = ts.Body.Close() }()
	a := r.session(t, "c-resume0", "client-a")

	r.SessionClock.Advance(session12s)
	r.tick(t)
	waitFor(t, "the departure", 10*time.Second, func() bool {
		return sameIDs(clientIDs(r.listedClients(t, "c-resume0")), "client-ts")
	})
	// The channel stops between the resume's lookup and its attach.
	f.hooks.afterResumeLookup = func() { r.Manager.Stop("c-resume0") }
	nextSourceCalls := len(r.Control.RequestsTo("/next-source"))

	status, _, body := r.getHLS(t, a.path("video.m3u8"))
	if status != http.StatusGone || string(body) != `{"error": "channel stopped"}` {
		t.Fatalf("the resume answered %d %q, want 410", status, body)
	}
	if got := len(r.Control.RequestsTo("/next-source")); got != nextSourceCalls {
		t.Fatalf("the resume made %d next-source calls, want none: it must never start a channel", got-nextSourceCalls)
	}
	if status, _, _ := r.getHLS(t, a.path("video.m3u8")); status != http.StatusForbidden {
		t.Errorf("the session is still in the table after a failed resume (%d)", status)
	}
	if r.Manager.Get("c-resume0") != nil {
		t.Fatal("a channel is running again after the resume")
	}
}

// Row 41, the spec's second case: the stop lands between the resume's two
// attaches and its commit.
func TestAResumeThatLosesTheRaceToAStopReleasesItsAttachment(t *testing.T) {
	f := newHLSFixture(t, modeGood, relaytest.HLSProbeJSON(true, true))
	r := hlsRig(t, f, nil)
	ts := r.tuneAs(t, "c-resume1", "client-ts")
	defer func() { _ = ts.Body.Close() }()
	a := r.session(t, "c-resume1", "client-a")
	ch := r.Manager.Get("c-resume1")

	r.SessionClock.Advance(session12s)
	r.tick(t)
	waitFor(t, "the departure", 10*time.Second, func() bool {
		return sameIDs(clientIDs(r.listedClients(t, "c-resume1")), "client-ts")
	})
	f.hooks.afterResumeAttach = func() { r.Manager.Stop("c-resume1") }

	status, _, _ := r.getHLS(t, a.path("video.m3u8"))
	if status != http.StatusGone {
		t.Fatalf("the resume answered %d, want 410", status)
	}
	for _, c := range ch.ClientSnapshot() {
		if c.ID == "client-a" {
			t.Fatal("the stopped channel still lists the resumed client: its attachment was not released")
		}
	}
}

func TestADepartedSessionResumesOnItsRunningPipeline(t *testing.T) {
	f := newHLSFixture(t, modeGood, relaytest.HLSProbeJSON(true, true))
	r := hlsRig(t, f, nil)
	ts := r.tuneAs(t, "c-resume2", "client-ts")
	defer func() { _ = ts.Body.Close() }()
	a := r.session(t, "c-resume2", "client-a")
	b := r.session(t, "c-resume2", "client-b")

	// ONE clock ages both sessions, so the order matters: advance past the
	// idle timeout, let B's request complete (B's last activity is now the new
	// time), tick (A departs, B does not), then A's GET.
	r.SessionClock.Advance(session12s)
	if status, _, _ := r.getHLS(t, b.path("video.m3u8")); status != http.StatusOK {
		t.Fatalf("B's GET answered %d", status)
	}
	r.tick(t)
	waitFor(t, "A's departure", 10*time.Second, func() bool {
		return sameIDs(clientIDs(r.listedClients(t, "c-resume2")), "client-ts", "client-b")
	})

	status, _, body := r.getHLS(t, a.path("video.m3u8"))
	if status != http.StatusOK || !strings.Contains(string(body), "#EXT-X-TARGETDURATION") {
		t.Fatalf("A's resume answered %d: %s", status, body)
	}
	// Events reach the control plane ASYNCHRONOUSLY, in batches, so a baseline
	// count taken now can still miss earlier connects in flight and a later
	// "baseline + 1" can be jumped over by a batch that lands two at once
	// (the census flake: 3 of 10 CI rounds timed out here). What is monotone
	// and has one writer per emit is A's OWN connects: its entry's and its
	// resume's, exactly two, never more.
	waitFor(t, "client-a's second client_connect (its entry's and its resume's)", 10*time.Second, func() bool {
		n := 0
		for _, e := range r.eventsOf("client_connect") {
			if e.ClientID == "client-a" {
				n++
			}
		}
		return n == 2
	})
	if got := clientIDs(r.listedClients(t, "c-resume2")); !sameIDs(got, "client-ts", "client-a", "client-b") {
		t.Fatalf("the registry lists %v after the resume, want the TS client and both sessions", got)
	}
}

// R49: a resume needs its session's own running pipeline.
func TestAResumeOnAStoppedPipelineIs410(t *testing.T) {
	f := newHLSFixture(t, modeGood, relaytest.HLSProbeJSON(true, true))
	r := hlsRig(t, f, nil)
	ts := r.tuneAs(t, "c-resume3", "client-ts")
	defer func() { _ = ts.Body.Close() }()
	a := r.session(t, "c-resume3", "client-a")
	b := r.session(t, "c-resume3", "client-b")

	r.SessionClock.Advance(session12s)
	r.tick(t)
	waitFor(t, "A's and B's departures", 10*time.Second, func() bool {
		return sameIDs(clientIDs(r.listedClients(t, "c-resume3")), "client-ts")
	})
	// Both departed: the pipeline's refcount reached zero and it stopped,
	// while the TS client keeps the channel. A resume must not restart it.
	ch := r.Manager.Get("c-resume3")
	waitFor(t, "the pipeline to stop", 15*time.Second, func() bool { _, _, ok := ch.HLSStatus(); return !ok })
	_ = b
	if status, _, _ := r.getHLS(t, a.path("video.m3u8")); status != http.StatusGone {
		t.Fatalf("a resume on a stopped pipeline answered %d, want 410", status)
	}
	if n := f.encoderSpawns(); n != 1 {
		t.Fatalf("%d encoders spawned, want the one: the resume must not start a fresh pipeline", n)
	}
}

// Round 1, finding 2: an entry that joins a stopping channel is refused.
func TestAnEntryThatJoinsAStoppingChannelIsRefused(t *testing.T) {
	f := newHLSFixture(t, modeGood, relaytest.HLSProbeJSON(true, true))
	r := hlsRig(t, f, nil)
	r.session(t, "c-joinstop", "client-a") // makes the pipeline ready
	ch := r.Manager.Get("c-joinstop")

	// B's entry stops the channel between its AttachHLS and its Add.
	f.hooks.afterEntryAttach = func() {
		r.Manager.Stop("c-joinstop")
		<-ch.Done()
		time.Sleep(200 * time.Millisecond) // the run-end hook's goroutine
	}
	status, header, _ := r.enter(t, "c-joinstop", "client-b")
	f.hooks.afterEntryAttach = nil
	if status != http.StatusServiceUnavailable || header.Get("Retry-After") != "1" {
		t.Fatalf("an entry that joined a stopping channel answered %d, want 503 with Retry-After 1", status)
	}
	if got := r.Sessions.Len(); got > 1 {
		t.Fatalf("the table holds %d sessions, want at most A's (already STOPPED)", got)
	}
	for _, c := range ch.ClientSnapshot() {
		if c.ID == "client-b" {
			t.Fatal("the stopped channel's registry lists B")
		}
	}
}

// D13: a Redirect-profile channel is served over HLS through the relay.
func TestARedirectChannelIsServedOverHLSAsProxy(t *testing.T) {
	f := newHLSFixture(t, modeGood, relaytest.HLSProbeJSON(true, true))
	r := fanRigWith(t, relaytest.ControlPlaneConfig{Kind: control.KindRedirect}, relaytest.Config{Rate: 4}, nil, f.option())

	// A TS tune while the channel is not running is a 302, as ever.
	ts := http.Header{}
	ts.Set(control.HeaderAuthorized, control.RelayTrustToken(testSecret))
	ts.Set("X-Relay-Channel", "c-redirect")
	ts.Set("X-Relay-Client", "client-ts-0")
	client := *r.Relay.Client()
	client.CheckRedirect = func(*http.Request, []*http.Request) error { return http.ErrUseLastResponse }
	request, err := http.NewRequestWithContext(t.Context(), http.MethodGet, r.Relay.URL+"/proxy/ts/stream/c-redirect", nil)
	if err != nil {
		t.Fatal(err)
	}
	request.Header = ts
	response, err := client.Do(request)
	if err != nil {
		t.Fatal(err)
	}
	_ = response.Body.Close()
	if response.StatusCode != http.StatusFound && response.StatusCode != http.StatusMovedPermanently {
		t.Fatalf("a TS tune on a Redirect channel answered %d, want a redirect", response.StatusCode)
	}

	before := r.Upstream.Requests()
	s := r.session(t, "c-redirect", "client-hls")
	if s.token == "" {
		t.Fatal("no session")
	}
	if r.Upstream.Requests() <= before {
		t.Fatal("the provider saw no request from the relay: an hls tune on a Redirect channel must be served through it")
	}

	// And a TS tune while it runs attaches and gets bytes.
	running := r.tuneAs(t, "c-redirect", "client-ts-1")
	defer func() { _ = running.Body.Close() }()
	readAligned(t, running.Body, 50)
}

func TestTheSweeperIsProcessWideAndOutlivesItsChannel(t *testing.T) {
	f := newHLSFixture(t, modeGood, relaytest.HLSProbeJSON(true, true))
	r := hlsRig(t, f, nil)
	r.session(t, "c-sweeper", "client-a") // a lone viewer: no TS client keeps the channel

	r.SessionClock.Advance(session12s)
	r.tick(t)
	waitFor(t, "the departure to stop the channel", 15*time.Second, channelGone(r, "c-sweeper"))
	if r.Sessions.Len() != 1 {
		t.Fatalf("the table holds %d sessions, want the one departed (resumable)", r.Sessions.Len())
	}

	// The channel and its pipeline are gone; the sweeper is not.
	r.SessionClock.Advance(session300s + time.Second)
	r.tick(t)
	waitFor(t, "the expired session to be removed", 10*time.Second, func() bool { return r.Sessions.Len() == 0 })
}

// Nit 10 of round 1: a pipeline released at zero stops off the request
// goroutine, so a slow encoder's exit grace never delays a zap.
func TestAPipelineReleasedAtZeroStopsOffTheRequestGoroutine(t *testing.T) {
	f := newHLSFixture(t, modeStubborn, relaytest.HLSProbeJSON(true, true))
	r := hlsRig(t, f, nil)
	ts := r.tuneAs(t, "c-zero", "client-ts") // keeps the channel, so only the pipeline stops
	defer func() { _ = ts.Body.Close() }()
	s := r.session(t, "c-zero", "client-a")
	ch := r.Manager.Get("c-zero")

	started := time.Now()
	if status := r.leave(t, s.token); status != http.StatusNoContent {
		t.Fatalf("DELETE answered %d, want 204", status)
	}
	// The encoder's straggler holds its pipes past the kill, so the pipeline's
	// own Stop cannot return before ffmpeg.KillWait has run out; a DELETE that
	// waited for it would take at least that long.
	if took := time.Since(started); took >= ffmpeg.KillWait {
		t.Fatalf("the 204 took %v: the pipeline's Stop, which waits at least %v for the encoder's pipes, ran on the request goroutine", took, ffmpeg.KillWait)
	}
	if _, _, ok := ch.HLSStatus(); ok {
		t.Fatal("the pipeline is still registered after its last session left")
	}
}

func TestTheChannelPayloadCarriesTheHLSEncoderAndGeneration(t *testing.T) {
	f := newHLSFixture(t, modeGood, relaytest.HLSProbeJSON(true, true))
	r := hlsRig(t, f, nil)
	ts := r.tuneAs(t, "c-payload", "client-ts")
	defer func() { _ = ts.Body.Close() }()

	list := func() map[string]any {
		status, raw := r.listChannels(t, "")
		if status != http.StatusOK {
			t.Fatalf("list answered %d", status)
		}
		var out struct {
			Channels []map[string]any `json:"channels"`
		}
		if err := json.Unmarshal(raw, &out); err != nil || len(out.Channels) != 1 {
			t.Fatalf("decoding the list: %v (%d channels)", err, len(out.Channels))
		}
		return out.Channels[0]
	}
	detail := func() map[string]any {
		status, raw := r.internalCall(t, http.MethodGet, "/proxy/relay/channels/c-payload", nil)
		if status != http.StatusOK {
			t.Fatalf("detail answered %d", status)
		}
		return decodeObject(t, raw)
	}
	for name, payload := range map[string]map[string]any{"list": list(), "detail": detail()} {
		if _, present := payload["hls_encoder"]; present {
			t.Errorf("the %s payload of a TS-only channel carries hls_encoder", name)
		}
		if _, present := payload["hls_generation"]; present {
			t.Errorf("the %s payload of a TS-only channel carries hls_generation", name)
		}
	}

	r.session(t, "c-payload", "client-hls")
	for name, payload := range map[string]map[string]any{"list": list(), "detail": detail()} {
		if payload["hls_encoder"] != "software" {
			t.Errorf("the %s payload's hls_encoder is %v, want software", name, payload["hls_encoder"])
		}
		if generation, ok := payload["hls_generation"].(float64); !ok || generation != 0 {
			t.Errorf("the %s payload's hls_generation is %v, want 0", name, payload["hls_generation"])
		}
	}
}

// Timing constants the driven-tick tests use, named so the intent reads.
const (
	session12s  = 12 * time.Second
	session300s = 300 * time.Second
)

// Rulings R56 and R57: the entry's wait for the encoder's init segments and the
// media playlist's wait for its first segment must not be shorter than a
// legitimate cold software start: the quick probe and, in sequence, the
// re-probe, then the startup stall allowance a generation gets before its
// first fragment (R55). A 503 on the multivariant
// fails an AVPlayer item outright. Held under nginx's 60 s read timeout.
func TestTheEntryWaitsOutALegitimateColdStart(t *testing.T) {
	cold := hls.QuickProbe.Analyze + hls.FullProbe.Analyze + hls.StartupStallFactor*hls.StallTimeout
	for name, got := range map[string]time.Duration{
		"ReadyWait":    HLSDeps{}.readyWait(),
		"PlaylistWait": HLSDeps{}.playlistWait(),
	} {
		if got < cold {
			t.Errorf("the default %s is %v, below a legitimate cold start's %v (quick probe + re-probe + startup stall allowance)", name, got, cold)
		}
		if got >= 60*time.Second {
			t.Errorf("the default %s is %v, not under nginx's 60 s proxy_read_timeout on /hls/", name, got)
		}
	}
}
