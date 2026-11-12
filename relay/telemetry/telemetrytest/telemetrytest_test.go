package telemetrytest

import (
	"context"
	"fmt"
	"testing"

	"github.com/D10Scot/Dispatcharr/relay/telemetry"
)

// spyTB records failures instead of failing the real test.
type spyTB struct {
	testing.TB
	failures []string
}

func (s *spyTB) Helper() {}

func (s *spyTB) Errorf(format string, args ...any) {
	s.failures = append(s.failures, fmt.Sprintf(format, args...))
}

// O4's disarm oracle is "M3 = 0". A reader that cannot collect must fail the
// test, not read as zero.
func TestAFailedCollectionFailsTheTestRatherThanReadingZero(t *testing.T) {
	spy := &spyTB{TB: t}
	rec := Install(spy)
	rec.T.ClientSent(context.Background(), 7, telemetry.FormatMPEGTS, 188)
	if got := rec.Sum("mino_relay_client_sent"); got != 188 || len(spy.failures) != 0 {
		t.Fatalf("control: sum = %v, failures = %v", got, spy.failures)
	}
	if err := rec.reader.Shutdown(context.Background()); err != nil {
		t.Fatal(err)
	}
	if got := rec.Sum("mino_relay_client_sent"); got != 0 {
		t.Fatalf("sum after shutdown = %v", got)
	}
	if len(spy.failures) != 1 {
		t.Fatalf("a failed collection recorded %d failures, want 1: an empty figure reads as M3 = 0", len(spy.failures))
	}
	if rec.Exemplars("mino_relay_client_sent") != -1 || len(spy.failures) != 2 {
		t.Fatalf("Exemplars must report -1 and fail the test: %v", spy.failures)
	}
}
