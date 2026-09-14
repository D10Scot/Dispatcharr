package ffmpeg

import (
	"bytes"
	"context"
	"errors"
	"io"
	"os"
	"strconv"
	"strings"
	"sync"
	"testing"
	"time"

	"github.com/D10Scot/Dispatcharr/relay/internal/relaytest"
)

// TestStandIn is the trampoline: the test binary re-executed as the stand-in
// (see relaytest/standin.go). It returns at once in an ordinary run.
func TestStandIn(_ *testing.T) {
	if os.Getenv(relaytest.StandInEnv) != "1" {
		return
	}
	os.Exit(relaytest.RunStandIn(relaytest.StandInArgs()))
}

// standIn starts the stand-in with args through the package's own Start, so
// every test here exercises the real spawn path.
func standIn(ctx context.Context, t *testing.T, args ...string) *Process {
	t.Helper()
	t.Setenv(relaytest.StandInEnv, "1")
	command, argv := relaytest.StandInCommand(args...)
	p, err := Start(ctx, command, argv)
	if err != nil {
		t.Fatalf("Start: %v", err)
	}
	return p
}

// assetFile writes a synthetic TS asset to a temp file the stand-in can
// read as its -i input.
func assetFile(t *testing.T, packets int) (string, []byte) {
	t.Helper()
	payload := relaytest.SyntheticTS(packets, 0x100)
	path := t.TempDir() + "/asset.ts"
	if err := os.WriteFile(path, payload, 0o600); err != nil {
		t.Fatalf("writing the asset: %v", err)
	}
	return path, payload
}

// The bytes a child writes to fd 1 are what Stdout reads, verbatim, and a
// child that ends with status 0 after EOF reports nil.
func TestStdoutIsTheChildsFd1Verbatim(t *testing.T) {
	path, payload := assetFile(t, 256)
	p := standIn(t.Context(), t, "-i", path)

	got, err := io.ReadAll(p.Stdout())
	if err != nil {
		t.Fatalf("reading stdout: %v", err)
	}
	if !bytes.Equal(got, payload) {
		t.Fatalf("stdout delivered %d bytes, want the asset's %d, byte for byte", len(got), len(payload))
	}
	if err := p.Wait(); err != nil {
		t.Fatalf("Wait after a clean exit: %v", err)
	}
}

// ReadStderr splits on CR and LF and sees every progress record of a real
// capture: CR == records - 1 for a gracefully-ended capture, so a reader
// that split on either alone would miscount (CAPTURE.md). The count is read
// off the corpus by relaytest.SplitCorpus, not typed.
func TestReadStderrSplitsOnCROrLFAndSeesEveryRecord(t *testing.T) {
	for _, corpus := range relaytest.CorpusNames {
		t.Run(corpus, func(t *testing.T) {
			_, records := relaytest.SplitCorpus(relaytest.Corpus(corpus))
			path, _ := assetFile(t, 4)
			p := standIn(t.Context(), t, "-i", path, "--stderr-corpus", relaytest.CorpusPath(corpus), "--stderr-interval", "0")

			var mu sync.Mutex
			var lines []string
			done := make(chan struct{})
			go func() {
				defer close(done)
				p.ReadStderr(func(line string) {
					mu.Lock()
					lines = append(lines, line)
					mu.Unlock()
				})
			}()
			_, _ = io.Copy(io.Discard, p.Stdout())
			<-done
			_ = p.Wait()

			mu.Lock()
			defer mu.Unlock()
			progress := 0
			for _, l := range lines {
				if IsProgressLine(l) {
					progress++
				}
			}
			if progress != len(records) {
				t.Fatalf("the reader saw %d progress lines, the corpus holds %d records -- the split lost or merged records", progress, len(records))
			}
			for _, l := range lines {
				if strings.ContainsAny(l, "\r\n") {
					t.Fatalf("a line still carries a terminator: %q", l)
				}
				if strings.TrimSpace(l) == "" {
					t.Fatal("an empty line was emitted; input/manager.py:994-996 skips them")
				}
			}
		})
	}
}

// A buffer past 1 KiB with no terminator and no frame= is flushed as a line
// rather than held until the next terminator (input/manager.py:986-991).
// Driven with a child that writes 1,500 bytes of diagnostic and no newline,
// then stops: without the flush the reader would deliver it only at EOF,
// which happens to be the same moment here -- so the child STAYS ALIVE
// (dead air) and the assertion is that the line arrives while it does.
func TestALongUnterminatedLineIsFlushedWhileTheChildStillRuns(t *testing.T) {
	// A corpus file of one 1,500-byte unterminated line, written by the
	// test: this is a shape the corpus rule forbids for progress lines and
	// permits for a diagnostic, because it carries no speed=.
	corpus := t.TempDir() + "/long.stderr"
	long := strings.Repeat("x", 1500)
	if err := os.WriteFile(corpus, []byte(long), 0o600); err != nil {
		t.Fatal(err)
	}
	path, _ := assetFile(t, 4)
	ctx, cancel := context.WithCancel(t.Context())
	defer cancel()
	p := standIn(ctx, t, "-i", path, "--stderr-corpus", corpus, "--dead-air-after-bytes", "188")

	got := make(chan string, 1)
	go p.ReadStderr(func(line string) {
		select {
		case got <- line:
		default:
		}
	})
	select {
	case line := <-got:
		if line != long {
			t.Fatalf("the flushed line is %d bytes, want %d: %q", len(line), len(long), strings.TrimLeft(line, "x"))
		}
	case <-time.After(5 * time.Second):
		t.Fatal("the unterminated line was not flushed while the child was alive")
	}
	p.Kill()
	_ = p.Wait()
}

// Cancelling the context kills the child with SIGKILL, not SIGTERM: the
// stand-in ignores SIGTERM, so a Cancel that sent the polite signal would
// leave it alive and this test would time out. input/manager.py:1743 sends
// SIGKILL and nothing else.
func TestCancelKillsTheChildWithSIGKILL(t *testing.T) {
	path, _ := assetFile(t, 4)
	ctx, cancel := context.WithCancel(t.Context())
	p := standIn(ctx, t, "-i", path, "--dead-air-after-bytes", "188", "--ignore-sigterm")

	// Let the child install its signal disposition before signalling it.
	buf := make([]byte, 188)
	if _, err := io.ReadFull(p.Stdout(), buf); err != nil {
		t.Fatalf("reading the first packet: %v", err)
	}
	pid := p.PID()

	start := time.Now()
	cancel()
	err := p.Wait()
	var exited *ErrExited
	if !errors.As(err, &exited) || exited.Code != -9 {
		t.Fatalf("Wait after cancel = %v, want ErrExited{Code: -9} (killed by SIGKILL)", err)
	}
	// WITHIN HALF OF KillWait, and the bound is the whole discrimination.
	// os/exec's WaitDelay sends its own SIGKILL once the delay has passed,
	// so a Cancel that sent SIGTERM to a child ignoring it would STILL end
	// in ErrExited{-9} -- 500 ms later. The first version of this test
	// allowed three seconds and stayed green with SIGTERM injected. A
	// SIGKILL is acted on in milliseconds; the WaitDelay fallback cannot
	// fire before 500 ms; 250 ms sits between the two mechanisms.
	if took := time.Since(start); took > KillWait/2 {
		t.Fatalf("the child took %s to die after cancel; a direct SIGKILL takes milliseconds, and %s is "+
			"WaitDelay's own fallback kill after a signal the child ignored", took, KillWait)
	}
	if !processGone(pid) {
		t.Fatalf("pid %d is still alive after Wait returned", pid)
	}
}

// The child's stdin is /dev/null: it reads EOF at once
// (input/manager.py:842's POSIX_SPAWN_OPEN of /dev/null). A child whose
// stdin were the relay's own, or a pipe nobody writes, would block here.
func TestTheChildsStdinIsDevNull(t *testing.T) {
	path, _ := assetFile(t, 4)
	p := standIn(t.Context(), t, "-i", path, "--stdin-probe")
	var report string
	done := make(chan struct{})
	go func() {
		defer close(done)
		p.ReadStderr(func(line string) {
			if strings.HasPrefix(line, "stand-in stdin:") {
				report = line
			}
		})
	}()
	_, _ = io.Copy(io.Discard, p.Stdout())
	<-done
	_ = p.Wait()
	if report != "stand-in stdin: EOF" {
		t.Fatalf("the child saw %q on stdin, want an immediate EOF", report)
	}
}

// A non-zero exit reaches Wait as ErrExited with the child's own code, and
// a clean exit after a partial copy reports nil: Wait reports the STATUS,
// and what a status means is the caller's decision.
func TestWaitReportsTheChildsExitStatus(t *testing.T) {
	path, _ := assetFile(t, 8)
	for _, code := range []int{0, 1, 3} {
		t.Run("exit "+strconv.Itoa(code), func(t *testing.T) {
			p := standIn(t.Context(), t, "-i", path, "--exit-after-bytes", "376", "--exit-code", strconv.Itoa(code))
			got, _ := io.ReadAll(p.Stdout())
			if len(got) != 376 {
				t.Fatalf("stdout delivered %d bytes before the exit, want 376", len(got))
			}
			err := p.Wait()
			if code == 0 {
				if err != nil {
					t.Fatalf("Wait = %v, want nil for exit status 0", err)
				}
				return
			}
			var exited *ErrExited
			if !errors.As(err, &exited) || exited.Code != code {
				t.Fatalf("Wait = %v, want ErrExited{Code: %d}", err, code)
			}
		})
	}
}

// A command that is a URL is refused before anything is spawned: exec.Error
// prints the command NAME, and a URL there would be the one shape
// redact.Error cannot strip.
func TestACommandThatIsAURLIsRefusedBeforeSpawning(t *testing.T) {
	_, err := Start(t.Context(), "http://provider.example/live/u/hunter2/1.ts", nil)
	if !errors.Is(err, ErrCommandIsAURL) {
		t.Fatalf("Start with a URL command = %v, want ErrCommandIsAURL", err)
	}
	if err != nil && strings.Contains(err.Error(), "hunter2") {
		t.Fatalf("the refusal echoes the credential: %v", err)
	}
}

// A command that cannot be found fails Start with exec's own error, which
// names the executable and never the argv.
func TestAMissingExecutableFailsStartWithoutEchoingArgv(t *testing.T) {
	_, err := Start(t.Context(), "relay-no-such-executable-2c4", []string{"-i", "http://provider.example/live/u/hunter2/1.ts"})
	if err == nil {
		t.Fatal("Start found an executable that does not exist")
	}
	if strings.Contains(err.Error(), "hunter2") {
		t.Fatalf("the start error echoes the URL from argv: %v", err)
	}
	if !strings.Contains(err.Error(), "relay-no-such-executable-2c4") {
		t.Fatalf("the start error lost the executable's name: %v", err)
	}
}
