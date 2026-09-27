package ffmpeg

import (
	"bytes"
	"errors"
	"io"
	"os"
	"path/filepath"
	"strings"
	"testing"

	"github.com/D10Scot/Dispatcharr/relay/internal/relaytest"
)

// Phase 4 spec, D6: the HLS encoder's spawn gives the child an output pipe at
// fd 3+i for every true entry of extra, readable through Extra(i), with the
// same process group, stdin pipe and exit mapping as StartPiped. A false
// entry is a descriptor the child does not have: writing to it fails in the
// child, and the numbering of the others does not move.
func TestStartPipedExtraGivesTheChildItsOutputPipes(t *testing.T) {
	t.Setenv(relaytest.StandInEnv, "1")
	dir := t.TempDir()
	video := filepath.Join(dir, "video")
	audio := filepath.Join(dir, "audio")
	if err := os.WriteFile(video, []byte("video on fd 1"), 0o600); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(audio, []byte("ac-3 on fd 4"), 0o600); err != nil {
		t.Fatal(err)
	}
	command, argv := relaytest.StandInCommand(
		"--fd-file", relaytest.FDFileArg(1, video),
		"--fd-file", relaytest.FDFileArg(4, audio),
		"--wait-stdin-eof")
	p, err := StartPipedExtra(t.Context(), command, argv, []bool{false, true})
	if err != nil {
		t.Fatalf("StartPipedExtra: %v", err)
	}
	if p.Extra(0) != nil || p.Extra(2) != nil || p.Extra(-1) != nil {
		t.Fatalf("Extra returned a pipe the child was not given")
	}
	got := make(chan []byte, 2)
	go func() { b, _ := io.ReadAll(p.Stdout()); got <- b }()
	go func() { b, _ := io.ReadAll(p.Extra(1)); got <- b }()
	if _, err := p.Stdin().Write([]byte("input")); err != nil {
		t.Fatalf("writing fd 0: %v", err)
	}
	p.CloseStdin()
	outputs := []string{string(<-got), string(<-got)}
	if err := p.Wait(); err != nil {
		t.Fatalf("Wait: %v", err)
	}
	joined := strings.Join(outputs, "|")
	if !strings.Contains(joined, "video on fd 1") || !strings.Contains(joined, "ac-3 on fd 4") {
		t.Fatalf("the child's outputs arrived as %q, want fd 1's and fd 4's bytes", outputs)
	}

	// fd 3 was not given, so a child writing to it fails.
	command, argv = relaytest.StandInCommand("--fd-file", relaytest.FDFileArg(3, audio))
	p, err = StartPipedExtra(t.Context(), command, argv, []bool{false, true})
	if err != nil {
		t.Fatalf("StartPipedExtra: %v", err)
	}
	var stderr bytes.Buffer
	p.ReadStderr(func(line string) { stderr.WriteString(line) })
	var exited *ErrExited
	if err := p.Wait(); !errors.As(err, &exited) || exited.Code != 2 || !strings.Contains(stderr.String(), "fd 3") {
		t.Fatalf("a write to an fd the child was not given: Wait = %v, stderr %q", err, stderr.String())
	}
}

// Nothing is opened for an empty mask; a pipe that cannot be made fails the
// spawn naming its descriptor; and a spawn that fails closes every pipe it
// made.
func TestStartPipedExtraWithoutExtrasAndOnAFailedSpawn(t *testing.T) {
	calls := 0
	newPipe = func() (*os.File, *os.File, error) {
		calls++
		if calls == 2 {
			return nil, nil, errors.New("too many open files")
		}
		return os.Pipe()
	}
	t.Cleanup(func() { newPipe = os.Pipe })
	if _, err := StartPipedExtra(t.Context(), "ffmpeg", nil, []bool{true, true}); err == nil || !strings.Contains(err.Error(), "fd 4") {
		t.Fatalf("a failed pipe for fd 4: %v", err)
	}
	newPipe = os.Pipe

	read, write, err := extraPipes(nil)
	if err != nil || read != nil || write != nil {
		t.Fatalf("extraPipes(nil) = %v, %v, %v", read, write, err)
	}
	if _, err := StartPipedExtra(t.Context(), filepath.Join(t.TempDir(), "no-such-ffmpeg"), nil, []bool{true}); err == nil {
		t.Fatal("a missing executable started")
	}
	if _, err := StartPipedExtra(t.Context(), "http://provider.invalid/x", nil, []bool{true}); !errors.Is(err, ErrCommandIsAURL) {
		t.Fatalf("a URL command: %v", err)
	}
}
