package telemetry_test

import (
	"net/http/httptest"
	"testing"

	"github.com/D10Scot/Dispatcharr/relay/telemetry"
	"github.com/D10Scot/Dispatcharr/relay/telemetry/telemetrytest"
)

// The writer caches M3's attribute set between writes (O2 review, nit 15);
// a change of labels must still reach the next write, or every byte after a
// relabel would be counted against the first channel the writer saw.
func TestARelabelledWriterCountsUnderItsNewLabels(t *testing.T) {
	rec := telemetrytest.Install(t)
	w := telemetry.NewFirstWriteWriter(httptest.NewRecorder(), nil)
	w.Arm()
	w.SetLabels(9, telemetry.FormatHLS)
	_, _ = w.Write(make([]byte, 40))
	_, _ = w.Write(make([]byte, 2))
	w.SetLabels(10, telemetry.FormatMPEGTS)
	_, _ = w.Write(make([]byte, 7))

	got := map[[2]string]float64{}
	for _, p := range rec.Points("mino_relay_client_sent") {
		id, _ := p.Attrs["channel_id"].(string)
		format, _ := p.Attrs["format"].(string)
		got[[2]string{id, format}] = p.Value
	}
	want := map[[2]string]float64{{"9", "hls"}: 42, {"10", "mpegts"}: 7}
	if len(got) != len(want) || got[[2]string{"9", "hls"}] != 42 || got[[2]string{"10", "mpegts"}] != 7 {
		t.Fatalf("M3 = %v, want %v", got, want)
	}
}
