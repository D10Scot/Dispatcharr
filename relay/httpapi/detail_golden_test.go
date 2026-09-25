package httpapi

import (
	"encoding/json"
	"os"
	"reflect"
	"testing"
)

// detailGoldenPath holds a payload rendered by DJANGO'S OWN SERIALIZER --
// apps/proxy/relay_serializers.py's RelayChannelDetailSerializer -- from the
// fixture apps/proxy/tests/test_relay_detail_payload_golden.py builds.
//
// The sibling of goldenPath, and for the same reason: the oracle is produced
// by the OTHER implementation, which is the only thing that makes it able to
// fail (hollow shape 1).
//
// Regenerate it with the command in this PR's Task 2, never by running the Go.
const detailGoldenPath = "testdata/channel_detail.json"

// detailGoldenPayload is the Go value the golden file must describe: one
// channel with every conditional field set, a TS client carrying the three
// byte counters and an fMP4 client carrying none of them.
func detailGoldenPayload() detailPayload {
	state := "active"
	streamID := 41
	m3uProfileID := 3
	total := uint64(9_999_888)
	kbps := 2_665.3034666666666
	speed := 1.02
	profileID := 7
	bytesSent := int64(9_999_888)
	avgRate := 341.2
	currentRate := 348.9

	return detailPayload{
		ChannelID:      "11111111-1111-4111-8111-111111111111",
		State:          &state,
		URL:            "http://provider.invalid/live/sub/pw/41.ts",
		StreamProfile:  "1",
		StartedAt:      1_789_000_000.5,
		Owner:          OwnerUnknown,
		BufferIndex:    120,
		ChannelName:    "BBC One HD",
		StreamID:       &streamID,
		StreamName:     "BBC One HD (UK)",
		M3UProfileID:   &m3uProfileID,
		M3UProfileName: "Premium",
		StateChangedAt: 1_789_000_005.0,
		StateDuration:  25.5,
		Uptime:         30.0,
		TotalBytes:     &total,
		TotalData:      "9.54 MB",
		AvgBitrateKbps: &kbps,
		AvgBitrate:     "2.67 Mbps",
		ClientCount:    2,
		BufferStats: bufferStatsPayload{
			Chunks: 120,
			Diagnostics: map[string]any{
				"first_chunk": map[string]any{
					"index":      uint64(116),
					"size":       255868,
					"ts_packets": 1361,
					"aligned":    true,
					"first_byte": byte(0x47),
				},
			},
			AvgChunkSize:     ptr(255868.0),
			RecentChunkSizes: []int{255868, 255868, 255868, 255868, 255868},
			KeysFound:        []uint64{116, 117, 118, 119, 120},
			KeysMissing:      ptr([]uint64{}),
			TotalSampleBytes: ptr(1_279_340),
			EstimatedPackets: ptr(6805),
			IsTSAligned:      ptr(true),
		},
		LocalManager: localManagerPayload{
			Healthy:      true,
			Connected:    true,
			LastDataTime: 1_789_000_029.5,
			LastDataAge:  0.5,
		},
		VideoCodec:    "h264",
		Resolution:    "1920x1080",
		Width:         "1920",
		Height:        "1080",
		VideoBitrate:  "4500.0",
		SourceFPS:     "25.0",
		PixelFormat:   "yuv420p",
		AudioCodec:    "aac",
		SampleRate:    "48000",
		AudioChannels: "stereo",
		AudioBitrate:  "128.0",
		FFmpegSpeed:   &speed,
		FFmpegFPS:     "25.0",
		ActualFPS:     "24.5",
		FFmpegBitrate: "4200.0",
		StreamType:    "mpegts",
		Clients: []detailClientPayload{
			{
				ClientID:        "client_1789000000000_1234",
				UserAgent:       "VLC/3.0.20",
				WorkerID:        WorkerUnknown,
				IPAddress:       "198.51.100.4",
				UserID:          "7",
				OutputFormat:    "mpegts",
				OutputProfileID: &profileID,
				ConnectedAt:     1_789_000_001.25,
				LastActive:      1_789_000_029.5,
				LastActiveAgo:   0.5,
				BytesSent:       &bytesSent,
				AvgRateKBps:     &avgRate,
				CurrentRateKBps: &currentRate,
			},
			{
				ClientID:        "client_1789000000000_5678",
				UserAgent:       "unknown",
				WorkerID:        WorkerUnknown,
				IPAddress:       "198.51.100.9",
				UserID:          "0",
				OutputFormat:    "fmp4",
				OutputProfileID: nil,
				ConnectedAt:     1_789_000_010.0,
				LastActive:      1_789_000_029.0,
				LastActiveAgo:   1.0,
			},
		},
	}
}

func ptr[T any](v T) *T { return &v }

func decodeDetailGolden(t *testing.T) any {
	t.Helper()
	raw, err := os.ReadFile(detailGoldenPath)
	if err != nil {
		t.Fatalf("reading %s: %v -- regenerate it with "+
			"DISPATCHARR_WRITE_GOLDEN=1 python manage.py test "+
			"apps.proxy.tests.test_relay_detail_payload_golden", detailGoldenPath, err)
	}
	var want any
	if err := json.Unmarshal(raw, &want); err != nil {
		t.Fatalf("decoding %s: %v", detailGoldenPath, err)
	}
	return want
}

// Compared as PARSED JSON, not bytes, for the list golden's reason (Amendment
// A3.7): DRF renders a Python float as "5.0" where encoding/json renders
// float64(5) as "5", every consumer parses, and nothing compares bytes. What
// the decode does not lose is the part that matters -- an absent key stays
// absent, a null stays nil, a string stays a string.
func TestTheDetailPayloadMatchesDjangosSerializer(t *testing.T) {
	want := decodeDetailGolden(t)

	encoded, err := json.Marshal(detailGoldenPayload())
	if err != nil {
		t.Fatalf("encoding the payload: %v", err)
	}
	var got any
	if err := json.Unmarshal(encoded, &got); err != nil {
		t.Fatalf("decoding this relay's own payload: %v", err)
	}
	if !reflect.DeepEqual(got, want) {
		t.Fatalf("this relay's detail payload differs from the one Django's "+
			"RelayChannelDetailSerializer renders from the same fixture.\n got: %s\nwant: %s",
			encoded, mustMarshal(t, want))
	}
}

// Row 14, both clauses that differ BETWEEN the two endpoints, asserted
// against the two goldens together.
//
// A test that checked the string against only one endpoint proves nothing
// about the other -- the row's own Notes say exactly that -- so this reads
// both payloads in one test and would fail if either moved.
func TestOwnerAndSourceFPSDifferBetweenTheTwoEndpoints(t *testing.T) {
	detail, ok := decodeDetailGolden(t).(map[string]any)
	if !ok {
		t.Fatalf("the detail golden is not an object")
	}
	list, ok := decodeGolden(t).(map[string]any)
	if !ok {
		t.Fatalf("the list golden is not an object")
	}
	first, ok := list["channels"].([]any)[0].(map[string]any)
	if !ok {
		t.Fatalf("the list golden's first channel is not an object")
	}

	if detail["owner"] != OwnerUnknown {
		t.Errorf("owner on the detail endpoint is %v, want the literal %q "+
			"(channel_status.py:45's default; parity-matrix row 14)", detail["owner"], OwnerUnknown)
	}
	if first["owner"] != nil {
		t.Errorf("owner on the list endpoint is %v, want null (channel_status.py:474)", first["owner"])
	}

	if _, isString := detail["source_fps"].(string); !isString {
		t.Errorf("source_fps on the detail endpoint is %T, want a string: row 14's "+
			"third clause, which Phase 1 PR 7 did NOT unify", detail["source_fps"])
	}
	if _, isFloat := first["source_fps"].(float64); !isFloat {
		t.Errorf("source_fps on the list endpoint is %T, want a number", first["source_fps"])
	}

	// And the clause that IS unified, so "the two endpoints simply disagree
	// about everything" cannot be what makes this pass.
	if _, isFloat := detail["ffmpeg_speed"].(float64); !isFloat {
		t.Errorf("ffmpeg_speed on the detail endpoint is %T, want a number: PR 7 unified "+
			"it and parity holds it unified", detail["ffmpeg_speed"])
	}
	if _, isFloat := first["ffmpeg_speed"].(float64); !isFloat {
		t.Errorf("ffmpeg_speed on the list endpoint is %T, want a number", first["ffmpeg_speed"])
	}
}

// Issue #314, FIXED: ffmpeg_bitrate is on the payload, a string like the
// other detail-endpoint rates. Asserted against the GOLDEN, which Django's
// serializer rendered, so a relay that emitted the key under another name
// fails here. That source_bitrate is gone from the SERIALIZER is pinned on
// the Python side, by test_the_fixture_covers_every_serializer_field with
// NEVER_WRITTEN empty: a golden rendered from a fixture that never set the
// key cannot tell whether the serializer still declares it.
func TestTheDetailPayloadCarriesTheFFmpegOutputBitrate(t *testing.T) {
	golden, ok := decodeDetailGolden(t).(map[string]any)
	if !ok {
		t.Fatalf("the detail golden is not an object")
	}
	if got, isString := golden["ffmpeg_bitrate"].(string); !isString || got == "" {
		t.Errorf("ffmpeg_bitrate on the detail golden is %v (%T), want the output bitrate as a string (#314)", golden["ffmpeg_bitrate"], golden["ffmpeg_bitrate"])
	}
}

// RE-HOMED BY PHASE 2 STAGE 2d-4. The one assertion of
// apps/proxy/tests/test_relay_status_shape.py's ten that had no cover on
// either side -- its test_the_three_dvr_fields_are_absent_when_redis_has_none.
// That file drove the deleted ChannelStatus builders directly, so it went with
// apps/proxy/live_proxy/; the property it pinned did not, and the golden above
// cannot carry it because its fixture is one fully-populated channel.
//
// The three fields are `string` + `,omitempty` at detail.go:159-161 and are
// assigned only when the source stats carry them (:311-318), so an unset field
// must VANISH rather than render as "" -- the same contract
// TestEveryOptionalFieldIsAbsentRatherThanNull holds the LIST payload to, and
// a distinct one, because width/height/video_bitrate exist on the detail
// payload alone.
func TestTheDetailPayloadOmitsTheDVRVideoFieldsWhenNothingSetThem(t *testing.T) {
	payload := detailGoldenPayload()
	payload.Width = ""
	payload.Height = ""
	payload.VideoBitrate = ""

	encoded, err := json.Marshal(payload)
	if err != nil {
		t.Fatalf("encoding the payload: %v", err)
	}
	var decoded map[string]any
	if err := json.Unmarshal(encoded, &decoded); err != nil {
		t.Fatalf("decoding: %v", err)
	}
	for _, key := range []string{"width", "height", "video_bitrate"} {
		if _, present := decoded[key]; present {
			t.Errorf("an unset %q still renders, as %v: DRF declares it required=False "+
				"with no default, so the key must vanish rather than carry an empty "+
				"string", key, decoded[key])
		}
	}
	// And they DO render when set, so a struct-tag typo cannot make this pass.
	for _, key := range []string{"width", "height", "video_bitrate"} {
		if _, present := mustDecodeDetail(t, detailGoldenPayload())[key]; !present {
			t.Errorf("the populated detail payload is missing %q", key)
		}
	}
}

func mustDecodeDetail(t *testing.T, payload any) map[string]any {
	t.Helper()
	encoded, err := json.Marshal(payload)
	if err != nil {
		t.Fatalf("encoding the payload: %v", err)
	}
	var decoded map[string]any
	if err := json.Unmarshal(encoded, &decoded); err != nil {
		t.Fatalf("decoding: %v", err)
	}
	return decoded
}
