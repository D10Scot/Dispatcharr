package relaytest

import (
	"slices"
	"testing"
)

// The synthetic asset's own pins. They exist for the reason asset_test.go's do:
// every fMP4 test in this module takes these bytes as its oracle, so a change
// to the generator that made a "fragment" something the scanner would not split
// at would make the tests it feeds pass against a subject that had stopped being
// the subject.

func TestTheSyntheticInitSegmentIsFtypThenMoovAndNoFragment(t *testing.T) {
	_, _, types := MP4Boxes(SyntheticFMP4Init())
	if !slices.Equal(types, []string{"ftyp", "moov"}) {
		t.Fatalf("the synthetic init segment's boxes are %v, want exactly ftyp then moov", types)
	}
}

func TestASyntheticFragmentIsMoofThenMdatAndCarriesItsIndex(t *testing.T) {
	for _, index := range []int{0, 1, 41, 1000} {
		fragment := SyntheticFMP4Fragment(index)
		_, _, types := MP4Boxes(fragment)
		if !slices.Equal(types, []string{"moof", "mdat"}) {
			t.Fatalf("fragment %d's boxes are %v, want moof then mdat", index, types)
		}
		if got := FMP4FragmentIndex(fragment); got != index {
			t.Fatalf("fragment %d reads back as %d", index, got)
		}
	}
}

func TestFMP4FragmentIndexRefusesWhatIsNotAFragment(t *testing.T) {
	// -1 rather than a plausible number, so a test that accidentally passed an
	// init segment or a raw TS packet to it fails rather than comparing against
	// whatever four bytes happened to be at offset 8.
	for name, data := range map[string][]byte{
		"an init segment": SyntheticFMP4Init(),
		"a TS packet":     SyntheticTS(1, 0x100),
		"nothing":         nil,
		"a short buffer":  {0, 0, 0, 16, 'm', 'o', 'o'},
	} {
		if got := FMP4FragmentIndex(data); got != -1 {
			t.Fatalf("FMP4FragmentIndex(%s) returned %d, want -1", name, got)
		}
	}
}

func TestFMP4ShapeProblemAcceptsOnlyAnInitSegmentFollowedByAFragment(t *testing.T) {
	// A helper that accepted everything would silently disarm every test that
	// uses it, which is exactly the "test gone hollow without changing" shape.
	// So the accepting case and three rejecting ones are asserted together.
	whole := slices.Concat(SyntheticFMP4Init(), SyntheticFMP4Fragment(0), SyntheticFMP4Fragment(1))
	if problem := FMP4ShapeProblem(whole); problem != "" {
		t.Fatalf("FMP4ShapeProblem rejected a well-formed stream: %s", problem)
	}
	for name, data := range map[string][]byte{
		"an init segment with no fragment": SyntheticFMP4Init(),
		"a fragment with no init segment":  SyntheticFMP4Fragment(0),
		"a TS stream":                      SyntheticTS(4, 0x100),
		"nothing at all":                   nil,
	} {
		if problem := FMP4ShapeProblem(data); problem == "" {
			t.Fatalf("FMP4ShapeProblem accepted %s", name)
		}
	}
}

func TestMP4BoxesStopsAtAMalformedLength(t *testing.T) {
	// The walk is a deliberate re-implementation of the production scanner's,
	// so it needs its own bound: a length below eight is not a box, and a
	// walker that trusted it would loop or index past the end.
	data := slices.Concat(SyntheticFMP4Init(), []byte{0, 0, 0, 3, 'x', 'x', 'x', 'x'}, SyntheticFMP4Fragment(0))
	_, _, types := MP4Boxes(data)
	if !slices.Equal(types, []string{"ftyp", "moov"}) {
		t.Fatalf("MP4Boxes walked past a length-3 box and returned %v", types)
	}
}

func TestMP4BoxSizesCoverTheWholeBox(t *testing.T) {
	// The four length bytes must cover the header as well as the payload, or
	// every walk -- the production one included -- lands one header short of
	// the next box and the whole corpus is unusable.
	box := MP4Box("free", make([]byte, 64))
	if len(box) != 72 {
		t.Fatalf("a 64-byte payload produced a %d-byte box, want 72", len(box))
	}
	_, sizes, types := MP4Boxes(box)
	if len(sizes) != 1 || sizes[0] != 72 || types[0] != "free" {
		t.Fatalf("the box walks as sizes=%v types=%v, want one 72-byte free box", sizes, types)
	}
}

func TestSpawnCountIsZeroForALogNothingWrote(t *testing.T) {
	// output_support.py:111's contract: a relay that spawned nothing leaves no
	// file, and the count is zero rather than an error. A helper that returned
	// an error here would make every sharing test carry an irrelevant branch.
	if got := SpawnCount(t.TempDir() + "/never-written.log"); got != 0 {
		t.Fatalf("SpawnCount on a missing file returned %d, want 0", got)
	}
}
