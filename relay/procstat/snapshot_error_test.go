package procstat

import (
	"errors"
	"testing"
)

// A failed snapshot marks every sample's RSS as unknown, so the gauge has no
// point rather than a false zero; a later good snapshot makes it known again.
// The CPU accumulator is unaffected (TestAFailedSnapshotKeepsTheAccumulator).
func TestAFailedSnapshotMarksRSSUnknown(t *testing.T) {
	src := &scripted{snaps: [][]Proc{
		{proc(500, 10, 1, 10)},
		{proc(500, 10, 1, 12)},
	}}
	r := NewRegistry(src)
	r.Track(500, lab)

	if s := r.Collect()[0]; !s.RSSKnown || s.RSSBytes != 10*4096 {
		t.Fatalf("first collection = %+v, want RSSKnown with %d bytes", s, 10*4096)
	}
	src.err = errors.New("proc unreadable")
	if s := r.Collect()[0]; s.RSSKnown {
		t.Fatalf("collection after a failed snapshot = %+v, want RSSKnown false", s)
	}
	src.err = nil
	if s := r.Collect()[0]; !s.RSSKnown || s.RSSBytes != 12*4096 {
		t.Fatalf("collection after recovery = %+v, want RSSKnown with %d bytes", s, 12*4096)
	}
}

// The error hook sees each failed snapshot's error and nothing else, and is
// called outside the lock: a hook that calls back into the registry must not
// deadlock.
func TestTheErrorHookSeesEachFailedSnapshot(t *testing.T) {
	src := &scripted{snaps: [][]Proc{{proc(500, 10, 1, 1)}}}
	r := NewRegistry(src)
	r.Track(500, lab)

	var got []error
	r.SetErrorHook(func(err error) {
		got = append(got, err)
		_ = r.Groups() // takes the lock: deadlocks if the hook runs under it
	})
	r.Collect()
	if len(got) != 0 {
		t.Fatalf("hook called %d times on a good snapshot", len(got))
	}
	boom := errors.New("proc unreadable")
	src.err = boom
	r.Collect()
	r.Collect()
	if len(got) != 2 || !errors.Is(got[0], boom) || !errors.Is(got[1], boom) {
		t.Fatalf("hook saw %v, want the snapshot error twice", got)
	}
}
