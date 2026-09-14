package ffmpeg

import (
	"errors"
	"syscall"
)

// processGone reports whether pid no longer exists. Signal 0 checks
// existence without delivering anything; a zombie still "exists" until it is
// reaped, which is why callers Wait first.
func processGone(pid int) bool {
	err := syscall.Kill(pid, 0)
	return errors.Is(err, syscall.ESRCH)
}
