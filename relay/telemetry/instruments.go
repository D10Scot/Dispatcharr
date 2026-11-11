package telemetry

import (
	"context"
	"strconv"

	"go.opentelemetry.io/otel/attribute"
	"go.opentelemetry.io/otel/metric"
)

// The Go rows of the metric catalogue (observability spec § Metric catalogue).
// Adding, removing or relabelling an instrument is an amendment to the spec
// (D14), and TestExpositionMatchesTheCatalogue compares /metrics to CatalogueGo.
const (
	nameChannels      = "mino_relay_channels"
	nameClients       = "mino_relay_clients"
	nameClientSent    = "mino_relay_client_sent"
	nameFailovers     = "mino_relay_failovers"
	nameHLSSessions   = "mino_relay_hls_sessions"
	nameRewindUsage   = "mino_relay_rewind_disk_usage"
	nameRewindLimit   = "mino_relay_rewind_disk_limit"
	nameProcessCPU    = "mino_relay_process_cpu"
	nameProcessMemory = "mino_relay_process_memory_rss"
)

func (t *Telemetry) instruments(m metric.Meter) error {
	chGauge, err := m.Int64ObservableGauge(nameChannels, metric.WithUnit("{channel}"))
	if err != nil {
		return err
	}
	clGauge, err := m.Int64ObservableGauge(nameClients, metric.WithUnit("{client}"))
	if err != nil {
		return err
	}
	if t.clientSent, err = m.Int64Counter(nameClientSent, metric.WithUnit("By")); err != nil {
		return err
	}
	if t.failovers, err = m.Int64Counter(nameFailovers, metric.WithUnit("{failover}")); err != nil {
		return err
	}
	hlsGauge, err := m.Int64ObservableGauge(nameHLSSessions, metric.WithUnit("{session}"))
	if err != nil {
		return err
	}
	useGauge, err := m.Int64ObservableGauge(nameRewindUsage, metric.WithUnit("By"))
	if err != nil {
		return err
	}
	limGauge, err := m.Int64ObservableGauge(nameRewindLimit, metric.WithUnit("By"))
	if err != nil {
		return err
	}
	cpuCounter, err := m.Float64ObservableCounter(nameProcessCPU, metric.WithUnit("s"))
	if err != nil {
		return err
	}
	rssGauge, err := m.Int64ObservableGauge(nameProcessMemory, metric.WithUnit("By"))
	if err != nil {
		return err
	}

	_, err = m.RegisterCallback(func(_ context.Context, o metric.Observer) error {
		if f := t.channels.Load(); f != nil {
			for state, n := range (*f)() {
				if in(channelStates, state) {
					o.ObserveInt64(chGauge, int64(n), metric.WithAttributes(attribute.String("state", state)))
				}
			}
		}
		if f := t.clients.Load(); f != nil {
			for _, c := range (*f)() {
				if !in(formats, c.Format) {
					continue
				}
				o.ObserveInt64(clGauge, int64(c.N), metric.WithAttributes(
					attribute.String("channel_id", strconv.Itoa(c.ChannelID)),
					attribute.String("format", c.Format),
					attribute.String("profile_id", strconv.Itoa(c.ProfileID)),
				))
			}
		}
		if f := t.hls.Load(); f != nil {
			o.ObserveInt64(hlsGauge, int64((*f)()))
		}
		if f := t.rewindUse.Load(); f != nil {
			o.ObserveInt64(useGauge, (*f)())
		}
		if f := t.rewindCap.Load(); f != nil {
			// Not observed while the cap is unset (math.MaxInt64).
			if limit, ok := (*f)(); ok {
				o.ObserveInt64(limGauge, limit)
			}
		}
		for _, s := range t.procs.Collect() {
			if !in(kinds, s.Labels.Kind) {
				continue
			}
			attrs := metric.WithAttributes(
				attribute.String("channel_id", strconv.Itoa(s.Labels.ChannelID)),
				attribute.String("kind", s.Labels.Kind),
				attribute.String("profile_id", strconv.Itoa(s.Labels.ProfileID)),
			)
			o.ObserveFloat64(cpuCounter, s.CPUSeconds, attrs)
			if s.Live {
				o.ObserveInt64(rssGauge, s.RSSBytes, attrs)
			}
		}
		return nil
	}, chGauge, clGauge, hlsGauge, useGauge, limGauge, cpuCounter, rssGauge)
	return err
}

// ObserveChannels registers the source of M1: channel counts by state.
func (t *Telemetry) ObserveChannels(f func() map[string]int) { t.channels.Store(&f) }

// ObserveClients registers the source of M2.
func (t *Telemetry) ObserveClients(f func() []ClientCount) { t.clients.Store(&f) }

// ObserveHLSSessions registers the source of M5.
func (t *Telemetry) ObserveHLSSessions(f func() int) { t.hls.Store(&f) }

// ObserveRewind registers the sources of M6 and M7. limit reports false while
// the cap is unset, and then M7 is not observed.
func (t *Telemetry) ObserveRewind(usage func() int64, limit func() (int64, bool)) {
	t.rewindUse.Store(&usage)
	t.rewindCap.Store(&limit)
}

// ClientSent adds n to M3. A format outside the closed set is not recorded.
func (t *Telemetry) ClientSent(ctx context.Context, channelID int, format string, n int) {
	if n <= 0 || !in(formats, format) {
		return
	}
	t.clientSent.Add(ctx, int64(n), metric.WithAttributes(
		attribute.String("channel_id", strconv.Itoa(channelID)),
		attribute.String("format", format),
	))
}

// Failover adds one to M4. A trigger or outcome outside its closed set is not recorded.
func (t *Telemetry) Failover(ctx context.Context, channelID int, trigger, outcome string) {
	if !in(triggers, trigger) || !in(failoverOutcomes, outcome) {
		return
	}
	t.failovers.Add(ctx, 1, metric.WithAttributes(
		attribute.String("channel_id", strconv.Itoa(channelID)),
		attribute.String("trigger", trigger),
		attribute.String("outcome", outcome),
	))
}

// CatalogueRow is one Go row of the metric catalogue as /metrics renders it.
type CatalogueRow struct {
	Family string // the Prometheus family name
	Type   string // gauge or counter
	Labels []string
}

// CatalogueGo is the literal copy of the catalogue's Go rows that
// TestExpositionMatchesTheCatalogue compares with a scrape (D14).
var CatalogueGo = []CatalogueRow{
	{"mino_relay_channels", "gauge", []string{"state"}},
	{"mino_relay_clients", "gauge", []string{"channel_id", "format", "profile_id"}},
	{"mino_relay_client_sent_bytes_total", "counter", []string{"channel_id", "format"}},
	{"mino_relay_failovers_total", "counter", []string{"channel_id", "outcome", "trigger"}},
	{"mino_relay_hls_sessions", "gauge", nil},
	{"mino_relay_rewind_disk_usage_bytes", "gauge", nil},
	{"mino_relay_rewind_disk_limit_bytes", "gauge", nil},
	{"mino_relay_process_cpu_seconds_total", "counter", []string{"channel_id", "kind", "profile_id"}},
	{"mino_relay_process_memory_rss_bytes", "gauge", []string{"channel_id", "kind", "profile_id"}},
}
