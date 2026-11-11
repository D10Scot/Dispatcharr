package procstat

import (
	"errors"
	"io/fs"
	"strconv"
	"strings"
	"syscall"
)

// errUnreadable fails a snapshot in which a process that still exists could
// not be read.
var errUnreadable = errors.New("procstat: a process's stat could not be read")

// snapshotFrom builds one snapshot from the entries of /proc and a reader of
// /proc/<pid>/stat. Entries that are not a pid are ignored.
//
// A pid whose stat file is gone (the process exited between the listing and
// the read) is skipped. Any other read failure fails the whole snapshot,
// because a failed snapshot ages nothing in the Registry: a live process that
// only could not be read (descriptor exhaustion, say) must never look absent,
// or enough of those in a row would forget it and count its CPU again from
// zero. A stat line that does not parse is skipped; an identity that never
// parsed was never counted, so skipping it cannot count anything twice.
func snapshotFrom(names []string, read func(name string) ([]byte, error)) ([]Proc, error) {
	out := make([]Proc, 0, len(names))
	for _, name := range names {
		if name == "" || name[0] < '0' || name[0] > '9' {
			continue
		}
		if _, err := strconv.Atoi(name); err != nil {
			continue
		}
		raw, err := read(name)
		if err != nil {
			if vanished(err) {
				continue
			}
			return nil, errUnreadable
		}
		p, err := ParseStat(strings.TrimSpace(string(raw)))
		if err != nil {
			continue
		}
		out = append(out, p)
	}
	return out, nil
}

// vanished reports whether err from reading /proc/<pid>/stat means the
// process no longer exists.
func vanished(err error) bool {
	return errors.Is(err, fs.ErrNotExist) || errors.Is(err, syscall.ESRCH)
}
