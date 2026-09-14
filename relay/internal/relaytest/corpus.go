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

// The captured real-ffmpeg stderr corpus, READ IN PLACE from the Python
// harness's own fixtures directory and never copied into this module.
//
// apps/proxy/live_proxy/tests/harness/fixtures/ffmpeg_stderr/CAPTURE.md is
// the authority on what these files are: verbatim captures from ffmpeg 8.1.2,
// CR separators included, never hand-edited. Two copies of a corpus that must
// not be edited is one copy nobody remembers to regenerate, so the Go tests
// open the same bytes the Python tests open. Every rule that file states
// about the corpus -- the digits are a timing measurement, only the SHAPE is
// asserted -- binds the Go tests too.

// CorpusNames are the three captures, harness/ffmpeg_stderr.py:15's
// CORPUS_NAMES.
var CorpusNames = []string{"normal", "slow-trickle", "truncation"}

// repoRoot locates the repository from this file's own path: relay/internal/
// relaytest/corpus.go is four levels below it. runtime.Caller rather than
// the working directory, because `go test` sets the cwd to the PACKAGE
// directory, which is a different depth for every package that reads the
// corpus.
func repoRoot() string {
	_, file, _, ok := runtime.Caller(0)
	if !ok {
		panic("relaytest: runtime.Caller failed")
	}
	return filepath.Dir(filepath.Dir(filepath.Dir(filepath.Dir(file))))
}

// CorpusPath is the absolute path of one capture.
func CorpusPath(name string) string {
	for _, known := range CorpusNames {
		if known == name {
			return filepath.Join(repoRoot(), "apps", "proxy", "live_proxy", "tests", "harness",
				"fixtures", "ffmpeg_stderr", name+".stderr")
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
// parser moved. Same rationale, and the same literal, as
// apps/proxy/live_proxy/tests/manager_support.py:24.
var (
	corpusSpeedRe   = regexp.MustCompile(`speed=\s*([0-9.]+)x?`)
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
