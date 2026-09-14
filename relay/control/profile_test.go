package control

import (
	"encoding/json"
	"testing"
)

// The three states of stream_profile.argv, decoded from the wire: a list, an
// explicit null, and an absent key. encoding/json cannot tell the last two
// apart for a plain slice field, and the relay must, because they mean
// different things (an unbuildable profile versus an older Django).
func TestArgvPresenceIsDecodedInAllThreeStates(t *testing.T) {
	for _, tc := range []struct {
		name    string
		body    string
		present bool
		argv    []string
	}{
		{"a built list", `{"id":1,"command":"ffmpeg","args":"-i {streamUrl}","kind":"transcode","argv":["-i","http://p/1.ts"]}`, true, []string{"-i", "http://p/1.ts"}},
		{"an empty list, the Proxy shape", `{"id":2,"command":"","args":"","kind":"proxy","argv":[]}`, true, []string{}},
		{"null, an unbuildable profile", `{"id":3,"command":"ffmpeg","args":"-i \"{streamUrl}","kind":"transcode","argv":null}`, true, nil},
		{"absent, an older control plane", `{"id":4,"command":"ffmpeg","args":"-i {streamUrl}","kind":"transcode"}`, false, nil},
	} {
		t.Run(tc.name, func(t *testing.T) {
			var ref StreamProfileRef
			if err := json.Unmarshal([]byte(tc.body), &ref); err != nil {
				t.Fatalf("decoding: %v", err)
			}
			if ref.ArgvPresent != tc.present {
				t.Fatalf("ArgvPresent = %v, want %v", ref.ArgvPresent, tc.present)
			}
			if (ref.Argv == nil) != (tc.argv == nil) || len(ref.Argv) != len(tc.argv) {
				t.Fatalf("Argv = %#v, want %#v", ref.Argv, tc.argv)
			}
			for i := range tc.argv {
				if ref.Argv[i] != tc.argv[i] {
					t.Fatalf("Argv[%d] = %q, want %q", i, ref.Argv[i], tc.argv[i])
				}
			}
			// The other fields still decode through the custom unmarshaller.
			if ref.Command == "" && tc.name != "an empty list, the Proxy shape" {
				t.Fatal("Command was lost by UnmarshalJSON")
			}
		})
	}
}

// The whole next-source answer, with ffmpeg_stream_profile both null and
// present, through the client's own decoding.
func TestTheFFmpegStreamProfileDecodesNullAndPresent(t *testing.T) {
	var answer NextSourceAnswer
	body := `{"source":{"stream_id":1,"url":"http://p/1.m3u8","user_agent":"ua","transcode":false,"m3u_profile_id":1,
		"slot_reserved":true,"channel_name":"c","stream_name":"s","m3u_profile_name":"m",
		"stream_profile":{"id":1,"command":"","args":"","kind":"proxy","argv":[]},
		"ffmpeg_stream_profile":{"id":9,"command":"ffmpeg","args":"-i {streamUrl}","kind":"transcode","argv":["-i","http://p/1.m3u8"]}},
		"alternates":[],"error":null,"proxy_settings":{}}`
	if err := json.Unmarshal([]byte(body), &answer); err != nil {
		t.Fatalf("decoding: %v", err)
	}
	if answer.Source.FFmpegStreamProfile == nil || answer.Source.FFmpegStreamProfile.ID != 9 {
		t.Fatalf("ffmpeg_stream_profile = %+v, want id 9", answer.Source.FFmpegStreamProfile)
	}
	if !answer.Source.FFmpegStreamProfile.ArgvPresent || len(answer.Source.FFmpegStreamProfile.Argv) != 2 {
		t.Fatalf("ffmpeg_stream_profile.argv = %#v, want two elements", answer.Source.FFmpegStreamProfile.Argv)
	}
	if err := json.Unmarshal([]byte(`{"source":{"stream_profile":{"id":1,"kind":"proxy"},"ffmpeg_stream_profile":null}}`), &answer); err != nil {
		t.Fatalf("decoding a null ffmpeg_stream_profile: %v", err)
	}
	if answer.Source.FFmpegStreamProfile != nil {
		t.Fatal("a null ffmpeg_stream_profile decoded as present")
	}
}
