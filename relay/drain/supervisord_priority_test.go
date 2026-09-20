package drain

import (
	"os"
	"path/filepath"
	"regexp"
	"strconv"
	"testing"

	"github.com/D10Scot/Dispatcharr/relay/internal/relaytest"
)

// supervisordPriorityRe finds the ONE key this test's claim rests on. Anchored
// and comment-aware, for the same reason supervisordStopWaitRe in drain_test.go
// is: `#priority=206` in a note must not be read as the setting, and
// supervisord's own ini parser would not read it either.
var supervisordPriorityRe = regexp.MustCompile(`(?m)^[ \t]*priority[ \t]*=[ \t]*([0-9]+)[ \t]*$`)

// supervisordPriority reads one program conf's priority= out of the file that
// actually ships. It FAILS rather than skipping or defaulting when the file or
// the key is missing -- a helper that fell back to 205 would turn a renamed or
// deleted key into a permanently green test asserting a relationship nothing in
// the repository states any more, which is the silence-read-as-pass shape this
// test exists to avoid one level up.
func supervisordPriority(t *testing.T, conf string) int {
	t.Helper()
	rel := filepath.Join("docker", "supervisord.d", conf)
	path := filepath.Join(relaytest.RepoRoot(), rel)
	raw, err := os.ReadFile(path) // #nosec G304 -- a path this test computed from the repo root
	if err != nil {
		t.Fatalf("cannot read %s: %v -- this test's whole claim is a relationship between two "+
			"supervisord confs, so it must not pass without reading both", rel, err)
	}
	match := supervisordPriorityRe.FindSubmatch(raw)
	if match == nil {
		t.Fatalf("%s declares no priority=<n>. Either supervisord's start/stop ordering for this "+
			"program moved to another key, or it was removed -- both change what this test is "+
			"asserting, so neither may be defaulted through", rel)
	}
	value, err := strconv.Atoi(string(match[1]))
	if err != nil { // unreachable while the pattern is [0-9]+, kept so a widened pattern cannot pass silently
		t.Fatalf("%s: priority=%q is not an integer: %v", rel, match[1], err)
	}
	return value
}

// The container's stop budget is a SUM ACROSS PRIORITY GROUPS, not a maximum:
// supervisord signals one group at a time and waits out that group's
// stopwaitsecs before moving on. relay-go and relay-uwsgi share priority=205
// deliberately, so the pair costs max(20, 20) = 20s rather than 20 + 20; a
// priority of its own would take the container total from 155s to 175s against
// docker-compose's 160s stop_grace_period and start SIGKILLing every deploy
// mid-shutdown.
//
// That arithmetic is stated as a comment in relay-go.conf:7-13 and, until
// stage 2d-3, asserted by nothing at all -- drain_test.go reads stopwaitsecs
// and only stopwaitsecs. After 2d the claim stays load-bearing, because
// relay-uwsgi survives narrowed to VOD and catch-up, so the shared group
// survives with it.
//
// READ from both confs rather than restated as Go constants, for the reason
// drain_test.go's own helper gives: a derived threshold copied into the test
// goes stale silently.
func TestBothRelayProgramsShareOnePriorityGroup(t *testing.T) {
	goPriority := supervisordPriority(t, "relay-go.conf")
	uwsgiPriority := supervisordPriority(t, "relay-uwsgi.conf")

	if goPriority != uwsgiPriority {
		t.Fatalf("relay-go.conf declares priority=%d and relay-uwsgi.conf declares priority=%d.\n"+
			"They must share one supervisord priority group: a group of its own adds relay-go's\n"+
			"stopwaitsecs to the container's stop budget as a separate window, taking the sum from\n"+
			"155s to 175s against a 160s stop_grace_period.",
			goPriority, uwsgiPriority)
	}
}
