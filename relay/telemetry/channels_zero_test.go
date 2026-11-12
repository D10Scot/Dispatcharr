package telemetry_test

import (
	"fmt"
	"strings"
	"sync"
	"testing"

	"github.com/D10Scot/Dispatcharr/relay/telemetry/telemetrytest"
)

// Every channel.State value (relay/channel/state.go).
var everyChannelState = []string{"initializing", "connecting", "waiting_for_clients", "active", "buffering", "error", "stopping", "stopped"}

// M1 is zero-filled over its closed state set (observability D6, D14): an
// idle relay exports `mino_relay_channels` with every known state at 0, so
// the family is present on a relay with no channel, and a state's series
// reads 0 when its last channel leaves rather than going stale.
func TestAnIdleRelayExportsEveryChannelStateAtZero(t *testing.T) {
	rec := telemetrytest.Install(t)
	rec.T.ObserveChannels(func() map[string]int { return map[string]int{} })
	body := scrape(t, rec.T.Metrics())
	if !strings.Contains(body, "# TYPE mino_relay_channels gauge") {
		t.Fatalf("an idle relay exports no mino_relay_channels family:\n%s", body)
	}
	for _, state := range everyChannelState {
		if want := fmt.Sprintf("mino_relay_channels{state=%q} 0\n", state); !strings.Contains(body, want) {
			t.Errorf("missing %q on an idle relay:\n%s", strings.TrimSpace(want), body)
		}
	}
}

// One channel active: that state reads 1, every other known state 0, and a
// state outside the closed set is still not exported.
func TestAChannelStateReadsZeroOnceItsLastChannelLeaves(t *testing.T) {
	rec := telemetrytest.Install(t)
	var mu sync.Mutex
	counts := map[string]int{"active": 1, "nonsense": 3}
	rec.T.ObserveChannels(func() map[string]int {
		mu.Lock()
		defer mu.Unlock()
		return counts
	})
	if body := scrape(t, rec.T.Metrics()); !strings.Contains(body, `mino_relay_channels{state="active"} 1`) {
		t.Fatalf("active channel not counted:\n%s", body)
	}
	mu.Lock()
	counts = map[string]int{"stopped": 1}
	mu.Unlock()
	body := scrape(t, rec.T.Metrics())
	for _, want := range []string{`mino_relay_channels{state="active"} 0`, `mino_relay_channels{state="stopped"} 1`} {
		if !strings.Contains(body, want) {
			t.Errorf("missing %q after the channel left active:\n%s", want, body)
		}
	}
	if strings.Contains(body, "nonsense") {
		t.Errorf("an out-of-set state reached /metrics:\n%s", body)
	}
}
