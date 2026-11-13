package relaytest

import (
	"encoding/binary"
	"fmt"
	"io"
	"os"
	"strconv"
	"strings"
	"time"
)

// fdFile is one --fd-file N=PATH: the bytes the stand-in writes to fd N.
type fdFile struct {
	fd   int
	path string
}

// parseFDFile reads "N=PATH". N is 1 (stdout) or 3 and up; fd 0 is the
// relay's input and fd 2 its stderr reader, neither of which an output file
// belongs on.
func parseFDFile(value string) (fdFile, bool) {
	number, path, found := strings.Cut(value, "=")
	if !found || path == "" {
		return fdFile{}, false
	}
	fd, err := strconv.Atoi(number)
	if err != nil || fd == 0 || fd == 2 || fd < 0 {
		return fdFile{}, false
	}
	return fdFile{fd: fd, path: path}, true
}

// FDFileArg is the --fd-file value for fd and path, so a test never spells
// the flag's syntax itself.
func FDFileArg(fd int, path string) string {
	return fmt.Sprintf("%d=%s", fd, path)
}

// runFDFileStandIn is the stand-in as relay/hls sees an encoder or a probe:
// it writes each --fd-file's bytes to its descriptor, in the order given,
// holds every descriptor open, and then ends as it was told to; its exit is
// what closes them.
//
// fd 0 is drained in the background from the start, as a real ffmpeg reads
// its input continuously; a stand-in that did not would block a relay
// writing into a full pipe and make every test a deadlock that looked like a
// slow one (runFMP4StandIn's reason). By default it exits once the files are
// written, which is a process that ENDED on its own: before its first
// segment when the files carry none, after it when they do. --wait-stdin-eof
// holds the exit until fd 0 reaches EOF, which is a generation the relay
// ended by closing its input at a source boundary. --ignore-stdin-eof never
// exits, which is a generation the relay has to kill.
func runFDFileStandIn(o standInOptions) int {
	eof := make(chan struct{})
	go func() {
		defer close(eof)
		_, _ = io.Copy(io.Discard, os.Stdin)
	}()
	if o.fdFragmentInterval > 0 {
		if code := writeFDFilesPaced(o); code != 0 {
			return code
		}
		return holdFDFileStandIn(o, eof)
	}
	for _, f := range o.fdFiles {
		raw, err := os.ReadFile(f.path) // #nosec G304 -- a fixture path the test itself chose
		if err != nil {
			fmt.Fprintf(os.Stderr, "stand-in: reading %s: %v\n", f.path, err) // credential-logging: ok - an *fs.PathError over a test fixture path
			return 2
		}
		out := os.Stdout
		if f.fd != 1 {
			out = os.NewFile(uintptr(f.fd), fmt.Sprintf("fd%d", f.fd))
		}
		if out == nil {
			fmt.Fprintf(os.Stderr, "stand-in: fd %d is not open\n", f.fd)
			return 2
		}
		if _, err := out.Write(raw); err != nil {
			fmt.Fprintf(os.Stderr, "stand-in: writing fd %d: %v\n", f.fd, err) // credential-logging: ok - a pipe write error, no URL anywhere in it
			return 2
		}
		// Not closed: an encoder holds its outputs open until it exits, so
		// a reader's EOF is the process's end, exactly as with ffmpeg.
	}
	return holdFDFileStandIn(o, eof)
}

// holdFDFileStandIn is how the stand-in ends once its files are written.
func holdFDFileStandIn(o standInOptions, eof <-chan struct{}) int {
	switch {
	case o.ignoreStdinEOF:
		// A sleep loop rather than select{}, for RunStandIn's stated reason.
		for {
			time.Sleep(time.Second)
		}
	case o.waitStdinEOF:
		<-eof
	}
	return o.exitCode
}

// writeFDFilesPaced writes every --fd-file at once, each box by box, pausing
// after each mdat: one fragment per interval on every descriptor, as an
// encoder produces them in real time. Written serially and unpaced, a long
// stream reaches the relay as one burst of segments, which outruns the rewind
// writer's bounded queue on a loaded machine.
func writeFDFilesPaced(o standInOptions) int {
	codes := make(chan int, len(o.fdFiles))
	for _, f := range o.fdFiles {
		go func() { codes <- writeFDFilePaced(f, o.fdFragmentInterval) }()
	}
	code := 0
	for range o.fdFiles {
		if c := <-codes; c != 0 {
			code = c
		}
	}
	return code
}

func writeFDFilePaced(f fdFile, interval time.Duration) int {
	raw, err := os.ReadFile(f.path) // #nosec G304 -- a fixture path the test itself chose
	if err != nil {
		fmt.Fprintf(os.Stderr, "stand-in: reading %s: %v\n", f.path, err) // credential-logging: ok - an *fs.PathError over a test fixture path
		return 2
	}
	out := os.Stdout
	if f.fd != 1 {
		out = os.NewFile(uintptr(f.fd), fmt.Sprintf("fd%d", f.fd))
	}
	if out == nil {
		fmt.Fprintf(os.Stderr, "stand-in: fd %d is not open\n", f.fd)
		return 2
	}
	for len(raw) >= 8 {
		size := int(binary.BigEndian.Uint32(raw[:4]))
		if size < 8 || size > len(raw) {
			size = len(raw)
		}
		if _, err := out.Write(raw[:size]); err != nil {
			fmt.Fprintf(os.Stderr, "stand-in: writing fd %d: %v\n", f.fd, err) // credential-logging: ok - a pipe write error, no URL anywhere in it
			return 2
		}
		if string(raw[4:8]) == "mdat" {
			time.Sleep(interval)
		}
		raw = raw[size:]
	}
	return 0
}
