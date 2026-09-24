package relaytest

import (
	"bytes"
	"fmt"
	"os"
	"path/filepath"
	"regexp"
	"runtime"
	"strconv"
)

// The captured real-ffmpeg stderr corpus, in this package's own testdata
// directory since Phase 2 stage 2d-4.
//
// It used to be READ IN PLACE from the Python harness's fixtures directory
// and never copied, because "two copies of a corpus that must not be edited
// is one copy nobody remembers to regenerate". Stage 2d-4 deleted
// apps/proxy/live_proxy/, so there is no second copy to diverge from and the
// rationale went with it; the files moved here rather than being duplicated.
//
// testdata/ffmpeg_stderr/CAPTURE.md moved with them and is still the
// authority on what they are: verbatim captures from ffmpeg 8.1.2, CR
// separators included, never hand-edited, regenerated only by
// scripts/capture_ffmpeg_stderr.py. Every rule it states about the corpus --
// the digits are a timing measurement, only the SHAPE is asserted -- binds
// these tests.

// CorpusNames are the captures: three from the shipped ffmpeg 8.1.2, and two
// from ffmpeg 6.1.1 (issue #299), whose stream-copy progress records begin
// size= and carry no frame= at all. CorpusSpeeds panics on the 6.1.1 pair --
// each opens with a speed=N/A record -- so read those through SplitCorpus.
var CorpusNames = []string{"normal", "slow-trickle", "truncation", "ffmpeg6-normal", "ffmpeg6-slow-trickle"}

// pkgDir is this file's own directory, from its compiled-in path.
//
// runtime.Caller rather than a relative string, and this is the whole reason
// the corpus move needed a code change at all: `go test` sets the working
// directory to the PACKAGE being tested, and Corpus() is called from
// relay/ffmpeg, relay/httpapi and relay/channel as well as from here. A bare
// "testdata/..." resolves against the CALLER's directory and is found only in
// this package -- green in the one place a maintainer would look first, and
// a panic everywhere else.
//
// The value stays ABSOLUTE because CorpusPath's eleven callers hand it through
// argv to a re-exec'd stand-in (standin.go), which has no cwd of its own to
// resolve against. Note -trimpath would defeat this; nothing runs `go test`
// with it (docker/Dockerfile's `go build -trimpath` is the production binary).
func pkgDir() string {
	_, file, _, ok := runtime.Caller(0)
	if !ok {
		panic("relaytest: runtime.Caller failed")
	}
	return filepath.Dir(file)
}

// RepoRoot is the repository root, resolved from this file's own compiled-in
// path: relay/internal/relaytest is three levels below it. Exported because
// this package is the module's ONE answer to "where is the repo from a test",
// and since stage 2d-4 moved the corpus into testdata/ it is the module's only
// repo-relative read left: relay/drain's tests read
// docker/supervisord.d/relay-go.conf through it, and a second, independently
// maintained directory walk is the kind of drift that goes wrong quietly.
func RepoRoot() string {
	return filepath.Dir(filepath.Dir(filepath.Dir(pkgDir())))
}

// CorpusPath is the absolute path of one capture.
func CorpusPath(name string) string {
	for _, known := range CorpusNames {
		if known == name {
			return filepath.Join(pkgDir(), "testdata", "ffmpeg_stderr", name+".stderr")
		}
	}
	panic(fmt.Sprintf("relaytest: unknown corpus %q", name))
}

// Corpus is one capture, byte for byte.
func Corpus(name string) []byte {
	raw, err := os.ReadFile(CorpusPath(name))
	if err != nil {
		panic(fmt.Sprintf("relaytest: reading the %s corpus: %v", name, err)) // credential-logging: ok - an *fs.PathError over a fixture path
	}
	return raw
}

// SplitCorpus is harness/ffmpeg_stderr.py's split(): the preamble, and every
// progress record, splitting on CR OR LF because that is what
// input/manager.py's _read_stderr does (:981-991) and what the captures need
// -- ffmpeg TERMINATES a record with CR, and a gracefully-exiting ffmpeg ends
// its last one with LF, so `truncation` has zero CR bytes and a CR-only split
// finds no record in it at all.
func SplitCorpus(raw []byte) (preamble []byte, records [][]byte) {
	lines := bytes.Split(bytes.ReplaceAll(raw, []byte("\r"), []byte("\n")), []byte("\n"))
	for _, line := range lines {
		if bytes.Contains(line, []byte("speed=")) {
			records = append(records, line)
		}
	}
	if len(records) == 0 {
		return raw, nil
	}
	first := bytes.Index(raw, records[0])
	return raw[:first], records
}

// The PRODUCTION speed regex, copied deliberately rather than imported from
// package ffmpeg: these helpers exist so a test can quote what the shipped
// parser sees, and importing the parser would make the quote move if the
// parser moved. The copy must therefore move WITH it, by hand: issue #227's
// fix widened package ffmpeg's speedRe to read an exponent, and this literal
// was widened in the same PR so the two agree on a scientific-notation
// record.
var (
	corpusSpeedRe   = regexp.MustCompile(`speed=\s*([0-9.]+(?:[eE][-+]?[0-9]+)?)x?`)
	corpusElapsedRe = regexp.MustCompile(`elapsed=(\d+):(\d\d):(\d\d(?:\.\d+)?)`)
)

// CorpusSpeeds is every progress record's speed=, as the production regex
// reads it -- manager_support.py's corpus_speeds.
func CorpusSpeeds(name string) []float64 {
	_, records := SplitCorpus(Corpus(name))
	out := make([]float64, 0, len(records))
	for _, r := range records {
		m := corpusSpeedRe.FindSubmatch(r)
		if m == nil {
			panic(fmt.Sprintf("relaytest: a %s record carries no speed=: %q", name, r))
		}
		v, err := strconv.ParseFloat(string(m[1]), 64)
		if err != nil {
			panic(fmt.Sprintf("relaytest: %s record %q: %v", name, r, err)) // credential-logging: ok - a strconv error over a captured progress record
		}
		out = append(out, v)
	}
	return out
}

// CorpusElapsed is record `index`'s elapsed= in seconds -- the real ffmpeg
// wall clock it took -- manager_support.py's corpus_elapsed. ffmpeg 8.1.2
// appends this field after speed=; nothing in production parses it.
func CorpusElapsed(name string, index int) float64 {
	_, records := SplitCorpus(Corpus(name))
	m := corpusElapsedRe.FindSubmatch(records[index])
	if m == nil {
		panic(fmt.Sprintf("relaytest: %s record %d carries no elapsed=", name, index))
	}
	h, _ := strconv.Atoi(string(m[1]))
	mi, _ := strconv.Atoi(string(m[2]))
	s, _ := strconv.ParseFloat(string(m[3]), 64)
	return float64(h*3600+mi*60) + s
}
