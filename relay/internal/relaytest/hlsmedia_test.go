package relaytest_test

import (
	"testing"

	"github.com/D10Scot/Dispatcharr/relay/hls"
	"github.com/D10Scot/Dispatcharr/relay/internal/relaytest"
)

// The synthetic HLS media is copied from relay/hls's test helpers, so it is
// held to what relay/hls itself accepts: a builder that drifted would let
// every httpapi test built on it pass against media the real reader refuses.
func TestTheSyntheticHLSMediaParses(t *testing.T) {
	for _, tc := range []struct {
		name  string
		bytes []byte
		codec string
		frags int
	}{
		{"video", relaytest.HLSVideoStream(4, 50), "avc1.64002a", 4},
		{"aac", relaytest.HLSAACStream(6), "mp4a.40.2", 6},
	} {
		t.Run(tc.name, func(t *testing.T) {
			// The init is everything up to the first moof.
			moof := indexOf(tc.bytes, []byte("moof"))
			if moof < 4 {
				t.Fatal("no moof in the stream")
			}
			init := tc.bytes[:moof-4]
			track, err := hls.ParseInit(init)
			if err != nil {
				t.Fatalf("ParseInit: %v", err)
			}
			if track.Codec != tc.codec {
				t.Fatalf("codec %q, want %q", track.Codec, tc.codec)
			}
			rest := tc.bytes[len(init):]
			seen := 0
			for len(rest) > 0 {
				moofSize := int(rest[0])<<24 | int(rest[1])<<16 | int(rest[2])<<8 | int(rest[3])
				mdatSize := int(rest[moofSize])<<24 | int(rest[moofSize+1])<<16 | int(rest[moofSize+2])<<8 | int(rest[moofSize+3])
				whole := rest[:moofSize+mdatSize]
				frag, err := hls.ParseFragment(whole, track)
				if err != nil {
					t.Fatalf("ParseFragment %d: %v", seen, err)
				}
				if !frag.Sync || frag.Samples == 0 {
					t.Fatalf("fragment %d: sync %t, samples %d", seen, frag.Sync, frag.Samples)
				}
				seen++
				rest = rest[len(whole):]
			}
			if seen != tc.frags {
				t.Fatalf("%d fragments parsed, want %d", seen, tc.frags)
			}
		})
	}

	both, err := hls.ParseProbe(relaytest.HLSProbeJSON(true, true))
	if err != nil || both.Video == nil || len(both.Qualifying()) != 1 {
		t.Fatalf("the video+audio probe: %+v, %v", both, err)
	}
	audioOnly, err := hls.ParseProbe(relaytest.HLSProbeJSON(false, true))
	if err != nil || audioOnly.Video != nil {
		t.Fatalf("the audio-only probe: %+v, %v", audioOnly, err)
	}
}

func indexOf(haystack, needle []byte) int {
	for i := 0; i+len(needle) <= len(haystack); i++ {
		if string(haystack[i:i+len(needle)]) == string(needle) {
			return i
		}
	}
	return -1
}
