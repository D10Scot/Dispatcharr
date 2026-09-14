//go:build linux

package ffmpeg

import "syscall"

// sysProcAttr is the Linux half of spec D5's first exception: a process
// group of its own, so Kill reaches everything the child forked, and
// SIGKILL on parent death, so an ffmpeg blocked on a stalled upstream cannot
// outlive the relay and hold a provider slot (CLAUDE.md, § Operationally,
// the defect Python's os.posix_spawn without PDEATHSIG leaves open).
//
// Pdeathsig is delivered when the THREAD that forked the child exits, not
// the process (prctl(2)). Go's runtime never exits an OS thread except when
// a goroutine that called runtime.LockOSThread returns while still locked,
// and nothing in this module locks a thread, so the forking thread lives as
// long as the process does. Stated because it is the one way this could
// fire early, and it is guarded by convention rather than by code.
func sysProcAttr() *syscall.SysProcAttr {
	return &syscall.SysProcAttr{Setpgid: true, Pdeathsig: syscall.SIGKILL}
}
