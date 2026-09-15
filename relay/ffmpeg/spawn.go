package ffmpeg

import (
	"bytes"
	"context"
	"errors"
	"fmt"
	"io"
	"os"
	"os/exec"
	"strings"
	"sync"
	"syscall"
	"time"
)

// Process is one running transcode subprocess: ffmpeg, VLC or streamlink,
// spawned from a Stream Profile's command and argv.
//
// THE OBSERVABLE CONTRACT IS input/manager.py:823-923's, fd for fd. stdin is
// /dev/null (POSIX_SPAWN_OPEN of /dev/null onto fd 0 there; os/exec's
// default for a nil Stdin here). stdout, fd 1, is the pipe the relay reads
// video from -- the profile's `pipe:1` -- and Stdout below is its read end.
// stderr, fd 2, is a pipe a reader drains line by line (ReadStderr), the
// port of the stderr reader thread. The environment is the relay's own,
// exactly as os.environ is passed there. The executable is resolved on PATH
// (shutil.which there, exec.LookPath here).
//
// WHAT DIFFERS IS D5's FIRST NAMED EXCEPTION. Python spawns with
// os.posix_spawn -- chosen because fork() hangs in gevent's _before_fork
// atfork handler, a reason that does not exist in Go and is not cargo-culted
// here -- with no setsid and no PDEATHSIG, so an ffmpeg blocked on a stalled
// upstream survives its worker and holds a provider slot (CLAUDE.md,
// § Operationally). This process is started in its own process group
// (Setpgid) so a kill reaches everything it forked, and on Linux with
// Pdeathsig SIGKILL so it dies with the relay. sysProcAttr in spawn_linux.go
// and spawn_other.go carries the per-OS half: syscall.SysProcAttr has no
// Pdeathsig field on darwin, and the relay is built for Linux only
// (docker/Dockerfile's relay-builder stage) but tested on both.
//
// KILL SEMANTICS MATCH PYTHON'S. _close_socket (input/manager.py:1737-1749)
// sends SIGKILL, never SIGTERM, and waits half a second. Cancel below sends
// SIGKILL to the whole process group and Wait gives the process WaitDelay to
// go, which is that same half second.
type Process struct {
	cmd    *exec.Cmd
	stdout io.ReadCloser
	stderr io.ReadCloser
	// stdin is non-nil only for a process started by StartPiped: the
	// output-side remux, whose fd 0 is the relay's own ring rather than
	// /dev/null (output/fmp4/manager.py:36's `-i pipe:0`).
	stdin     io.WriteCloser
	closeOnce sync.Once
	cancel    context.CancelFunc
	// ended is closed by Wait once the process has been reaped.
	ended chan struct{}
	err   error
}

// KillWait is how long a killed process is given to be reaped before Wait
// stops waiting for its pipes: input/manager.py:1746's wait(timeout=0.5).
const KillWait = 500 * time.Millisecond

// ErrCommandIsAURL refuses a Stream Profile whose command carries a scheme.
// A command is an executable name; one that is a URL would put a provider
// credential into every os/exec error message (exec.Error prints the NAME),
// which is the one shape redact.Error is not built to strip. Python would
// try to spawn it and fail; this fails earlier and says why.
var ErrCommandIsAURL = errors.New("ffmpeg: a stream profile's command must be an executable, not a URL")

// ErrExited is a process that ended on its own with a non-zero status.
//
// Code is Python's returncode (input/manager.py:867-873): the exit status
// when the process exited, and MINUS the signal number when it was killed by
// one, so a SIGKILLed process reports -9. Python reads the code only to log
// it -- every end of the stdout pipe is "Server closed connection"
// (:1868-1872) whatever the status -- and the source that owns this process
// decides what to do with a non-zero one.
type ErrExited struct{ Code int }

func (e *ErrExited) Error() string {
	if e.Code < 0 {
		return fmt.Sprintf("ffmpeg: the process was killed by signal %d", -e.Code)
	}
	return fmt.Sprintf("ffmpeg: the process exited with status %d", e.Code)
}

// Start spawns command with argv, in its own process group, and returns once
// it is running. ctx cancellation kills the whole group.
//
// fd 0 IS /dev/null, which is input/manager.py:830-834's POSIX_SPAWN_OPEN. The
// input-side transcode reads its upstream over the network and never from the
// relay; a writable stdin here would be a pipe nobody fills.
func Start(ctx context.Context, command string, argv []string) (*Process, error) {
	return start(ctx, command, argv, false)
}

// StartPiped is Start with a WRITABLE fd 0, for the output-side remux, whose
// input is the channel's own ring buffer rather than a URL
// (output/fmp4/manager.py:32-45's `-f mpegts -i pipe:0`).
//
// ONE SPAWNER, TWO ENTRY POINTS, and that is deliberate rather than tidy: the
// Setpgid/Pdeathsig group, the SIGKILL-only cancel, the KillWait budget, the
// three-way exit mapping and the stderr splitter are the observable contract
// this package exists to hold, and an output-side process that got its own
// spawn would be a second copy of all five -- the shape D5's "do not write a
// second implementation of the truth" warns about. The ONLY difference is
// fd 0, and it is one parameter.
func StartPiped(ctx context.Context, command string, argv []string) (*Process, error) {
	return start(ctx, command, argv, true)
}

func start(ctx context.Context, command string, argv []string, pipeStdin bool) (*Process, error) {
	if strings.Contains(command, "://") {
		return nil, ErrCommandIsAURL
	}
	ctx, cancel := context.WithCancel(ctx)
	// #nosec G204 -- the command and its arguments ARE the Stream Profile:
	// an operator-configured executable and the argv Django built from its
	// parameters (StreamProfile.build_command). Spawning them is this
	// function's whole job, and the URL-in-command case is refused above.
	cmd := exec.CommandContext(ctx, command, argv...)
	cmd.SysProcAttr = sysProcAttr()
	cmd.Cancel = func() error {
		// The whole group, not just the leader: with Setpgid the child's
		// own pid is the group id, and the negative form addresses the
		// group. A process that has already gone answers ESRCH, which
		// os/exec treats as "already dead".
		return syscall.Kill(-cmd.Process.Pid, syscall.SIGKILL)
	}
	cmd.WaitDelay = KillWait

	var stdin io.WriteCloser
	if pipeStdin {
		var err error
		stdin, err = cmd.StdinPipe()
		if err != nil {
			cancel()
			return nil, fmt.Errorf("ffmpeg: opening the stdin pipe: %w", err) // credential-logging: ok - an os.Pipe failure, no URL anywhere in it
		}
	}
	stdout, err := cmd.StdoutPipe()
	if err != nil {
		cancel()
		return nil, fmt.Errorf("ffmpeg: opening the stdout pipe: %w", err) // credential-logging: ok - an os.Pipe failure, no URL anywhere in it
	}
	// THE STDERR PIPE IS OURS, NOT cmd.StderrPipe()'s, AND THAT IS ISSUE #304.
	//
	// os/exec's own documentation on StderrPipe says it plainly: "Wait will
	// close the pipe after seeing the command exit, so most callers need not
	// close it themselves; it is thus incorrect to call Wait before all reads
	// from the pipe have completed." Process.Wait below calls cmd.Wait, and
	// BOTH of this package's consumers reach it with their stderr drain still
	// running -- channel.TranscodeSource.Run waits for the process and only
	// then joins the reader (source_transcode.go), and 2c-6's output pipeline
	// does the same. Under package-wide scheduling pressure the drain is cut
	// off part-way: the 2c-5 review reproduced it as
	// TestParsedStderrReachesTheChannelsStats reporting an EARLIER progress
	// record's speed than the corpus's last (ffmpeg_speed 3.98 where 2.87 was
	// due), once in nine no-race runs, and deterministically with a few
	// milliseconds of delay per read.
	//
	// AN os.Pipe THE PARENT OWNS FIXES IT AT THE SOURCE, and fixes both call
	// sites with one edit rather than imposing an ordering rule on every
	// future one. cmd.Wait closes only the pipes os/exec itself created; an
	// *os.File assigned to cmd.Stderr it leaves alone. The parent's copy of
	// the WRITE end is closed immediately after Start -- otherwise the reader
	// would never see EOF, because this process would still hold one open --
	// so the reader's EOF is exactly the child's last byte, whenever the
	// reaper runs. ReadStderr closes the read end when it returns, which is
	// the one place it can be closed safely: it is the sole consumer and it
	// returns only at EOF or on a read error.
	//
	// IN PRODUCTION the defect loses the last progress records before an exit,
	// so ffmpeg_speed, total_bytes and the rest of channel.Stats could be
	// stale at teardown by however many records the drain missed. Nothing a
	// viewer sees; something the status endpoints render.
	stderrRead, stderrWrite, err := os.Pipe()
	if err != nil {
		cancel()
		return nil, fmt.Errorf("ffmpeg: opening the stderr pipe: %w", err) // credential-logging: ok - an os.Pipe failure, no URL anywhere in it
	}
	cmd.Stderr = stderrWrite
	if err := cmd.Start(); err != nil {
		_ = stderrRead.Close()
		_ = stderrWrite.Close()
		cancel()
		// exec.Error carries the command NAME (refused above if it were a
		// URL); a *fs.PathError carries the executable's path. Neither
		// carries argv, which is where the URL is.
		return nil, fmt.Errorf("ffmpeg: starting %s: %w", command, err) // credential-logging: ok - exec.Error and PathError name the executable, never argv, and a URL-shaped command is refused before this line
	}
	// The child holds its own copy now, so the parent's must go or the reader
	// never sees EOF (#304).
	_ = stderrWrite.Close()
	return &Process{cmd: cmd, stdout: stdout, stderr: stderrRead, stdin: stdin, cancel: cancel, ended: make(chan struct{})}, nil
}

// Stdin is the write end of a StartPiped process's fd 0, and nil for one
// started by Start.
func (p *Process) Stdin() io.Writer { return p.stdin }

// CloseStdin closes fd 0, which is how a remux is asked to flush and exit
// cleanly: output/fmp4/manager.py:159-163's stop() closes the child's stdin
// first and only kills it if it is still running afterwards. Idempotent, and a
// no-op for a process started by Start.
//
// sync.Once rather than a nil check after closing, because both the writer
// goroutine's own deferred close (manager.py:244-249's `finally`) and Stop
// call it, from different goroutines: os.File.Close is not documented as safe
// to call concurrently with itself, and `go test -race` would not necessarily
// see the overlap.
func (p *Process) CloseStdin() {
	if p.stdin == nil {
		return
	}
	p.closeOnce.Do(func() { _ = p.stdin.Close() })
}

// Stdout is the read end of the process's fd 1: the video bytes.
func (p *Process) Stdout() io.Reader { return p.stdout }

// PID is the process id, for tests and logs.
func (p *Process) PID() int { return p.cmd.Process.Pid }

// ReadStderr drains fd 2 to EOF, calling fn for every line.
//
// THE SPLIT IS input/manager.py:981-1003's: whichever of CR or LF comes
// first ends a line, because ffmpeg TERMINATES a progress record with CR
// (rewriting one status line in place) and ends everything else with LF; a
// reader that split on LF alone would see one enormous line per tune.
// Empty lines are skipped after trimming, as :994-996 does. And a buffer
// that grows past 1 KiB with no terminator and no "frame=" in it is flushed
// as a line (:986-991), which is how a long diagnostic with no newline still
// reaches the log rather than waiting for the next record.
//
// It never returns an error: a broken stderr pipe means the process is
// going, and Wait is where that is reported.
func (p *Process) ReadStderr(fn func(line string)) {
	// The sole consumer closes the read end, and this is the only place it is
	// closed (#304): Wait must not, because a Wait racing an unfinished drain
	// is the defect itself.
	defer func() { _ = p.stderr.Close() }()
	var buf []byte
	chunk := make([]byte, 4096) // input/manager.py:976's read size
	for {
		n, err := p.stderr.Read(chunk)
		if n > 0 {
			buf = append(buf, chunk[:n]...)
			for {
				cr := bytes.IndexByte(buf, '\r')
				nl := bytes.IndexByte(buf, '\n')
				if cr == -1 && nl == -1 {
					if len(buf) > 1024 && !bytes.Contains(buf, []byte("frame=")) {
						emit(fn, buf)
						buf = buf[:0]
					}
					break
				}
				var line []byte
				if cr != -1 && (nl == -1 || cr < nl) {
					line, buf = buf[:cr], buf[cr+1:]
				} else {
					line, buf = buf[:nl], buf[nl+1:]
				}
				emit(fn, line)
			}
		}
		if err != nil {
			break
		}
	}
	// :1015-1021: whatever is left when the pipe closes is one last line.
	emit(fn, buf)
}

func emit(fn func(string), line []byte) {
	// utf-8 with errors ignored there (:992); Go strings carry the bytes as
	// they are and a parser regex simply fails to match an invalid sequence.
	text := strings.TrimSpace(string(line))
	if text != "" {
		fn(text)
	}
}

// Kill sends SIGKILL to the process group. Idempotent; safe after exit.
func (p *Process) Kill() { p.cancel() }

// Wait reaps the process and reports how it ended: nil for exit status 0,
// *ErrExited otherwise, and ctx.Err()-shaped errors are NOT what it returns
// -- a process this package killed reports ErrExited{Code: -9}, and the
// caller knows whether it asked for that.
//
// It closes the stdout pipe first, so a process still writing to fd 1 after
// the reader has stopped gets EPIPE rather than blocking forever on a full
// pipe nobody drains. Callable more than once.
func (p *Process) Wait() error {
	select {
	case <-p.ended:
		return p.err
	default:
	}
	_ = p.stdout.Close()
	err := p.cmd.Wait()
	// exec.CommandContext reports the context's own error once it has
	// killed the process, which would make "we cancelled it" and "it died
	// of signal 9 on its own" indistinguishable. The ProcessState is the
	// fact; the context is the reason, and the caller holds the reason.
	if p.cmd.ProcessState != nil {
		if status, ok := p.cmd.ProcessState.Sys().(syscall.WaitStatus); ok {
			switch {
			case status.Exited() && status.ExitStatus() == 0:
				err = nil
			case status.Exited():
				err = &ErrExited{Code: status.ExitStatus()}
			case status.Signaled():
				err = &ErrExited{Code: -int(status.Signal())}
			default:
				err = &ErrExited{Code: -1}
			}
		}
	} else if err != nil {
		err = &ErrExited{Code: -1}
	}
	p.err = err
	p.cancel()
	close(p.ended)
	return err
}
