//go:build linux

package ffmpeg

import (
	"bufio"
	"context"
	"fmt"
	"io"
	"os"
	"os/exec"
	"strconv"
	"strings"
	"syscall"
	"testing"
	"time"

	"github.com/D10Scot/Dispatcharr/relay/internal/relaytest"
)

// parentEnv turns the re-executed test binary into a RELAY: a process that
// spawns the stand-in through this package's Start, prints the child's pid,
// and then hangs. The test kills it and watches the child.
const parentEnv = "RELAY_PDEATHSIG_PARENT"

// TestParentProcess is the second trampoline. Under parentEnv it is the
// relay stand-in described above; in an ordinary run it returns at once.
func TestParentProcess(t *testing.T) {
	if os.Getenv(parentEnv) != "1" {
		return
	}
	// THE CHILD MUST BLOCK ON NOTHING BUT TIME. An earlier version of this
	// helper had it copy /dev/zero into a stdout pipe nobody drained, and
	// the break-check that removed Pdeathsig STAYED GREEN: when the parent
	// died the pipe's read end closed, the child's next write got EPIPE,
	// and it exited on its own -- a true positive for a false reason. The
	// defect this test guards is an ffmpeg blocked READING a stalled
	// upstream, which never writes and so never sees EPIPE; only the
	// kernel's parent-death signal reaches it. Dead-air mode is that shape:
	// one write, then a sleep loop, with stdin already /dev/null.
	command, argv := relaytest.StandInCommand("-i", "/dev/zero", "--dead-air-after-bytes", "188")
	p, err := Start(context.Background(), command, argv)
	if err != nil {
		fmt.Println("start failed:", err)
		os.Exit(1)
	}
	// READ THE CHILD'S ONE WRITE BEFORE ANNOUNCING IT. The second version of
	// this helper printed the pid at once, and the break-check stayed green
	// a second time: the child was still starting when the parent was
	// killed, its first write to fd 1 found a pipe with no reader, and Go
	// terminates a program on EPIPE to stdout -- measured at state R and
	// gone within 10 ms, with Pdeathsig removed. Once these 188 bytes are
	// in hand the child has entered its sleep loop and will never write
	// again, so from here only the kernel can end it.
	if _, err := io.ReadFull(p.Stdout(), make([]byte, 188)); err != nil {
		fmt.Println("the child never wrote:", err)
		os.Exit(1)
	}
	fmt.Println(p.PID())
	// Never reaps the child. The only thing that can end it now is the
	// kernel. A sleep loop rather than `select {}`: with no other goroutine
	// the runtime would report a deadlock and EXIT, and a parent that dies
	// on its own takes the child with it through the very mechanism under
	// test.
	for {
		time.Sleep(time.Hour)
	}
}

// SPEC D5's FIRST EXCEPTION, pinned: a child of a dead relay dies with it.
//
// The child is in its own process group (Setpgid), so killing the parent's
// group would not reach it and killing the parent alone reaches it ONLY
// through Pdeathsig. The parent is SIGKILLed, which is the shape of a crash
// or an OOM kill rather than a drain, and the child must be gone within a
// bounded time. Without Pdeathsig the child is reparented to init and lives
// on holding its provider slot -- the defect CLAUDE.md § Operationally
// records for the Python relay.
func TestAChildOfADeadRelayDiesWithIt(t *testing.T) {
	t.Setenv(relaytest.StandInEnv, "1")
	t.Setenv(parentEnv, "1")
	parent := exec.CommandContext(t.Context(), os.Args[0], "-test.run=^TestParentProcess$")
	parent.SysProcAttr = &syscall.SysProcAttr{Setpgid: true}
	stdout, err := parent.StdoutPipe()
	if err != nil {
		t.Fatal(err)
	}
	if err := parent.Start(); err != nil {
		t.Fatalf("starting the parent: %v", err)
	}
	defer func() {
		_ = parent.Process.Kill()
		_ = parent.Wait()
	}()

	scanner := bufio.NewScanner(stdout)
	if !scanner.Scan() {
		t.Fatal("the parent printed nothing")
	}
	line := strings.TrimSpace(scanner.Text())
	childPID, err := strconv.Atoi(line)
	if err != nil {
		t.Fatalf("the parent printed %q, want the child's pid", line)
	}
	if processGone(childPID) {
		t.Fatalf("child %d is not alive before the parent is killed", childPID)
	}

	if err := syscall.Kill(parent.Process.Pid, syscall.SIGKILL); err != nil {
		t.Fatalf("killing the parent: %v", err)
	}
	_ = parent.Wait()

	deadline := time.Now().Add(5 * time.Second)
	for !processGone(childPID) {
		if time.Now().After(deadline) {
			_ = syscall.Kill(childPID, syscall.SIGKILL)
			t.Fatalf("child %d outlived its dead parent by five seconds -- Pdeathsig is not set, "+
				"and an ffmpeg blocked on a stalled upstream would hold its provider slot forever", childPID)
		}
		time.Sleep(20 * time.Millisecond)
	}
}
