//go:build !linux

package ffmpeg

import "syscall"

// sysProcAttr on a non-Linux host: the process group only. There is no
// Pdeathsig field in syscall.SysProcAttr here -- the relay is built for
// Linux (docker/Dockerfile's relay-builder stage) and only tested elsewhere
// -- so the parent-death half of D5's exception is a Linux-only property,
// pinned by spawn_linux_test.go and honestly absent on a darwin developer
// host rather than emulated.
func sysProcAttr() *syscall.SysProcAttr {
	return &syscall.SysProcAttr{Setpgid: true}
}
