package httpapi

import (
	"context"
	"encoding/json"
	"errors"
	"io"
	"log/slog"
	"math"
	"net/http"
	"os"
	"regexp"
	"strconv"
	"strings"
	"testing"
	"time"

	"github.com/D10Scot/Dispatcharr/relay/buffer"
	"github.com/D10Scot/Dispatcharr/relay/channel"
	"github.com/D10Scot/Dispatcharr/relay/control"
	"github.com/D10Scot/Dispatcharr/relay/internal/relaytest"
)

// TestStandIn is this package's trampoline (relaytest/standin.go).
func TestStandIn(_ *testing.T) {
	if os.Getenv(relaytest.StandInEnv) != "1" {
		return
	}
	os.Exit(relaytest.RunStandIn(relaytest.StandInArgs()))
}

// transcodeRig is fanRig with a TRANSCODE stream profile whose command is
// the stand-in, fetching the rig's own upstream: the fake Django answers
// kind "transcode" and a built argv, exactly as it would for the locked
// ffmpeg profile after Django's build_command substituted the URL.
func transcodeRig(t *testing.T, overrides map[string]any, standInArgs ...string) *rig {
	t.Helper()
	return transcodeRigWith(t, relaytest.ControlPlaneConfig{Kind: control.KindTranscode}, overrides, standInArgs...)
}

func transcodeRigWith(t *testing.T, cp relaytest.ControlPlaneConfig, overrides map[string]any, standInArgs ...string) *rig {
	t.Helper()
	t.Setenv(relaytest.StandInEnv, "1")
	// The upstream is started first so its URL can be put in the argv,
	// which is what Django does with {streamUrl}; fanRigWith starts its own
	// and this one is the same object because newRig only creates one when
	// cp.SourceURL is empty.
	upstream := relaytest.NewUpstream(relaytest.Config{Payload: relaytest.SyntheticTS(rigAssetPackets, 0x100), Rate: 4})
	t.Cleanup(upstream.Close)
	cp.SourceURL = upstream.URL()
	if cp.Kind == control.KindTranscode {
		cp.Command, cp.Argv = relaytest.StandInCommand(append([]string{"-i", upstream.URL()}, standInArgs...)...)
	}
	cp.Settings = rigSettings(overrides)
	r := newRig(t, cp, relaytest.Config{Payload: relaytest.SyntheticTS(rigAssetPackets, 0x100), Rate: 4})
	// newRig started an upstream of its own that nothing will call; the
	// one the child fetches is the one the assertions count.
	r.Upstream = upstream
	return r
}

// waitForStats blocks until the channel has a reported ffmpeg speed: the
// stderr reader has parsed at least one progress record.
func waitForStats(t *testing.T, r *rig, id string) {
	t.Helper()
	deadline := time.Now().Add(15 * time.Second)
	for {
		if ch := r.Manager.Get(id); ch != nil && ch.Stats().FFmpegSpeed != nil {
			return
		}
		if time.Now().After(deadline) {
			t.Fatalf("channel %s never reported an ffmpeg speed within fifteen seconds", id)
		}
		time.Sleep(20 * time.Millisecond)
	}
}

func listedChannel(t *testing.T, r *rig) map[string]any {
	t.Helper()
	status, body := r.listChannels(t, "?clients=all")
	if status != http.StatusOK {
		t.Fatalf("the list endpoint answered %d", status)
	}
	var payload struct {
		Channels []map[string]any `json:"channels"`
	}
	if err := json.Unmarshal(body, &payload); err != nil {
		t.Fatalf("decoding the list body: %v", err)
	}
	if len(payload.Channels) != 1 {
		t.Fatalf("the relay listed %d channels, want 1", len(payload.Channels))
	}
	return payload.Channels[0]
}

// THE TRANSCODE ARCHITECTURE END TO END: the control plane names a transcode
// profile, the relay spawns its command with the built argv, the CHILD
// fetches the provider -- the relay itself never does -- and the client
// receives the child's fd 1 as whole, in-order TS packets.
func TestATranscodeTuneDeliversTheChildsOutput(t *testing.T) {
	r := transcodeRig(t, nil)
	response := r.tuneAs(t, "c-transcode", "client-a")
	defer func() { _ = response.Body.Close() }()
	if got := response.Header.Get("Content-Type"); got != "video/mp2t" {
		t.Fatalf("Content-Type = %q", got)
	}
	packetRun(t, "the client", response.Body, 400)
	if n := r.Upstream.Requests(); n != 1 {
		t.Fatalf("the provider saw %d requests, want exactly 1 -- from the child, not the relay", n)
	}
	seen := r.Control.RequestsTo("/next-source")
	if len(seen) != 1 || !strings.HasSuffix(seen[0].Path, "/c-transcode/next-source") {
		t.Fatalf("the control plane saw %d next-source calls: %+v", len(seen), seen)
	}
}

// The seven ffmpeg-derived fields reach GET /proxy/relay/channels with the
// values the corpus carries, typed as RelayChannelSerializer declares them:
// source_fps and ffmpeg_speed as floats on this endpoint (row 14's list
// side), the rest as strings.
func TestTheListEndpointCarriesTheFfmpegDerivedFields(t *testing.T) {
	speeds := relaytest.CorpusSpeeds("normal")
	r := transcodeRig(t, nil, "--stderr-corpus", relaytest.CorpusPath("normal"), "--stderr-interval", "0")
	response := r.tuneAs(t, "c-stats", "client-a")
	defer func() { _ = response.Body.Close() }()
	waitForHead(t, r, "c-stats", 1)
	waitForStats(t, r, "c-stats")
	// The whole capture is on stderr before the stand-in exits, by
	// construction (RunStandIn joins its stderr pump; break-check 22), and
	// at interval 0 it is written in one burst, so the last record is the
	// one reported once the reader has drained it. Waited for rather than
	// assumed, because the reader and the copy loop are two goroutines.
	deadline := time.Now().Add(5 * time.Second)
	for {
		speed := r.Manager.Get("c-stats").Stats().FFmpegSpeed
		if speed != nil && *speed == speeds[len(speeds)-1] {
			break
		}
		if time.Now().After(deadline) {
			t.Fatalf("ffmpeg_speed settled at %v, want the capture's last record %v", speed, speeds[len(speeds)-1])
		}
		time.Sleep(20 * time.Millisecond)
	}

	ch := listedChannel(t, r)
	for key, want := range map[string]any{
		"video_codec":    "h264",
		"resolution":     "320x180",
		"source_fps":     25.0,
		"ffmpeg_speed":   speeds[len(speeds)-1],
		"audio_codec":    "aac",
		"audio_channels": "mono",
		"stream_type":    "mpegts",
	} {
		if got := ch[key]; got != want {
			t.Errorf("%s = %v (%T), want %v (%T)", key, got, got, want, want)
		}
	}
	if got := ch["state"]; got != string(channel.StateActive) {
		t.Errorf("state = %v, want active: the normal capture never dips below the default threshold", got)
	}
}

// Issue #314: the output bitrate the stderr reader parses reaches the DETAIL
// endpoint as ffmpeg_bitrate, a string rounded to one place as Python stored
// it. The expected value is read off the capture with a test-local pattern,
// not through the parser under test.
func TestTheDetailEndpointCarriesTheFFmpegOutputBitrate(t *testing.T) {
	_, records := relaytest.SplitCorpus(relaytest.Corpus("normal"))
	m := regexp.MustCompile(`bitrate=\s*([0-9.]+)kbits/s`).FindSubmatch(records[len(records)-1])
	if m == nil {
		t.Fatal("the normal capture's last record carries no bitrate=; re-derive (CAPTURE.md)")
	}
	kbps, _ := strconv.ParseFloat(string(m[1]), 64)
	want := strconv.FormatFloat(math.Round(kbps*10)/10, 'f', -1, 64)
	if !strings.Contains(want, ".") {
		want += ".0"
	}

	r := transcodeRig(t, nil, "--stderr-corpus", relaytest.CorpusPath("normal"), "--stderr-interval", "0")
	response := r.tuneAs(t, "c-bitrate", "client-a")
	defer func() { _ = response.Body.Close() }()
	waitForHead(t, r, "c-bitrate", 1)
	deadline := time.Now().Add(5 * time.Second)
	for {
		stats := r.Manager.Get("c-bitrate").Stats()
		if stats.FFmpegOutputBitrate != nil && *stats.FFmpegOutputBitrate == math.Round(kbps*10)/10 {
			break
		}
		if time.Now().After(deadline) {
			t.Fatalf("the output bitrate settled at %v, want the capture's last record %v", stats.FFmpegOutputBitrate, kbps)
		}
		time.Sleep(20 * time.Millisecond)
	}

	status, body := r.internalCall(t, http.MethodGet, "/proxy/relay/channels/c-bitrate", nil)
	if status != http.StatusOK {
		t.Fatalf("the detail endpoint answered %d", status)
	}
	var detail map[string]any
	if err := json.Unmarshal(body, &detail); err != nil {
		t.Fatalf("decoding the detail body: %v", err)
	}
	if got := detail["ffmpeg_bitrate"]; got != want {
		t.Fatalf("ffmpeg_bitrate = %v (%T), want %q: the parsed output bitrate did not reach the detail payload (#314)", got, got, want)
	}
}

// PARITY-MATRIX ROW 29: the buffering detector is ffmpeg-exclusive. A Proxy
// channel with buffering_speed at the API's MAXIMUM -- a threshold no real
// stream reaches -- never reports a speed, never enters buffering, and its
// payload carries none of the seven ffmpeg-derived keys. Meaningful only now
// that both architectures exist: against 2c-3's Proxy-only relay it could
// not have failed.
func TestTheProxyProfileStreamsWithNoFfmpegAndNoStats(t *testing.T) {
	r := fanRig(t, relaytest.Config{Rate: 4}, map[string]any{"buffering_speed": 10.0, "buffering_timeout": 1})
	response := r.tuneAs(t, "c-proxy", "client-a")
	defer func() { _ = response.Body.Close() }()
	packetRun(t, "the client", response.Body, 2000)
	waitForHead(t, r, "c-proxy", 3)

	ch := listedChannel(t, r)
	for _, key := range []string{"video_codec", "resolution", "source_fps", "ffmpeg_speed", "audio_codec", "audio_channels", "stream_type"} {
		if v, present := ch[key]; present {
			t.Errorf("a Proxy channel carries %s = %v; nothing on that path can set it", key, v)
		}
	}
	if got := ch["state"]; got != string(channel.StateActive) {
		t.Errorf("state = %v, want active -- the Proxy path must never enter buffering, whatever the threshold", got)
	}
}

// The three states of stream_profile.argv at the tune surface. A missing key
// is a contract mismatch (502) like a missing setting; null is a profile
// that cannot be built (503); and in both cases NOTHING is spawned, which
// the provider's request count proves.
func TestAnAbsentOrNullArgvFailsTheTuneBeforeAnythingIsSpawned(t *testing.T) {
	for _, tc := range []struct {
		name string
		cp   relaytest.ControlPlaneConfig
		want int
	}{
		{"absent: an older control plane", relaytest.ControlPlaneConfig{Kind: control.KindTranscode, ArgvAbsent: true}, http.StatusBadGateway},
		{"null: unparseable parameters", relaytest.ControlPlaneConfig{Kind: control.KindTranscode, ArgvNull: true}, http.StatusServiceUnavailable},
	} {
		t.Run(tc.name, func(t *testing.T) {
			r := transcodeRigWith(t, tc.cp, nil)
			response := r.tune(t, "/proxy/ts/stream/c-argv", nil)
			defer func() { _ = response.Body.Close() }()
			if response.StatusCode != tc.want {
				t.Fatalf("answered %d, want %d", response.StatusCode, tc.want)
			}
			if n := r.Upstream.Requests(); n != 0 {
				t.Fatalf("the provider saw %d requests for a tune that could not be built", n)
			}
			body, _ := io.ReadAll(response.Body)
			if strings.Contains(string(body), "127.0.0.1") {
				t.Fatalf("the refusal body names the provider: %s", body)
			}
		})
	}
}

// force_ffmpeg (input/manager.py:445-453): a PROXY profile whose URL is HLS
// is played through the locked ffmpeg profile, not the raw reader. The
// discriminator is the stats: only the transcode path can produce an
// ffmpeg_speed, so its presence proves the child ran.
func TestAProxyProfileWithAnHLSURLIsPlayedThroughTheFFmpegProfile(t *testing.T) {
	t.Setenv(relaytest.StandInEnv, "1")
	upstream := relaytest.NewUpstream(relaytest.Config{Payload: relaytest.SyntheticTS(rigAssetPackets, 0x100), Rate: 4})
	t.Cleanup(upstream.Close)
	hlsURL := strings.TrimSuffix(upstream.URL(), ".ts") + ".m3u8"
	command, argv := relaytest.StandInCommand("-i", hlsURL, "--stderr-corpus", relaytest.CorpusPath("normal"), "--stderr-interval", "0")
	cp := relaytest.ControlPlaneConfig{
		Kind:          control.KindProxy,
		SourceURL:     hlsURL,
		FFmpegProfile: &relaytest.ProfileConfig{ID: 9, Command: command, Argv: argv},
		Settings:      rigSettings(nil),
	}
	r := newRig(t, cp, relaytest.Config{Payload: relaytest.SyntheticTS(rigAssetPackets, 0x100), Rate: 4})
	r.Upstream = upstream

	response := r.tuneAs(t, "c-hls", "client-a")
	defer func() { _ = response.Body.Close() }()
	packetRun(t, "the client", response.Body, 200)
	waitForStats(t, r, "c-hls")
	if n := upstream.Requests(); n != 1 {
		t.Fatalf("the provider saw %d requests, want 1 -- from the ffmpeg profile's child", n)
	}
	if _, present := listedChannel(t, r)["ffmpeg_speed"]; !present {
		t.Fatal("no ffmpeg_speed on the payload: the HLS URL was served by the raw reader, not by the ffmpeg profile")
	}
}

// ...and with NO locked ffmpeg profile installed, the same tune is refused
// 503 rather than handed to a reader that cannot follow a playlist.
func TestAProxyProfileWithAnHLSURLAndNoFFmpegProfileIsRefused(t *testing.T) {
	upstream := relaytest.NewUpstream(relaytest.Config{Payload: relaytest.SyntheticTS(64, 0x100)})
	t.Cleanup(upstream.Close)
	cp := relaytest.ControlPlaneConfig{Kind: control.KindProxy, SourceURL: strings.TrimSuffix(upstream.URL(), ".ts") + ".m3u8", Settings: rigSettings(nil)}
	r := newRig(t, cp, relaytest.Config{})
	response := r.tune(t, "/proxy/ts/stream/c-hls-none", nil)
	defer func() { _ = response.Body.Close() }()
	if response.StatusCode != http.StatusServiceUnavailable {
		t.Fatalf("answered %d, want 503", response.StatusCode)
	}
	if n := upstream.Requests(); n != 0 {
		t.Fatalf("the provider saw %d requests: the raw reader was pointed at a playlist", n)
	}
}

// PARITY-MATRIX ROW 5: the thresholds are snapshotted at channel start. A
// proxy_settings change while a channel runs does not reach it, and the
// second channel is what makes this falsifiable: built AFTER the change from
// the same capture and the same stand-in, it buffers at once, so the only
// difference between the two channels is when their tuning was taken.
//
// buffering_speed 0.1 is the API's MINIMUM (core/serializers.py:96) and the
// normal capture never dips to it, so channel A must never buffer; 10.0 is
// the maximum and every record after the first is below it, so channel B
// must.
func TestABufferingThresholdChangeDoesNotReachARunningChannel(t *testing.T) {
	speeds := relaytest.CorpusSpeeds("normal")
	for i, v := range speeds {
		if v <= 0.1 || (i > 0 && v >= 10.0) {
			t.Fatalf("the normal capture no longer sits between the API's minimum and maximum thresholds after its first record; re-derive (CAPTURE.md)")
		}
	}
	r := transcodeRig(t, map[string]any{"buffering_speed": 0.1, "buffering_timeout": 300},
		"--stderr-corpus", relaytest.CorpusPath("normal"), "--stderr-interval", "0.02", "--stderr-loop")

	running := r.tuneAs(t, "c-before", "client-a")
	defer func() { _ = running.Body.Close() }()
	waitForStats(t, r, "c-before")

	// The operator's save, as the control plane would report it from now
	// on: every LATER next-source answer carries the new threshold.
	r.Control.SetSettings(rigSettings(map[string]any{"buffering_speed": 10.0, "buffering_timeout": 300}))

	// The running channel keeps parsing records (the speed keeps changing)
	// and never buffers.
	seen := map[float64]bool{}
	deadline := time.Now().Add(1500 * time.Millisecond)
	for time.Now().Before(deadline) {
		ch := r.Manager.Get("c-before")
		if state := ch.State(); state == channel.StateBuffering {
			t.Fatal("the running channel picked up the new threshold")
		}
		if speed := ch.Stats().FFmpegSpeed; speed != nil {
			seen[*speed] = true
		}
		time.Sleep(20 * time.Millisecond)
	}
	if len(seen) < 4 {
		t.Fatalf("too few distinct speeds after the change to prove records were still being parsed: %v", seen)
	}

	// Same capture, same stand-in, new channel: it snapshots the NEW
	// threshold and buffers at once.
	after := r.tuneAs(t, "c-after", "client-b")
	defer func() { _ = after.Body.Close() }()
	deadline = time.Now().Add(10 * time.Second)
	for r.Manager.Get("c-after") == nil || r.Manager.Get("c-after").State() != channel.StateBuffering {
		if time.Now().After(deadline) {
			t.Fatal("the channel started after the change never buffered: the new threshold was not snapshotted either")
		}
		time.Sleep(20 * time.Millisecond)
	}
}

// A blank user_agent on the answer falls back to the wire's
// DEFAULT_USER_AGENT on BOTH architectures, as input/manager.py:73 does for
// the whole StreamManager: the transcode source's UDP filter reads it, and
// the Proxy reader sends it (:165). Asserted on the source startTune builds,
// against the fixture's own literal, because nothing about a blank agent is
// visible from outside on a non-UDP transcode tune -- and on the Proxy path
// the provider would see Go's own default instead, which review found the
// first draft allowing.
func TestABlankUserAgentFallsBackToTheWireDefault(t *testing.T) {
	const wireDefault = "VLC/3.0.20 LibVLC/3.0.20"
	t.Run("transcode", func(t *testing.T) {
		cp := relaytest.NewControlPlane(relaytest.ControlPlaneConfig{
			Kind: control.KindTranscode, SourceURL: "udp://239.0.0.1:1234", BlankUserAgent: true,
			Command: "ffmpeg", Argv: []string{"-i", "udp://239.0.0.1:1234"}, Settings: rigSettings(nil),
		})
		t.Cleanup(cp.Close)
		started, err := startTune(context.Background(), tuneDeps{control: &control.Client{Secret: testSecret, BaseURL: cp.URL(), HTTP: control.NewHTTPClient()}, log: slog.Default()}, "c-ua", false)
		if err != nil {
			t.Fatalf("startTune: %v", err)
		}
		source, ok := started.Source.(*channel.TranscodeSource)
		if !ok {
			t.Fatalf("the source is a %T, want *channel.TranscodeSource", started.Source)
		}
		if source.UserAgent != wireDefault {
			t.Fatalf("UserAgent = %q, want the wire's DEFAULT_USER_AGENT", source.UserAgent)
		}
		if source.Command != "ffmpeg" || len(source.Argv) != 2 {
			t.Fatalf("the source was built from the wrong profile: %+v", source)
		}
	})
	t.Run("proxy", func(t *testing.T) {
		cp := relaytest.NewControlPlane(relaytest.ControlPlaneConfig{
			Kind: control.KindProxy, SourceURL: "http://provider.invalid/live.ts", BlankUserAgent: true,
			Settings: rigSettings(nil),
		})
		t.Cleanup(cp.Close)
		started, err := startTune(context.Background(), tuneDeps{control: &control.Client{Secret: testSecret, BaseURL: cp.URL(), HTTP: control.NewHTTPClient()}, log: slog.Default()}, "c-ua-proxy", false)
		if err != nil {
			t.Fatalf("startTune: %v", err)
		}
		source, ok := started.Source.(channel.ProxySource)
		if !ok {
			t.Fatalf("the source is a %T, want channel.ProxySource", started.Source)
		}
		if source.UserAgent != wireDefault {
			t.Fatalf("UserAgent = %q, want the wire's DEFAULT_USER_AGENT -- a blank agent would reach the provider as Go's own", source.UserAgent)
		}
	})
}

// A transcode child that exits non-zero is a connection failure: three of
// them exhaust the source (row 3's accounting), the client's response ends,
// and the channel is in error still carrying the child's code through the
// exhaustion error.
func TestAChildThatExitsNonZeroEndsTheTune(t *testing.T) {
	r := transcodeRig(t, nil, "--exit-after-bytes", "376000", "--exit-code", "2")
	response := r.tuneAs(t, "c-exit", "client-a")
	defer func() { _ = response.Body.Close() }()
	// Taken WHILE the client is attached: once the response ends the
	// client's release drops the channel from the manager, and a Get
	// afterwards finds nothing -- which is correct, and not what this
	// test is about.
	waitForHead(t, r, "c-exit", 1)
	ch := r.Manager.Get("c-exit")
	done := make(chan []byte, 1)
	go func() {
		body, _ := io.ReadAll(response.Body)
		done <- body
	}()
	select {
	case body := <-done:
		if len(body) == 0 {
			t.Fatal("the client received nothing")
		}
	case <-time.After(30 * time.Second):
		t.Fatal("the response never ended after the child exited three times")
	}
	<-ch.Done()
	var exited interface{ Error() string }
	if !errors.As(ch.Err(), &exited) || !strings.Contains(ch.Err().Error(), "status 2") {
		t.Fatalf("Err() = %v, want the child's exit status 2", ch.Err())
	}
	if n := r.Upstream.Requests(); n != 3 {
		t.Fatalf("the provider saw %d requests, want 3: one per attempt on the same source", n)
	}
}

var _ = buffer.TSPacketSize
