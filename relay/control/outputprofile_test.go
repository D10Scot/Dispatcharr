package control

import (
	"encoding/json"
	"reflect"
	"testing"
)

// THE OUTPUT PROFILE ARGV CARRIES THE COMMAND AS ELEMENT 0, where
// stream_profile.argv does not. The literal below is
// apps/proxy/tests/test_next_source_api.py:551's own expected value, read off
// that line rather than computed from the model: core/models.py:200-203's
// build_command is `[self.command] + shlex_split(self.parameters)` and
// apps/proxy/serializers.py:230 sends the result whole, while
// apps/proxy/next_source.py's _stream_profile_ref sends `command` separately
// and argv without it.
//
// A DIFFERENT SHAPE ON THE SAME WIRE IS EASY TO GET WRONG IN ONE DIRECTION
// ONLY: a relay that stripped element 0 here would spawn `-i` with the real
// command as its first argument, which fails loudly; one that did NOT strip it
// where stream_profile needs it would pass the command twice. Both are pinned,
// this one here.
func TestTheOutputProfileArgvCarriesTheCommandFirst(t *testing.T) {
	const body = `{"id": 4, "argv": ["ffmpeg", "-i", "pipe:0", "-c:a", "ac3", "pipe:1"]}`
	var ref OutputProfileRef
	if err := json.Unmarshal([]byte(body), &ref); err != nil {
		t.Fatalf("decoding the entry: %v", err)
	}
	if ref.ID != 4 {
		t.Fatalf("the entry's id is %d, want 4", ref.ID)
	}
	if got := ref.Command(); got != "ffmpeg" {
		t.Fatalf("Command() is %q, want argv[0] -- ffmpeg", got)
	}
	want := []string{"-i", "pipe:0", "-c:a", "ac3", "pipe:1"}
	if got := ref.Args(); !reflect.DeepEqual(got, want) {
		t.Fatalf("Args() is %v, want everything after argv[0]: %v", got, want)
	}
}

// AN ABSENT output_profiles KEY IS NOT AN EMPTY MAP, and encoding/json cannot
// tell them apart on a plain map field -- both leave it nil. The distinction
// is load-bearing: an empty object is a deployment with no active profile (and
// Django always sends one, pinned by
// apps/proxy/tests/test_next_source_api.py::
// test_no_active_profiles_is_an_empty_object_not_a_missing_key), while an
// absent key is a control plane older than Phase 2 PR 2b-2, which a tune
// naming a profile must fail on rather than serve plain.
//
// THE TWO CASES ARE ASSERTED AGAINST EACH OTHER in one test, so a decoder that
// collapsed them could not pass half of it.
func TestAnAbsentOutputProfilesKeyIsNotAnEmptyOne(t *testing.T) {
	for _, tc := range []struct {
		name    string
		body    string
		present bool
		size    int
	}{
		{"absent", `{"source": null, "error": null, "alternates": []}`, false, 0},
		{"empty object", `{"source": null, "error": null, "alternates": [], "output_profiles": {}}`, true, 0},
		{"one entry", `{"source": null, "error": null, "alternates": [], "output_profiles": {"4": {"id": 4, "argv": ["ffmpeg", "pipe:1"]}}}`, true, 1},
		// Not a shape Django sends; decoded rather than rejected so an
		// unexpected null cannot be read as "the key was there with entries".
		{"explicit null", `{"source": null, "error": null, "alternates": [], "output_profiles": null}`, true, 0},
	} {
		t.Run(tc.name, func(t *testing.T) {
			var answer NextSourceAnswer
			if err := json.Unmarshal([]byte(tc.body), &answer); err != nil {
				t.Fatalf("decoding the answer: %v", err)
			}
			if answer.OutputProfilesPresent != tc.present {
				t.Fatalf("OutputProfilesPresent is %v, want %v", answer.OutputProfilesPresent, tc.present)
			}
			if len(answer.OutputProfiles) != tc.size {
				t.Fatalf("the map holds %d entries, want %d", len(answer.OutputProfiles), tc.size)
			}
		})
	}
}

// A NULL argv IS DJANGO SAYING IT COULD NOT BUILD THE LIST -- shlex refused
// the profile's parameters, which OutputProfileSerializer validates nothing
// against. It is a DIFFERENT fault from the profile being absent and gets a
// different answer, so the decode must keep them apart: nil Argv with the
// entry present.
func TestANullOutputProfileArgvDecodesAsPresentButUnbuildable(t *testing.T) {
	const body = `{"source": null, "error": null, "alternates": [], "output_profiles": {"9": {"id": 9, "argv": null}}}`
	var answer NextSourceAnswer
	if err := json.Unmarshal([]byte(body), &answer); err != nil {
		t.Fatalf("decoding the answer: %v", err)
	}
	entry, found := answer.OutputProfiles["9"]
	if !found {
		t.Fatal("the entry with a null argv vanished from the map; an unbuildable profile must stay visible")
	}
	if entry.Argv != nil {
		t.Fatalf("a null argv decoded as %v, want nil", entry.Argv)
	}
	if got := entry.Command(); got != "" {
		t.Fatalf("Command() is %q for a null argv, want the empty string", got)
	}
	// And an EMPTY LIST is not the same thing: Django sends [] for a profile
	// whose build_command somehow produced nothing, which is still "built".
	const empty = `{"source": null, "error": null, "alternates": [], "output_profiles": {"9": {"id": 9, "argv": []}}}`
	var second NextSourceAnswer
	if err := json.Unmarshal([]byte(empty), &second); err != nil {
		t.Fatalf("decoding the empty-argv answer: %v", err)
	}
	if second.OutputProfiles["9"].Argv == nil {
		t.Fatal("an empty argv list decoded as nil, which is how a NULL argv is spelled")
	}
}
