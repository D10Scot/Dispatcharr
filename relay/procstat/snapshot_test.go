package procstat

import (
	"errors"
	"fmt"
	"io/fs"
	"syscall"
	"testing"
)

const hour = 3600

// statLine renders a /proc/<pid>/stat line ParseStat reads back as p.
func statLine(p Proc) string {
	f := make([]any, 0, 22)
	f = append(f, "S", 1, p.PGrp, p.PGrp, 0, -1, 0, 0, 0, 0, 0, p.CPUTicks, 0, 0, 0, 20, 0, 1, 0, p.Start, 0, p.RSSPages)
	s := fmt.Sprintf("%d (ffmpeg)", p.PID)
	for _, v := range f {
		s += fmt.Sprintf(" %v", v)
	}
	return s
}

// statSource is the Linux source's per-pid loop over a scripted /proc: each
// Snapshot reads every listed pid through the next scripted reader.
type statSource struct {
	names []string
	reads []func(name string) ([]byte, error)
	n     int
}

func (s *statSource) Snapshot() ([]Proc, error) {
	read := s.reads[s.n]
	s.n++
	return snapshotFrom(s.names, read)
}
func (*statSource) TicksPerSecond() float64 { return 100 }
func (*statSource) PageSize() int           { return 4096 }

func readsAs(p Proc) func(string) ([]byte, error) {
	return func(string) ([]byte, error) { return []byte(statLine(p) + "\n"), nil }
}

func failsWith(err error) func(string) ([]byte, error) {
	return func(name string) ([]byte, error) {
		return nil, &fs.PathError{Op: "open", Path: "/proc/" + name + "/stat", Err: err}
	}
}

func TestSnapshotSkipsAVanishedProcessAndFailsOnAnyOtherReadError(t *testing.T) {
	p := proc(500, 10, 2, 0)
	if got, err := snapshotFrom([]string{"500", "self", "12x"}, readsAs(p)); err != nil || len(got) != 1 || got[0] != p {
		t.Fatalf("snapshotFrom = %+v, %v; want the one pid read back", got, err)
	}
	// A line that does not parse is skipped beside a good one, and the
	// snapshot stands.
	mixed := func(name string) ([]byte, error) {
		if name == "501" {
			return []byte("501 (ffmpeg) garbage\n"), nil
		}
		return []byte(statLine(p) + "\n"), nil
	}
	if got, err := snapshotFrom([]string{"500", "501"}, mixed); err != nil || len(got) != 1 || got[0] != p {
		t.Errorf("an unparseable line beside a good one: snapshot = %+v, %v; want the good one and the snapshot whole", got, err)
	}
	for _, gone := range []error{fs.ErrNotExist, syscall.ENOENT, syscall.ESRCH} {
		if got, err := snapshotFrom([]string{"500"}, failsWith(gone)); err != nil || len(got) != 0 {
			t.Errorf("a process that exited (%v): snapshot = %+v, %v; want it skipped and the snapshot whole", gone, got, err)
		}
	}
	for _, live := range []error{syscall.EMFILE, syscall.ENFILE, syscall.EACCES, syscall.EIO} {
		if got, err := snapshotFrom([]string{"500"}, failsWith(live)); !errors.Is(err, errUnreadable) {
			t.Errorf("a live process that could not be read (%v): snapshot = %+v, %v; want the snapshot failed, or the process looks absent", live, got, err)
		}
	}
}

// The reviewer's round-4 probe, through the real per-pid loop: one CPU-hour,
// then eight collections in which descriptor exhaustion makes every per-pid
// read fail, then the process read again, unchanged. Each of those eight
// snapshots must fail and age nothing, so the hour is counted once.
func TestEightUnreadableCollectionsDoNotCountAnHourTwice(t *testing.T) {
	p := proc(500, 10, hour, 0)
	reads := []func(string) ([]byte, error){readsAs(p)}
	for range 8 {
		reads = append(reads, failsWith(syscall.EMFILE))
	}
	reads = append(reads, readsAs(p))
	r := NewRegistry(&statSource{names: []string{"500"}, reads: reads})
	r.Track(500, lab)
	for range 9 {
		r.Collect()
	}
	if got := cpu(t, r, lab); got != hour {
		t.Fatalf("figure = %v s, want %v: an unreadable live process aged out and its hour was counted again", got, hour)
	}
}
