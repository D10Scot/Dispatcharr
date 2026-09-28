package hls

import (
	"bytes"
	"errors"
	"io"
	"testing"
	"testing/iotest"
)

// collect runs a splitter over data, read a few bytes at a time so every box
// boundary lands mid-read somewhere, and returns what it handed on.
func collect(t *testing.T, data []byte) (inits, frags [][]byte, err error) {
	t.Helper()
	sp := splitter{
		onInit: func(b []byte) error { inits = append(inits, b); return nil },
		onFrag: func(b []byte) error { frags = append(frags, b); return nil },
	}
	err = sp.read(iotest.OneByteReader(bytes.NewReader(data)))
	return inits, frags, err
}

func TestTheSplitterHandsOnTheInitAtTheMoovAndEachMoofWithItsMdat(t *testing.T) {
	init := videoInit(0)
	f1 := fragSpec{seq: 1, trackID: 1, durations: []uint32{512}, sync: true}.build()
	f2 := fragSpec{seq: 2, trackID: 1, start: 512, durations: []uint32{512}, sync: true}.build()
	stray := box("free", []byte("x"))
	mfra := box("mfra", make([]byte, 8))
	inits, frags, err := collect(t, cat(init, f1, stray, f2, mfra))
	if err != nil {
		t.Fatalf("read: %v", err)
	}
	if len(inits) != 1 || !bytes.Equal(inits[0], init) {
		t.Fatalf("the init handed on is %d bytes, want the %d-byte ftyp+moov", len(inits[0]), len(init))
	}
	if len(frags) != 2 || !bytes.Equal(frags[0], f1) || !bytes.Equal(frags[1], f2) {
		t.Fatalf("got %d fragments, want the two moof+mdat pairs and nothing else", len(frags))
	}
}

// A process that dies mid-fragment leaves a partial box on its pipe: every
// whole fragment before it is handed on, and the partial one is not.
func TestEOFMidFragmentHandsOnOnlyWholeFragments(t *testing.T) {
	f1 := fragSpec{seq: 1, trackID: 1, durations: []uint32{512}, sync: true}.build()
	f2 := fragSpec{seq: 2, trackID: 1, start: 512, durations: []uint32{512}, sync: true}.build()
	_, frags, err := collect(t, cat(videoInit(0), f1, f2[:len(f2)-3]))
	if err != nil {
		t.Fatalf("a clean EOF mid-fragment is not an error: %v", err)
	}
	if len(frags) != 1 || !bytes.Equal(frags[0], f1) {
		t.Fatalf("got %d fragments, want only the whole one", len(frags))
	}
	// A moof whose mdat never arrived is not a fragment either.
	moofOnly := f2[:bytes.Index(f2, []byte("mdat"))-4]
	_, frags, _ = collect(t, cat(videoInit(0), f1, moofOnly))
	if len(frags) != 1 {
		t.Fatalf("a moof with no mdat was handed on")
	}
}

func TestTheSplitterRefusesWhatIsNotFragmentedMP4(t *testing.T) {
	f1 := fragSpec{seq: 1, trackID: 1, durations: []uint32{512}, sync: true}.build()
	if _, _, err := collect(t, cat(box("ftyp", nil), f1)); !errors.Is(err, errNoInit) {
		t.Errorf("a moof before any moov: %v, want errNoInit", err)
	}
	huge := cat(be32(maxBoxBytes+1), []byte("mdat"))
	if _, _, err := collect(t, cat(videoInit(0), huge)); !errors.Is(err, errBox) {
		t.Errorf("a box past the ceiling: %v, want a malformed-box error", err)
	}
	if _, _, err := collect(t, cat(videoInit(0), be32(3), []byte("moof"))); !errors.Is(err, errBox) {
		t.Errorf("a box smaller than its header: %v, want a malformed-box error", err)
	}
	if _, _, err := collect(t, cat(be32(0), []byte("mdat"))); !errors.Is(err, errBox) {
		t.Errorf("a to-the-end box on a pipe: %v, want a malformed-box error", err)
	}
	large := cat(be32(1), []byte("mdat"), be64(1<<62))
	if _, _, err := collect(t, large); !errors.Is(err, errBox) {
		t.Errorf("a 64-bit size past the ceiling: %v, want a malformed-box error", err)
	}
	fine := cat(be32(1), []byte("free"), be64(20), []byte("abcd"), videoInit(0))
	if inits, _, err := collect(t, fine); err != nil || len(inits) != 1 {
		t.Errorf("a 64-bit-sized box before the moov was not skipped: %v", err)
	}
	var tooMuch []byte
	for len(tooMuch) <= maxInitBytes {
		tooMuch = append(tooMuch, box("free", make([]byte, 1<<20))...)
	}
	if _, _, err := collect(t, tooMuch); !errors.Is(err, errBox) {
		t.Errorf("an init that never ends: %v, want a malformed-box error", err)
	}
}

func TestTheSplitterStopsAtItsCallbacksError(t *testing.T) {
	stop := errors.New("stop")
	sp := splitter{onInit: func([]byte) error { return stop }, onFrag: func([]byte) error { return nil }}
	if err := sp.read(bytes.NewReader(videoInit(0))); !errors.Is(err, stop) {
		t.Errorf("an onInit error was not returned: %v", err)
	}
	sp = splitter{onInit: func([]byte) error { return nil }, onFrag: func([]byte) error { return stop }}
	f1 := fragSpec{seq: 1, trackID: 1, durations: []uint32{512}, sync: true}.build()
	if err := sp.read(bytes.NewReader(cat(videoInit(0), f1))); !errors.Is(err, stop) {
		t.Errorf("an onFrag error was not returned: %v", err)
	}
	broken := iotest.ErrReader(io.ErrClosedPipe)
	if err := (&splitter{}).read(broken); !errors.Is(err, io.ErrClosedPipe) {
		t.Errorf("a read error was not returned: %v", err)
	}
}

// The box reader never panics and never reads out of bounds, whatever an
// encoder's pipe holds (spec § Testing: the box reader gets fuzz tests).
func FuzzParseInit(f *testing.F) {
	f.Add(videoInit(860))
	f.Add(audioInit())
	f.Add(initSpec{trackID: 1, handler: "soun", timescale: 48000, entry: audioEntry("ec-3", box("dec3", []byte{1, 2, 3}))}.build())
	f.Fuzz(func(_ *testing.T, data []byte) {
		_, _ = ParseInit(data)
		_, _ = StripEdits(data)
	})
}

func FuzzParseFragment(f *testing.F) {
	f.Add(fragSpec{seq: 1, trackID: 1, start: 99, durations: []uint32{512, 512}, sync: true}.build())
	f.Add(synthFragment(1, 1, 0, []byte{1, 2, 3}, 4, 1024))
	f.Fuzz(func(_ *testing.T, data []byte) {
		track := Track{ID: 1, Timescale: 12800, DefaultDuration: 512}
		if frag, err := ParseFragment(data, track); err == nil {
			_ = shiftStart(&frag, 1)
		}
		_, _, _ = fragmentSamples(data, track)
	})
}

func FuzzSplitter(f *testing.F) {
	f.Add(cat(videoInit(0), fragSpec{seq: 1, trackID: 1, durations: []uint32{512}, sync: true}.build()))
	f.Fuzz(func(_ *testing.T, data []byte) {
		sp := splitter{onInit: func([]byte) error { return nil }, onFrag: func([]byte) error { return nil }}
		_ = sp.read(bytes.NewReader(data))
	})
}
