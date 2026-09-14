package ffmpeg

import (
	"bytes"
	"errors"
	"os"
	"strconv"
	"syscall"
)

// processGone reports whether pid no longer exists, OR is a zombie nothing
// will ever reap. Signal 0 checks existence without delivering anything; a
// zombie still "exists" until it is reaped, which is why an ordinary caller
// Waits first -- but the test that calls this (spawn_linux_test.go's
// TestAChildOfADeadRelayDiesWithIt) cannot Wait a process it does not own,
// only observe that Pdeathsig did its job. Under GitHub's container: jobs
// (go-tests.yml's build job) the container's PID 1 is a keep-alive process
// with no reaper of its own, so a killed stand-in sits as an unreaped
// zombie past this function's plain existence check, past the test's
// deadline -- not because Pdeathsig failed, but because nothing calls
// wait() on the corpse. isZombieLinux (below) recognizes that shape;
// everywhere else, or if the read fails for any other reason, this falls
// back to the plain existence check.
func processGone(pid int) bool {
	if zombie, ok := isZombieLinux(pid); ok && zombie {
		return true
	}
	err := syscall.Kill(pid, 0)
	return errors.Is(err, syscall.ESRCH)
}

// isZombieLinux reports whether pid is a zombie process, and whether the
// check could be performed at all -- ok is false on darwin (no /proc) and
// whenever the process is already fully gone, both of which fall back to
// processGone's existence check above. /proc/<pid>/stat's fields are "pid
// (comm) state ...": comm is the executable's own basename, which can
// itself contain spaces and closing parens, so the state is parsed from
// the LAST ')' in the line, not the first -- the kernel's own documented
// format (man 5 proc) guarantees at least one trailing " X" state field
// after it.
func isZombieLinux(pid int) (zombie bool, ok bool) {
	raw, err := os.ReadFile("/proc/" + strconv.Itoa(pid) + "/stat")
	if err != nil {
		return false, false
	}
	i := bytes.LastIndexByte(raw, ')')
	if i < 0 || i+2 >= len(raw) {
		return false, false
	}
	return raw[i+2] == 'Z', true
}
