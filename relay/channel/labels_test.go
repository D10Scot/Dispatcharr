package channel

import (
	"reflect"
	"testing"

	"github.com/D10Scot/Dispatcharr/relay/buffer"
	"github.com/D10Scot/Dispatcharr/relay/telemetry"
)

// profileIDOfKey labels a profiled fMP4 chain's remux with the Output
// Profile it reads (observability D7): the id after ":p", and zero for a bare
// format or anything that is not a non-negative integer.
func TestProfileIDOfKey(t *testing.T) {
	for key, want := range map[string]int{
		"fmp4":        0,
		"fmp4:p12":    12,
		"mpegts:p3":   3,
		"fmp4:p0":     0,
		"fmp4:px":     0,
		"fmp4:p-1":    0,
		"fmp4:p":      0,
		"fmp4:p12abc": 0,
	} {
		if got := profileIDOfKey(key); got != want {
			t.Errorf("profileIDOfKey(%q) = %d, want %d", key, got, want)
		}
	}
}

// M2's observation (D7): one count per (channel, format, profile), each
// channel named by its numeric id, and a channel with none (a stream
// preview, identified only by its secret UUID) not counted at all.
func TestClientCountsGroupByChannelFormatAndProfile(t *testing.T) {
	m := NewManager(ManagerConfig{BudgetBytes: buffer.TSPacketSize * 400})
	t.Cleanup(m.StopAll)
	profile := func(id int) *int { return &id }
	attach := func(id string, pk int, c *Client) {
		t.Helper()
		_, release, err := m.Attach(id, c, func() (Started, error) {
			return Started{Source: blockingSource{started: &int32Counter{}}, Tuning: testTuning(), ChannelPK: pk}, nil
		})
		if err != nil {
			t.Fatalf("Attach(%s, %s): %v", id, c.ID, err)
		}
		t.Cleanup(release)
	}
	attach("labels-a", 7, &Client{ID: "a1", UserID: "0", OutputFormat: "mpegts"})
	attach("labels-a", 7, &Client{ID: "a2", UserID: "0", OutputFormat: "mpegts"})
	attach("labels-a", 7, &Client{ID: "a3", UserID: "0", OutputFormat: "fmp4", OutputProfileID: profile(12)})
	attach("labels-a", 7, &Client{ID: "a4", UserID: "0", OutputFormat: "mpegts", OutputProfileID: profile(12)})
	attach("labels-b", 9, &Client{ID: "b1", UserID: "0", OutputFormat: "hls"})
	attach("labels-preview", 0, &Client{ID: "p1", UserID: "0", OutputFormat: "mpegts"})

	got := map[telemetry.ClientCount]bool{}
	for _, c := range m.ClientCounts() {
		got[c] = true
	}
	want := map[telemetry.ClientCount]bool{
		{ChannelID: 7, Format: "mpegts", ProfileID: 0, N: 2}:  true,
		{ChannelID: 7, Format: "fmp4", ProfileID: 12, N: 1}:   true,
		{ChannelID: 7, Format: "mpegts", ProfileID: 12, N: 1}: true,
		{ChannelID: 9, Format: "hls", ProfileID: 0, N: 1}:     true,
	}
	if !reflect.DeepEqual(got, want) {
		t.Errorf("ClientCounts = %v, want %v", got, want)
	}

	states := m.ChannelStates()
	total := 0
	for _, n := range states {
		total += n
	}
	if total != 3 {
		t.Errorf("ChannelStates = %v, want three channels in all", states)
	}
}
