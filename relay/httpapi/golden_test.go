package httpapi

import (
	"encoding/json"
	"net/http"
	"os"
	"reflect"
	"sort"
	"testing"

	"github.com/D10Scot/Dispatcharr/relay/internal/relaytest"
)

// goldenPath holds a payload rendered by DJANGO'S OWN SERIALIZER --
// apps/proxy/relay_serializers.py's RelayChannelListSerializer -- from the
// fixture apps/proxy/tests/test_relay_list_payload_golden.py builds. It is the
// oracle for this endpoint's absent-versus-null-versus-present behaviour, and
// it is produced by the OTHER implementation, which is the only thing that
// makes it able to fail (hollow shape 1: an expected value the code under test
// computes cannot fail).
//
// Regenerate it with the command in this PR's Task, never by running the Go.
const goldenPath = "testdata/channels_clients_all.json"

// goldenPayload is the Go value the golden file must describe: two channels,
// one with every conditional field set and two clients, one with none and no
// clients at all. Every present/absent/null case this endpoint can produce is
// in here, which is what makes the comparison a check on the SHAPE rather than
// on one happy path.
func goldenPayload() channelListPayload {
	state := "active"
	stopped := "stopped"
	var noOwner *string
	streamID := 41
	m3uProfileID := 3
	total := uint64(9_999_888)
	kbps := 2_665.3034666666666
	startedA := 1_789_000_000.5
	startedB := 1_789_000_100.0
	uaA := "VLC/3.0.20"
	var uaAbsent *string
	profileID := 7

	return channelListPayload{
		Count: 2,
		Channels: []channelPayload{
			{
				ChannelID:      "11111111-1111-4111-8111-111111111111",
				State:          &state,
				URL:            "http://provider.invalid/live/sub/pw/41.ts",
				StreamProfile:  "1",
				Owner:          noOwner,
				BufferIndex:    120,
				ClientCount:    2,
				Uptime:         30.0,
				StartedAt:      &startedA,
				ChannelName:    "BBC One HD",
				M3UProfileID:   &m3uProfileID,
				StreamID:       &streamID,
				StreamName:     "BBC One HD (UK)",
				TotalBytes:     &total,
				AvgBitrateKbps: &kbps,
				AvgBitrate:     "2.67 Mbps",
				Clients: []clientPayload{
					{
						ClientID:        "client_1789000000000_1234",
						UserAgent:       &uaA,
						OutputFormat:    "mpegts",
						OutputProfileID: &profileID,
						IPAddress:       "198.51.100.4",
						ConnectedAt:     1_789_000_001.25,
						UserID:          "7",
					},
					{
						ClientID:        "client_1789000000000_5678",
						UserAgent:       uaAbsent,
						OutputFormat:    "mpegts",
						OutputProfileID: nil,
					},
				},
			},
			{
				ChannelID:     "22222222-2222-4222-8222-222222222222",
				State:         &stopped,
				URL:           "",
				StreamProfile: "0",
				Owner:         noOwner,
				BufferIndex:   0,
				ClientCount:   0,
				Uptime:        0,
				StartedAt:     &startedB,
				Clients:       []clientPayload{},
			},
		},
	}
}

// THE CROSS-IMPLEMENTATION PIN. Decoded rather than byte-compared, and that is
// a decision with one known consequence: DRF renders a Python float as "5.0"
// where encoding/json renders float64(5) as "5". Decoding both sides into
// map[string]any makes each a float64 and the spellings equal, which is right,
// because every consumer parses -- relay_client._request calls .json() and
// api.js parses -- and none compares bytes. What the decode does NOT lose is
// the part that matters: an absent key stays absent, a null stays nil, and a
// string stays a string, so the presence contract is still fully pinned.
func TestTheListPayloadMatchesDjangosSerializer(t *testing.T) {
	want := decodeGolden(t)

	encoded, err := json.Marshal(goldenPayload())
	if err != nil {
		t.Fatalf("encoding the payload: %v", err)
	}
	var got any
	if err := json.Unmarshal(encoded, &got); err != nil {
		t.Fatalf("decoding this relay's own payload: %v", err)
	}

	if !reflect.DeepEqual(got, want) {
		t.Fatalf("this relay's list payload differs from the one Django's "+
			"RelayChannelListSerializer renders from the same fixture.\n got: %s\nwant: %s",
			encoded, mustMarshal(t, want))
	}
}

// The presence contract, named field by field, so a failure says WHICH key
// moved rather than printing two blobs. A struct tag losing its omitempty, or
// gaining one it must not have, is exactly the edit this catches and the
// DeepEqual above reports only as "they differ".
func TestEveryOptionalFieldIsAbsentRatherThanNull(t *testing.T) {
	encoded, err := json.Marshal(goldenPayload())
	if err != nil {
		t.Fatalf("encoding the payload: %v", err)
	}
	var payload struct {
		Channels []map[string]any `json:"channels"`
	}
	if err := json.Unmarshal(encoded, &payload); err != nil {
		t.Fatalf("decoding: %v", err)
	}

	// The nine get_basic_channel_info sets unconditionally, three of them
	// nullable (channel_status.py:469-479).
	always := []string{
		"channel_id", "state", "url", "stream_profile", "owner",
		"buffer_index", "client_count", "uptime", "started_at", "clients",
	}
	for i, ch := range payload.Channels {
		for _, key := range always {
			if _, present := ch[key]; !present {
				t.Errorf("channel %d has no %q: get_basic_channel_info sets it on every path, "+
					"so it must never be omitted", i, key)
			}
		}
		if ch["owner"] != nil {
			t.Errorf("channel %d reports owner %v, want null: spec D2 deletes the ownership "+
				"election, so there is no worker to name", i, ch["owner"])
		}
	}

	// The minimal channel carries none of the conditional keys.
	minimal := payload.Channels[1]
	for _, key := range []string{
		"channel_name", "logo_id", "m3u_profile_id", "stream_id", "stream_name",
		"total_bytes", "avg_bitrate_kbps", "avg_bitrate", "healthy",
		"video_codec", "resolution", "source_fps", "ffmpeg_speed",
		"audio_codec", "audio_channels", "stream_type",
	} {
		if _, present := minimal[key]; present {
			t.Errorf("a channel with no %s still carries the key, as %v: DRF declares it "+
				"required=False with no default, so an unset key VANISHES rather than "+
				"rendering as null", key, minimal[key])
		}
	}

	// The clientless channel still carries an EMPTY LIST, never an absent key
	// and never null (channel_status.py:587 assigns it on every path).
	clients, present := minimal["clients"].([]any)
	if !present || clients == nil {
		t.Fatalf("a channel with no clients rendered clients as %v, want []", minimal["clients"])
	}
	if len(clients) != 0 {
		t.Fatalf("the clientless channel lists %d clients", len(clients))
	}

	// Per-client presence: four keys always, three only when truthy.
	rows, _ := payload.Channels[0]["clients"].([]any)
	if len(rows) != 2 {
		t.Fatalf("the populated channel lists %d clients, want 2", len(rows))
	}
	full, _ := rows[0].(map[string]any)
	bare, _ := rows[1].(map[string]any)
	for _, key := range []string{"client_id", "user_agent", "output_format", "output_profile_id"} {
		if _, present := bare[key]; !present {
			t.Errorf("a client with nothing optional set has no %q: it is assigned on every "+
				"path in channel_status.py and must always be present", key)
		}
	}
	for _, key := range []string{"ip_address", "connected_at", "user_id"} {
		if _, present := bare[key]; present {
			t.Errorf("a client with no %s still carries the key, as %v: it is set inside an "+
				"`if` and must vanish when unset", key, bare[key])
		}
		if _, present := full[key]; !present {
			t.Errorf("a fully populated client has no %q", key)
		}
	}
	if bare["user_agent"] != nil {
		t.Errorf("a client whose hash carried no user_agent reports %v, want null: hmget "+
			"returns None and the field is allow_null", bare["user_agent"])
	}
	if bare["output_profile_id"] != nil {
		t.Errorf("a client with no Output Profile reports %v, want null", bare["output_profile_id"])
	}
	if _, isString := full["user_id"].(string); !isString {
		t.Errorf("user_id rendered as %T, want a string: RelayChannelClientSerializer declares "+
			"CharField and relay_client.live_connections int()s it itself", full["user_id"])
	}
}

// The handler's live output has the same key set as the golden's populated
// channel. Without this, the two tests above pin a struct literal and nothing
// pins that the handler builds it.
func TestTheLiveEndpointProducesTheGoldensKeySet(t *testing.T) {
	r := fanRig(t, relaytest.Config{Rate: 4}, nil)
	response := r.tuneAs(t, "c-keys", "client-a")
	defer func() { _ = response.Body.Close() }()

	// The channel must have published at least one chunk, so total_bytes and
	// the two bitrate fields are present -- they are exactly the conditional
	// fields the golden's populated channel carries.
	waitForHead(t, r, "c-keys", 1)

	status, body := r.listChannels(t, "?clients=all")
	if status != http.StatusOK {
		t.Fatalf("the list endpoint answered %d, want 200", status)
	}
	var live struct {
		Channels []map[string]any `json:"channels"`
	}
	if err := json.Unmarshal(body, &live); err != nil {
		t.Fatalf("decoding the live body: %v", err)
	}
	if len(live.Channels) != 1 {
		t.Fatalf("the relay listed %d channels, want 1", len(live.Channels))
	}

	encoded, _ := json.Marshal(goldenPayload())
	var golden struct {
		Channels []map[string]any `json:"channels"`
	}
	_ = json.Unmarshal(encoded, &golden)

	if got, want := keysOf(live.Channels[0]), keysOf(golden.Channels[0]); !reflect.DeepEqual(got, want) {
		t.Fatalf("the live payload's keys are\n  %v\nand the golden's populated channel's are\n  %v\n"+
			"-- the handler and the shape this endpoint promises have diverged", got, want)
	}
	// Asserted on the LIVE payload, not on goldenPayload(): the struct literal
	// hard-codes a nil owner, so an assertion there cannot see a handler that
	// started naming one. The break-check that put a process identity in
	// describeChannel left this test green until this line went in.
	if live.Channels[0]["owner"] != nil {
		t.Fatalf("the handler reported owner %v, want null -- spec D2 deletes the ownership "+
			"election, so there is no worker to name", live.Channels[0]["owner"])
	}

	liveClients, _ := live.Channels[0]["clients"].([]any)
	if len(liveClients) != 1 {
		t.Fatalf("the live payload lists %d clients, want 1", len(liveClients))
	}
	goldenClients, _ := golden.Channels[0]["clients"].([]any)
	liveRow, _ := liveClients[0].(map[string]any)
	goldenRow, _ := goldenClients[0].(map[string]any)
	if got, want := keysOf(liveRow), keysOf(goldenRow); !reflect.DeepEqual(got, want) {
		t.Fatalf("the live client row's keys are\n  %v\nand the golden's are\n  %v", got, want)
	}
}

func keysOf(m map[string]any) []string {
	out := make([]string, 0, len(m))
	for k := range m {
		out = append(out, k)
	}
	sort.Strings(out)
	return out
}

func decodeGolden(t *testing.T) any {
	t.Helper()
	raw, err := os.ReadFile(goldenPath)
	if err != nil {
		t.Fatalf("reading %s: %v -- regenerate it with this PR's Python command", goldenPath, err)
	}
	var want any
	if err := json.Unmarshal(raw, &want); err != nil {
		t.Fatalf("decoding %s: %v", goldenPath, err)
	}
	return want
}

func mustMarshal(t *testing.T, v any) string {
	t.Helper()
	raw, err := json.Marshal(v)
	if err != nil {
		t.Fatalf("marshalling: %v", err)
	}
	return string(raw)
}
