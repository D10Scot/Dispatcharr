package relaytest

import (
	"fmt"
	"io"
	"net/http"
	"os"
	"os/signal"
	"strconv"
	"strings"
	"syscall"
	"time"

	"github.com/D10Scot/Dispatcharr/relay/redact"
)

// The stand-in: a program that behaves like ffmpeg from the relay's side
// without being one. The Go counterpart of apps/proxy/live_proxy/tests/
// harness/standin.py, which states the rule this one keeps:
//
//	Every spawn is real. The child program is the stand-in when the test's
//	subject is the relay's REACTION to what a process said or did -- a stderr
//	line, an exit code, an exit moment, a byte rate -- because those must be
//	exact and a real ffmpeg cannot be made exact on demand. The child program
//	is real ffmpeg when the test's subject is the bytes a remuxer produces.
//	It is never a Go object standing in for a process.
//
//	And every line the stand-in writes to stderr came out of a real ffmpeg.
//
// HOW IT IS A SEPARATE PROCESS WITHOUT A SECOND BINARY: the test binary
// re-executes itself. A package that spawns the stand-in declares one
// trampoline test,
//
//	func TestStandIn(t *testing.T) {
//		if os.Getenv(StandInEnv) != "1" { return }
//		os.Exit(RunStandIn(StandInArgs()))
//	}
//
// and StandInCommand builds the (command, argv) pair that reaches it:
// os.Args[0] with -test.run=^TestStandIn$ and the stand-in's own flags after
// "--". The relay's spawn passes os.Environ() to the child exactly as
// input/manager.py:839 passes os.environ, so a t.Setenv(StandInEnv, "1") in
// the test is what turns the re-executed binary into the stand-in. This is
// the shape os/exec's own tests use, and it needs no Python and no second
// executable on PATH -- which also keeps the module free of anything that
// could look like a second implementation of ffmpeg.
//
// Flags, harness/standin.py:26-36's, plus three for tests Python has no need
// of because its stand-in runs under a relay that never sends SIGKILL to a
// process group:
//
//	-i INPUT                 a URL to GET and copy to stdout, or a file path,
//	                         or pipe:0
//	--stderr-corpus PATH     the captured .stderr file to replay
//	--stderr-interval S      seconds between progress records (default 0.05);
//	                         the preamble is always written immediately
//	--stderr-loop            restart the corpus when it runs out
//	--exit-after-bytes N     exit after copying N bytes
//	--exit-code N            the code to exit with (default 0)
//	--dead-air-after-bytes N stop writing after N bytes but stay alive
//	--echo-argv              write "stand-in argv: ..." to stderr first, so a
//	                         test can see what it was spawned with
//	--ignore-sigterm         stay alive through SIGTERM, so a test can tell
//	                         SIGKILL from SIGTERM
//	--stdin-probe            report on stderr whether stdin was at EOF

// StandInEnv is the environment variable that turns the re-executed test
// binary into the stand-in.
const StandInEnv = "RELAY_STANDIN"

// StandInCommand is the (command, argv) a fake control plane answers with to
// make the relay spawn the stand-in with args.
func StandInCommand(args ...string) (command string, argv []string) {
	argv = append([]string{"-test.run=^TestStandIn$", "--"}, args...)
	return os.Args[0], argv
}

// StandInArgs is the stand-in's own arguments: everything after "--".
func StandInArgs() []string {
	for i, a := range os.Args {
		if a == "--" {
			return os.Args[i+1:]
		}
	}
	return nil
}

type standInOptions struct {
	input          string
	corpus         string
	interval       time.Duration
	loop           bool
	exitAfter      int
	exitCode       int
	deadAirAfter   int
	echoArgv       bool
	ignoreSigterm  bool
	stdinProbe     bool
	haveExitAfter  bool
	haveDeadAir    bool
	positional     []string
	originalArgs   []string
	fatalParseFlag string
}

func parseStandIn(args []string) standInOptions {
	o := standInOptions{interval: 50 * time.Millisecond, originalArgs: args}
	for i := 0; i < len(args); i++ {
		next := func() string {
			if i+1 >= len(args) {
				o.fatalParseFlag = args[i]
				return ""
			}
			i++
			return args[i]
		}
		switch a := args[i]; a {
		case "--stderr-corpus":
			o.corpus = next()
		case "--stderr-interval":
			secs, _ := strconv.ParseFloat(next(), 64)
			o.interval = time.Duration(secs * float64(time.Second))
		case "--stderr-loop":
			o.loop = true
		case "--exit-after-bytes":
			o.exitAfter, _ = strconv.Atoi(next())
			o.haveExitAfter = true
		case "--exit-code":
			o.exitCode, _ = strconv.Atoi(next())
		case "--dead-air-after-bytes":
			o.deadAirAfter, _ = strconv.Atoi(next())
			o.haveDeadAir = true
		case "--echo-argv":
			o.echoArgv = true
		case "--ignore-sigterm":
			o.ignoreSigterm = true
		case "--stdin-probe":
			o.stdinProbe = true
		case "-i":
			// ffmpeg's own input flag. Above the generic dash branch, for
			// the reason standin.py:90-101 records: `-i` starts with a dash.
			o.input = next()
		default:
			if strings.HasPrefix(a, "-") {
				// Any other flag -- ffmpeg's own, whatever the profile
				// carries -- is accepted and ignored, so the production
				// parameter string works unchanged.
				continue
			}
			o.positional = append(o.positional, a)
		}
	}
	if o.input == "" && len(o.positional) > 0 {
		o.input = o.positional[len(o.positional)-1]
	}
	return o
}

// RunStandIn runs the stand-in and returns the exit code the caller should
// os.Exit with.
func RunStandIn(args []string) int {
	o := parseStandIn(args)
	if o.fatalParseFlag != "" {
		fmt.Fprintf(os.Stderr, "stand-in: %s needs a value\n", o.fatalParseFlag)
		return 2
	}
	if o.echoArgv {
		// Mimics the one thing about ffmpeg's stderr that matters to the
		// redaction tests: it echoes the URL it was given.
		fmt.Fprintf(os.Stderr, "stand-in argv: %s\n", strings.Join(o.originalArgs, " "))
	}
	if o.ignoreSigterm {
		signal.Ignore(syscall.SIGTERM)
	}
	if o.stdinProbe {
		buf := make([]byte, 1)
		n, err := os.Stdin.Read(buf)
		switch {
		case n == 0 && err == io.EOF:
			fmt.Fprintln(os.Stderr, "stand-in stdin: EOF")
		case err != nil:
			fmt.Fprintf(os.Stderr, "stand-in stdin: error %v\n", err) // credential-logging: ok - a read error on fd 0
		default:
			fmt.Fprintln(os.Stderr, "stand-in stdin: data")
		}
	}
	if o.input == "" {
		fmt.Fprintln(os.Stderr, "stand-in: no input; expected `-i <url>` or a positional")
		return 2
	}

	if o.corpus != "" {
		// The pump is JOINED before RunStandIn returns, unless it loops.
		// Without the join, a file input at interval 0 finished its copy
		// and returned before the goroutine had ever been scheduled, and
		// os.Exit killed the pump with nothing written -- deterministically
		// without `-race`, and green under it only because the detector's
		// slower scheduling let the pump run first (break-check 22). A
		// daemon thread in standin.py has no such hazard: a Python thread
		// starts running synchronously. Deferred, so every return path
		// waits -- an exit code, EPIPE on fd 1, an input error -- which is
		// also what a real ffmpeg does: its stderr epilogue lands before it
		// exits. A looping pump never returns, so it is not joined; dead
		// air never returns either, so the join is unreachable there.
		pumped := make(chan struct{})
		go func() {
			defer close(pumped)
			pumpStderr(o.corpus, o.interval, o.loop)
		}()
		if !o.loop {
			defer func() { <-pumped }()
		}
	}

	var source io.ReadCloser
	switch {
	case o.input == "pipe:0":
		source = os.Stdin
	case strings.Contains(o.input, "://"):
		client := &http.Client{Timeout: 0}
		response, err := client.Get(o.input) //nolint:noctx // the stand-in is a separate process with no context to carry
		if err != nil {
			// The stand-in's stderr is what the relay under test redacts, and
			// this error would carry the input URL as ffmpeg's own would; it
			// is stripped here anyway, so a test that captures the child's
			// stderr directly is not handed a URL by test support.
			fmt.Fprintf(os.Stderr, "stand-in: fetching input: %v\n", redact.Error(err))
			return 1
		}
		defer func() { _ = response.Body.Close() }()
		source = response.Body
	default:
		f, err := os.Open(o.input)
		if err != nil {
			fmt.Fprintf(os.Stderr, "stand-in: opening input: %v\n", err) // credential-logging: ok - an *fs.PathError over a test asset path
			return 1
		}
		defer func() { _ = f.Close() }()
		source = f
	}

	copied := 0
	buf := make([]byte, 8192)
	for {
		n, err := source.Read(buf)
		if n > 0 {
			chunk := buf[:n]
			if o.haveExitAfter && copied+n >= o.exitAfter {
				_, _ = os.Stdout.Write(chunk[:o.exitAfter-copied])
				return o.exitCode
			}
			if o.haveDeadAir && copied+n >= o.deadAirAfter {
				_, _ = os.Stdout.Write(chunk[:o.deadAirAfter-copied])
				// Alive, connected, producing nothing -- what a dead-air
				// watchdog is for. A sleep loop, as standin.py:196-197, and
				// NOT `select {}`: with the stderr pump finished this would
				// be the only goroutine, and Go's runtime kills a process
				// whose every goroutine is asleep with "fatal error: all
				// goroutines are asleep - deadlock!" -- on stderr, where the
				// relay's reader would take it for a diagnostic line.
				for {
					time.Sleep(time.Second)
				}
			}
			if _, werr := os.Stdout.Write(chunk); werr != nil {
				// The relay closed its side: an ordinary end.
				return o.exitCode
			}
			copied += n
		}
		if err != nil {
			return o.exitCode
		}
	}
}

// pumpStderr replays a capture: the preamble at once, then one progress
// record per interval, CR-terminated -- standin.py:117-156, including its
// stated non-exactness about the LAST record of a real capture.
func pumpStderr(path string, interval time.Duration, loop bool) {
	raw, err := os.ReadFile(path) // #nosec G304 -- a fixture path the test itself chose
	if err != nil {
		fmt.Fprintf(os.Stderr, "stand-in: reading the corpus: %v\n", err) // credential-logging: ok - an *fs.PathError over a fixture path
		return
	}
	preamble, records := SplitCorpus(raw)
	_, _ = os.Stderr.Write(preamble)
	for {
		for _, record := range records {
			if interval > 0 {
				time.Sleep(interval)
			}
			if _, err := os.Stderr.Write(append(append([]byte(nil), record...), '\r')); err != nil {
				return
			}
		}
		if !loop {
			return
		}
	}
}
