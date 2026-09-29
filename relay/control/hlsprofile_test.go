package control

import (
	"encoding/json"
	"testing"
)

// hls_profile IS THREE STATES ON THE WIRE and a plain pointer field can tell
// only two of them apart: an ABSENT key is a control plane older than 4a-1d (a
// contract mismatch an HLS entry answers 502 for), JSON null is "the channel
// has no HLS profile" (the built-in re-encode), and an object is the profile.
// Asserted against each other in one table so a decoder that collapsed any two
// could not pass.
func TestTheHLSProfileKeyDecodesInThreeStates(t *testing.T) {
	for _, tc := range []struct {
		name    string
		body    string
		present bool
		want    *HLSProfileRef
		wantErr bool
	}{
		{"absent", `{"source": null, "error": null, "alternates": []}`, false, nil, false},
		{"null", `{"source": null, "error": null, "alternates": [], "hls_profile": null}`, true, nil, false},
		{"object", `{"source": null, "error": null, "alternates": [], "hls_profile": {"id": 7, "mode": "automatic"}}`, true, &HLSProfileRef{ID: 7, Mode: "automatic"}, false},
		{"malformed", `{"source": null, "error": null, "alternates": [], "hls_profile": {"id": "x"}}`, false, nil, true},
	} {
		t.Run(tc.name, func(t *testing.T) {
			var answer NextSourceAnswer
			err := json.Unmarshal([]byte(tc.body), &answer)
			if tc.wantErr {
				if err == nil {
					t.Fatalf("decoded %s without error; a malformed hls_profile must be a decode error", tc.body)
				}
				return
			}
			if err != nil {
				t.Fatalf("decoding %s: %v", tc.body, err)
			}
			if answer.HLSProfilePresent != tc.present {
				t.Fatalf("HLSProfilePresent = %t, want %t", answer.HLSProfilePresent, tc.present)
			}
			switch {
			case tc.want == nil && answer.HLSProfile != nil:
				t.Fatalf("HLSProfile = %+v, want nil", *answer.HLSProfile)
			case tc.want != nil && (answer.HLSProfile == nil || *answer.HLSProfile != *tc.want):
				t.Fatalf("HLSProfile = %v, want %+v", answer.HLSProfile, *tc.want)
			}
		})
	}
}
