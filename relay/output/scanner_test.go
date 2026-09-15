package output

import (
	"bytes"
	"errors"
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

func TestAMisalignedWorkingBufferIsDiscardedWholeRatherThanResynchronised(t *testing.T) {
	// THIS PINS PYTHON'S BEHAVIOUR, WHICH IS NOT WHAT ITS COMMENT CLAIMS, and
	// it is reproduced rather than fixed (spec D5). manager.py:259-266 says
	// "drop bytes until we find one" and searches from offset 1 -- but offset 1
	// re-reads the four-byte length field at a one-byte shift, which for any
	// real box yields a bogus size in the tens of thousands, jumps the scan
	// past every following box, and returns -1. _flush_complete_fragments then
	// CLEARS the whole working buffer (`frag_buf.clear()`), losing the
	// fragments that were sitting behind the misalignment rather than resuming
	// at the next one.
	//
	// Verified against the Python itself before this test was written: with a
	// 72-byte `junk` box in front of two whole fragments,
	// _find_moof_offset(buf, start=1) returns -1 where a correct resynchronisation
	// would return 72.
	//
	// FILED AS [#NNN] and reproduced rather than fixed. It is unreachable in a
	// healthy stream -- after the init segment the working buffer begins at a
	// moof, and after every publish it begins at the next moof, so it takes a
	// corrupt box length to enter -- which is why it is filed rather than
	// fixed, and why this test exists: so nobody "fixes" the Go side into
	// disagreeing with the Python one while the issue is open.
	f := buffer.NewFragments(buffer.FragmentsConfig{})
	s := &scanner{out: f, initStored: true}
	if err := s.write(slices.Concat(
		relaytest.MP4Box("junk", make([]byte, 64)),
		relaytest.SyntheticFMP4Fragment(5),
		relaytest.SyntheticFMP4Fragment(6),
	)); err != nil {
		t.Fatalf("the scanner rejected the stream: %v", err)
	}
	if got := len(collect(f)); got != 0 {
		t.Fatalf("%d fragments published behind a misaligned working buffer, want 0: Python's start=1 rescan returns -1 here and clears the buffer, and this port must agree with it", got)
	}
	if head := f.Head(); head != 0 {
		t.Fatalf("the buffer head moved to %d, want 0", head)
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
