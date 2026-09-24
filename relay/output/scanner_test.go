package output

import (
	"bytes"
	"encoding/binary"
	"errors"
	"fmt"
	"slices"
	"testing"

	"github.com/D10Scot/Dispatcharr/relay/buffer"
	"github.com/D10Scot/Dispatcharr/relay/internal/relaytest"
)

// collect drains everything a fragment buffer holds, as whole fragments.
func collect(f *buffer.Fragments) [][]byte {
	out, _, _ := f.Read(0)
	return out
}

// feed pushes data through a fresh scanner in `step`-byte writes, so a test can
// drive the same bytes as one read and as many.
func feed(t *testing.T, data []byte, step int) *buffer.Fragments {
	t.Helper()
	f := buffer.NewFragments(buffer.FragmentsConfig{})
	s := &scanner{out: f}
	for offset := 0; offset < len(data); offset += step {
		end := min(offset+step, len(data))
		if err := s.write(data[offset:end]); err != nil {
			t.Fatalf("the scanner rejected bytes %d..%d: %v", offset, end, err)
		}
	}
	return f
}

// THE ARGV IS A PYTHON LITERAL AND THIS IS ITS PIN (Global Constraint 8). The
// expected value is output/fmp4/manager.py:32-45 and :46-57 read off, token for
// token, not anything this package computes -- so a reordered flag, a dropped
// `-map 0` or a changed movflags value fails here.
func TestTheRemuxArgvMatchesFFmpegRemuxCmd(t *testing.T) {
	// FFMPEG_REMUX_CMD (manager.py:32-45), with the command split off the
	// front the way ffmpeg.Start takes it.
	wantWithBSF := []string{
		"-loglevel", "error",
		"-f", "mpegts",
		"-i", "pipe:0",
		"-c", "copy",
		"-map", "0",
		"-bsf:a", "aac_adtstoasc",
		"-use_editlist", "0",
		"-flush_packets", "1",
		"-f", "mp4",
		"-movflags", "frag_keyframe+delay_moov+default_base_moof",
		"pipe:1",
	}
	// FFMPEG_REMUX_CMD_NO_BSF (manager.py:46-57). It drops `-map 0` as well as
	// the filter, which is easy to miss and is reproduced rather than tidied.
	wantNoBSF := []string{
		"-loglevel", "error",
		"-f", "mpegts",
		"-i", "pipe:0",
		"-c", "copy",
		"-use_editlist", "0",
		"-flush_packets", "1",
		"-f", "mp4",
		"-movflags", "frag_keyframe+delay_moov+default_base_moof",
		"pipe:1",
	}
	if RemuxCommand != "ffmpeg" {
		t.Fatalf("RemuxCommand is %q, want FFMPEG_REMUX_CMD[0]", RemuxCommand)
	}
	if !slices.Equal(RemuxArgv(), wantWithBSF) {
		t.Fatalf("RemuxArgv() is\n  %q\nwant FFMPEG_REMUX_CMD[1:]\n  %q", RemuxArgv(), wantWithBSF)
	}
	if !slices.Equal(RemuxArgvNoBSF(), wantNoBSF) {
		t.Fatalf("RemuxArgvNoBSF() is\n  %q\nwant FFMPEG_REMUX_CMD_NO_BSF[1:]\n  %q", RemuxArgvNoBSF(), wantNoBSF)
	}
	if slices.Contains(RemuxArgvNoBSF(), "aac_adtstoasc") {
		t.Fatal("the no-BSF argv still carries aac_adtstoasc: the retry would fail the same way and a non-AAC channel would never play")
	}
}

func TestTheInitSegmentIsEverythingBeforeTheFirstMoof(t *testing.T) {
	init := relaytest.SyntheticFMP4Init()
	stream := slices.Concat(init, relaytest.SyntheticFMP4Fragment(0), relaytest.SyntheticFMP4Fragment(1))

	f := feed(t, stream, len(stream))
	if got := f.Init(); !bytes.Equal(got, init) {
		t.Fatalf("the init segment is %d bytes, want the %d before the first moof (ftyp + moov)", len(got), len(init))
	}
	if problem := relaytest.FMP4ShapeProblem(f.Init()); problem == "" {
		// The init segment alone is NOT a playable shape -- it has no moof --
		// so FMP4ShapeProblem must complain about it. Asserted so the shape
		// helper cannot be silently satisfied by anything.
		t.Fatal("FMP4ShapeProblem accepted an init segment with no fragment in it, so it cannot be distinguishing a fragment from a header")
	}
}

func TestAFragmentEndsWhereTheNextMoofBeginsAndTheLastIsHeldBack(t *testing.T) {
	// manager.py:276-279: a fragment's end is the NEXT moof, so the newest one
	// is always incomplete until its successor arrives. Three fragments in
	// therefore means two out.
	stream := slices.Concat(
		relaytest.SyntheticFMP4Init(),
		relaytest.SyntheticFMP4Fragment(0),
		relaytest.SyntheticFMP4Fragment(1),
		relaytest.SyntheticFMP4Fragment(2),
	)
	f := feed(t, stream, len(stream))

	got := collect(f)
	if len(got) != 2 {
		t.Fatalf("%d fragments were published from a stream carrying three, want 2: the newest has no successor to bound it", len(got))
	}
	for i, fragment := range got {
		if index := relaytest.FMP4FragmentIndex(fragment); index != i {
			t.Fatalf("published fragment %d carries embedded index %d, want %d: the boundaries are in the wrong place", i, index, i)
		}
		if !bytes.Equal(fragment, relaytest.SyntheticFMP4Fragment(i)) {
			t.Fatalf("published fragment %d is %d bytes, want the %d it was written as: a fragment must be carried whole",
				i, len(fragment), len(relaytest.SyntheticFMP4Fragment(i)))
		}
	}
}

func TestTheFinalFragmentIsPublishedWhenTheRemuxEnds(t *testing.T) {
	// manager.py:346-348's `finally`: without it the last fragment of every
	// ended stream is dropped, which for a short recording is a visible
	// truncation.
	stream := slices.Concat(
		relaytest.SyntheticFMP4Init(),
		relaytest.SyntheticFMP4Fragment(0),
		relaytest.SyntheticFMP4Fragment(1),
	)
	f := buffer.NewFragments(buffer.FragmentsConfig{})
	s := &scanner{out: f}
	if err := s.write(stream); err != nil {
		t.Fatalf("the scanner rejected the stream: %v", err)
	}
	if got := len(collect(f)); got != 1 {
		t.Fatalf("%d fragments before the end, want 1", got)
	}
	s.final()
	got := collect(f)
	if len(got) != 2 {
		t.Fatalf("%d fragments after the end, want 2: the last one has no successor and is published only by final()", len(got))
	}
	if index := relaytest.FMP4FragmentIndex(got[1]); index != 1 {
		t.Fatalf("the last published fragment carries index %d, want 1", index)
	}
}

func TestABoxBetweenTwoFragmentsIsCarriedInsideThePrecedingOne(t *testing.T) {
	// A fragment's bounds run from its own moof to the NEXT one
	// (manager.py:276-282), so anything the remux emits between two fragments
	// -- an `sidx`, a `free`, an `styp` -- travels inside the earlier fragment
	// and reaches the player. Not a special case in either implementation, and
	// asserted because it is the shape a reader might expect the
	// resynchronisation arm to handle instead.
	junk := relaytest.MP4Box("junk", make([]byte, 64))
	stream := slices.Concat(
		relaytest.SyntheticFMP4Init(),
		relaytest.SyntheticFMP4Fragment(0),
		junk,
		relaytest.SyntheticFMP4Fragment(1),
		relaytest.SyntheticFMP4Fragment(2),
	)
	f := feed(t, stream, len(stream))

	got := collect(f)
	if len(got) != 2 {
		t.Fatalf("%d fragments published, want 2 (0 and 1, with 2 held back)", len(got))
	}
	// Fragment 0's own bounds run to the NEXT moof, which is past the junk, so
	// the junk is carried inside fragment 0 exactly as Python carries it --
	// the resynchronisation arm only fires for junk at the START of the
	// working buffer.
	if index := relaytest.FMP4FragmentIndex(got[1]); index != 1 {
		t.Fatalf("the second published fragment carries index %d, want 1: the scanner lost its place across the junk box", index)
	}
}

func TestAMisalignedWorkingBufferResynchronisesAtTheNextMoof(t *testing.T) {
	// ISSUE #306, FIXED. manager.py:259-266 said "drop bytes until we find
	// one" and searched from offset 1 with the box-striding scanner -- but
	// offset 1 re-reads a four-byte length at a one-byte shift, which for any
	// real box is a bogus size in the tens of thousands, so the scan jumped
	// past every following box, returned -1, and the WHOLE working buffer was
	// cleared, fragments and all. The resync arm now looks for the next moof
	// header itself, so the fragments behind the misalignment are kept: 5 is
	// published (6 bounds it) and 6 is held back as every newest fragment is.
	f := buffer.NewFragments(buffer.FragmentsConfig{})
	s := &scanner{out: f, initStored: true}
	if err := s.write(slices.Concat(
		relaytest.MP4Box("junk", make([]byte, 64)),
		relaytest.SyntheticFMP4Fragment(5),
		relaytest.SyntheticFMP4Fragment(6),
	)); err != nil {
		t.Fatalf("the scanner rejected the stream: %v", err)
	}
	got := collect(f)
	if len(got) != 1 {
		t.Fatalf("%d fragments published behind a misaligned working buffer, want 1 (fragment 5; 6 is held back): the resync discarded them (#306)", len(got))
	}
	if index := relaytest.FMP4FragmentIndex(got[0]); index != 5 {
		t.Fatalf("the published fragment carries index %d, want 5", index)
	}
}

func TestAGarbageRunThatReadsAsALargeLengthDoesNotHideTheNextMoof(t *testing.T) {
	// ISSUE #119's shrunk counterexample, both at the finder and through the
	// scanner. One garbage byte before a moof: the striding scan read
	// 0x01000000 as a length at offset 0 and jumped clear past it. The
	// issue's own moof is EMPTY (8 bytes), which minMoofBox now refuses as a
	// resync point on purpose, so the finder is asserted on a real 16-byte one
	// and the empty box is kept in the rejection test below. Two garbage
	// bytes through the scanner: the resync arm starts at offset 1, reads
	// 0x01000000 there, and did the same.
	if at := resyncOffset(slices.Concat([]byte{0x01}, relaytest.SyntheticFMP4Fragment(0)), 0); at != 1 {
		t.Fatalf("resyncOffset found the moof at %d, want 1 (#119)", at)
	}
	f := buffer.NewFragments(buffer.FragmentsConfig{})
	s := &scanner{out: f, initStored: true}
	if err := s.write(slices.Concat([]byte{0x01, 0x01}, relaytest.SyntheticFMP4Fragment(0), relaytest.SyntheticFMP4Fragment(1))); err != nil {
		t.Fatalf("the scanner rejected the stream: %v", err)
	}
	if got := collect(f); len(got) != 1 || relaytest.FMP4FragmentIndex(got[0]) != 0 {
		t.Fatalf("published %d fragments after two garbage bytes, want fragment 0 alone (#119)", len(got))
	}
}

func TestAMoofHeaderSplitAcrossReadsSurvivesAResync(t *testing.T) {
	// The tail a resync with nothing to find must keep. A megabyte of garbage
	// arrives with the first six bytes of fragment 0's header at its end, and
	// the rest of the stream in the next read. Clearing the buffer -- what
	// the -1 did -- loses those six bytes, and fragment 0 with them; keeping
	// everything would hold the megabyte. resyncTail keeps seven.
	fragment := relaytest.SyntheticFMP4Fragment(0)
	f := buffer.NewFragments(buffer.FragmentsConfig{})
	s := &scanner{out: f, initStored: true}
	garbage := bytes.Repeat([]byte{0x01}, 1<<20)
	if err := s.write(slices.Concat(garbage, fragment[:6])); err != nil {
		t.Fatalf("the scanner rejected the stream: %v", err)
	}
	if held := len(s.frag); held > resyncTail {
		t.Fatalf("the working buffer holds %d bytes after a megabyte with no moof, want at most %d", held, resyncTail)
	}
	if err := s.write(slices.Concat(fragment[6:], relaytest.SyntheticFMP4Fragment(1))); err != nil {
		t.Fatalf("the scanner rejected the stream: %v", err)
	}
	if got := collect(f); len(got) != 1 || relaytest.FMP4FragmentIndex(got[0]) != 0 {
		t.Fatalf("published %d fragments, want fragment 0: its header straddled the read and was discarded", len(got))
	}
}

func TestAMoofLiteralWithAnImplausibleLengthIsNotAResyncPoint(t *testing.T) {
	// A "moof" inside a payload reads a garbage length. Too long, and the
	// aligned path would wait for 4 GiB of it; too short -- #119's own empty
	// box among them -- and it is not a moof at all (minMoofBox). Each is
	// skipped for the real moof after it.
	for name, bogus := range map[string][]byte{
		"longer than any moof":       {0xFF, 0xFF, 0xFF, 0xFF, 'm', 'o', 'o', 'f'},
		"#119's empty moof, 8 bytes": relaytest.MP4Box("moof", nil),
		"shorter than an mfhd needs": relaytest.MP4Box("moof", make([]byte, 4)),
	} {
		data := slices.Concat([]byte{0x00}, bogus, relaytest.SyntheticFMP4Fragment(0))
		if at, want := resyncOffset(data, 1), 1+len(bogus); at != want {
			t.Fatalf("%s: resyncOffset chose %d, want the real moof at %d", name, at, want)
		}
		// And with nothing after it, a refused candidate leaves no resync
		// point at all, rather than being taken for want of a better one.
		if at := resyncOffset(slices.Concat([]byte{0x00}, bogus), 1); at != -1 {
			t.Fatalf("%s: resyncOffset chose %d with no real moof in the buffer, want -1", name, at)
		}
	}
}

func TestAMoofShorterThanARealOneDoesNotStallTheBuffer(t *testing.T) {
	// Adopted from #348's A-4. A buffer ALIGNED on a "moof" whose length is
	// below a real moof's 16 bytes (its own header plus an mfhd) is not on a
	// fragment. The seed returned without consuming anything for a length
	// below 8 (fmp4.go:229-231), so every later write grew the buffer and
	// nothing was ever published again; a length from 8 to 15 was trusted and
	// published as a bogus fragment of its own. Either way fragment 0, whole
	// and right behind it, must be what comes out.
	for _, size := range []uint32{4, 12} {
		t.Run(fmt.Sprintf("length %d", size), func(t *testing.T) {
			short := make([]byte, max(size, 8))
			binary.BigEndian.PutUint32(short[0:4], size)
			copy(short[4:8], "moof")
			f := buffer.NewFragments(buffer.FragmentsConfig{})
			s := &scanner{out: f, initStored: true}
			if err := s.write(slices.Concat(short, relaytest.SyntheticFMP4Fragment(0), relaytest.SyntheticFMP4Fragment(1))); err != nil {
				t.Fatalf("the scanner rejected the stream: %v", err)
			}
			got := collect(f)
			if len(got) != 1 || relaytest.FMP4FragmentIndex(got[0]) != 0 {
				t.Fatalf("published %d fragments behind a %d-byte moof, want fragment 0 alone", len(got), size)
			}
		})
	}
}

func TestAFragmentThatNeverEndsIsAbandonedAtTheCeiling(t *testing.T) {
	// Adopted from #348's A-4, both shapes of it. An aligned moof whose own
	// length is corrupt waits for bytes that never come (fmp4.go:233-236); a
	// valid moof followed by a box whose length is corrupt makes the search
	// for the NEXT moof return -1 on every pass (:238-240). Either way the
	// seed held the working buffer open toward a length of up to 4 GiB. Past
	// the ceiling the scanner gives the fragment up and resynchronises, so
	// the buffer stays bounded and the next real fragment is published. The
	// ceiling is lowered on this scanner alone rather than fed 64 MiB.
	//
	// The first shape declares 500000, not an internet-scale value: review
	// round 1's nit on #399 made flush refuse an ALIGNED moof above
	// maxMoofBoxBytes outright (resynchronising past it at once, pinned by
	// TestAnAlignedMoofClaimingMoreThanAnyRealOneCanIsResynchronisedPastAtOnce),
	// so a declared length past that bound no longer reaches this arm at
	// all. 500000 stays under maxMoofBoxBytes (so it is still "aligned" and
	// still waited on) while staying far past both a real moof's few
	// kilobytes and this test's own 4096-byte ceiling, so the wait still
	// never resolves and still gets abandoned at the ceiling.
	const ceiling = 4096
	corruptMoofLength := make([]byte, 4)
	binary.BigEndian.PutUint32(corruptMoofLength, 500000)
	shapes := map[string][]byte{
		"the moof's own length is corrupt": slices.Concat(
			corruptMoofLength, []byte("moof"), make([]byte, 8)),
		"the box after the moof is corrupt": slices.Concat(
			relaytest.MP4Box("moof", make([]byte, 8)), []byte{0xff, 0xff, 0xff, 0x00}, []byte("mdat")),
	}
	for name, corrupt := range shapes {
		t.Run(name, func(t *testing.T) {
			f := buffer.NewFragments(buffer.FragmentsConfig{})
			s := &scanner{out: f, initStored: true, ceiling: ceiling}
			writes := [][]byte{corrupt}
			for range 8 {
				writes = append(writes, bytes.Repeat([]byte{0x01}, 1024))
			}
			for i, w := range writes {
				if err := s.write(w); err != nil {
					t.Fatalf("the scanner rejected write %d: %v", i, err)
				}
				if held := len(s.frag); held > ceiling {
					t.Fatalf("the working buffer holds %d bytes after write %d, past the %d-byte ceiling", held, i, ceiling)
				}
			}
			if err := s.write(slices.Concat(relaytest.SyntheticFMP4Fragment(0), relaytest.SyntheticFMP4Fragment(1))); err != nil {
				t.Fatalf("the scanner rejected the stream: %v", err)
			}
			if got := collect(f); len(got) != 1 || relaytest.FMP4FragmentIndex(got[0]) != 0 {
				t.Fatalf("published %d fragments after the ceiling, want fragment 0 alone", len(got))
			}
		})
	}
}

func TestABoxLengthBelowEightAdvancesOneByteRatherThanGivingUp(t *testing.T) {
	// manager.py:84-86's `if box_size < 8: offset += 1`. A search that gave up
	// instead would never find the moof that follows, and a stream that
	// desynchronised would stall silently rather than resynchronising.
	//
	// EIGHT ZERO BYTES, chosen so every one-byte step reads a length of zero
	// and steps again, and the eighth lands exactly on the moof box's own
	// header. A prefix whose shifted reads happen to yield a LARGE length
	// instead makes the scan jump past the moof and return -1 -- verified
	// against the Python itself, which answers 8 for this fixture and -1 for
	// a `size 3 + xxxx` one -- so the fixture is what makes this an assertion
	// about the one-byte advance rather than about which junk was chosen.
	corrupt := make([]byte, 8)
	data := slices.Concat(corrupt, relaytest.SyntheticFMP4Fragment(0))
	if at := findMoofOffset(data, 0); at != len(corrupt) {
		t.Fatalf("findMoofOffset found the moof at %d, want %d: a length below eight must advance one byte, not abandon the scan", at, len(corrupt))
	}
}

func TestABoxLongerThanWhatHasArrivedIsNotAFragmentYet(t *testing.T) {
	// manager.py:277-279: _find_moof_offset(frag_buf, start=moof_size) with a
	// start past the end returns -1, and the fragment waits for more bytes. A
	// scanner that treated it as complete would publish a truncated fragment.
	partial := relaytest.SyntheticFMP4Fragment(0)
	f := feed(t, slices.Concat(relaytest.SyntheticFMP4Init(), partial[:len(partial)/2]), 4096)
	if got := len(collect(f)); got != 0 {
		t.Fatalf("%d fragments published from half a fragment, want 0", got)
	}
}

func TestTheSameBytesSplitAcrossReadsProduceTheSameFragments(t *testing.T) {
	// fd 1 hands the reader arbitrary boundaries: a fragment, its init segment
	// and a box header can all straddle two reads. One byte at a time is the
	// worst case, and it must produce exactly what one read produces.
	stream := slices.Concat(
		relaytest.SyntheticFMP4Init(),
		relaytest.SyntheticFMP4Fragment(0),
		relaytest.SyntheticFMP4Fragment(1),
		relaytest.SyntheticFMP4Fragment(2),
	)
	whole := feed(t, stream, len(stream))
	byOne := feed(t, stream, 1)
	byOdd := feed(t, stream, 997)

	if !bytes.Equal(whole.Init(), byOne.Init()) || !bytes.Equal(whole.Init(), byOdd.Init()) {
		t.Fatalf("the init segment differs by read size: %d whole, %d by one, %d by 997",
			len(whole.Init()), len(byOne.Init()), len(byOdd.Init()))
	}
	for name, f := range map[string]*buffer.Fragments{"one byte at a time": byOne, "997 bytes at a time": byOdd} {
		got, want := collect(f), collect(whole)
		if len(got) != len(want) {
			t.Fatalf("%s produced %d fragments, want the %d one read produces", name, len(got), len(want))
		}
		for i := range want {
			if !bytes.Equal(got[i], want[i]) {
				t.Fatalf("%s produced a different fragment %d (%d bytes vs %d)", name, i, len(got[i]), len(want[i]))
			}
		}
	}
}

func TestAResyncTailIsNotPublishedWhenTheRemuxEnds(t *testing.T) {
	// Review round 1's should-fix on #399. When the remux's fd 1 ends while
	// the working buffer is misaligned, the only thing left in s.frag can be
	// the up-to-resyncTail-byte remnant a resync-with-nothing-found kept.
	// final() published it as though it were a whole fragment -- junk at the
	// end of every fMP4 viewer's stream, since the writer defers final() at
	// the fd 1 close. final() must publish only a buffer aligned on a real
	// moof, the same idiom flush already uses to recognise one.
	f := buffer.NewFragments(buffer.FragmentsConfig{})
	s := &scanner{out: f, initStored: true}
	if err := s.write(bytes.Repeat([]byte{0x01}, 100)); err != nil {
		t.Fatalf("the scanner rejected the stream: %v", err)
	}
	if held := len(s.frag); held == 0 || held > resyncTail {
		t.Fatalf("the working buffer holds %d bytes after 100 bytes of garbage, want 1..%d to exercise the guard", held, resyncTail)
	}
	s.final()
	if got := len(collect(f)); got != 0 {
		t.Fatalf("%d fragments published from the resync tail when the remux ended, want 0: it is not a moof and must not be published as one", got)
	}
}

func TestAnAlignedMoofClaimingMoreThanAnyRealOneCanIsResynchronisedPastAtOnce(t *testing.T) {
	// Review round 1's nit on #399. resyncOffset already refuses a candidate
	// above maxMoofBoxBytes; the aligned path did not, so an aligned "moof"
	// whose own corrupt length exceeds it waited toward the 64 MiB ceiling
	// even though no real moof runs anywhere near that large. Treating it as
	// misaligned instead resynchronises past it immediately.
	bogus := make([]byte, 8)
	binary.BigEndian.PutUint32(bogus[0:4], 2<<20) // 2 MiB: > maxMoofBoxBytes
	copy(bogus[4:8], "moof")
	f := buffer.NewFragments(buffer.FragmentsConfig{})
	s := &scanner{out: f, initStored: true}
	if err := s.write(slices.Concat(bogus, relaytest.SyntheticFMP4Fragment(0), relaytest.SyntheticFMP4Fragment(1))); err != nil {
		t.Fatalf("the scanner rejected the stream: %v", err)
	}
	if got := collect(f); len(got) != 1 || relaytest.FMP4FragmentIndex(got[0]) != 0 {
		t.Fatalf("published %d fragments behind an aligned moof claiming 2 MiB, want fragment 0 alone at once, not after waiting toward the ceiling", len(got))
	}
}

func TestTenMegabytesWithNoMoofAborts(t *testing.T) {
	// manager.py:334-339: a child that is not producing fragmented MP4 must not
	// be buffered forever. The abort is what ends the pipeline and closes the
	// buffer, which is what ends a client's wait.
	f := buffer.NewFragments(buffer.FragmentsConfig{})
	s := &scanner{out: f}
	filler := relaytest.MP4Box("free", make([]byte, 1<<20))
	var err error
	for range 12 {
		if err = s.write(filler); err != nil {
			break
		}
	}
	if err == nil {
		t.Fatalf("the scanner accepted %d MB with no moof in it, want ErrNoInitSegment past %d bytes", 12, MaxInitSegmentBytes)
	}
	if !errors.Is(err, ErrNoInitSegment) {
		t.Fatalf("the scanner returned %v, want ErrNoInitSegment", err)
	}
}
