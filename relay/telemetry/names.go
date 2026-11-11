package telemetry

// Span names: a closed set (D9). The redacting exporter replaces any other
// name with the instrumentation scope's.
const (
	SpanTune         = "relay.tune"
	SpanAuthorize    = "relay.authorize"
	SpanNextSource   = "relay.next_source"
	SpanFailover     = "relay.failover"
	SpanStreamSwitch = "relay.stream_switch"
)

// Span attribute keys (§ Span catalogue). Nothing else is exported.
const (
	AttrChannelID    = "mino.channel_id"
	AttrOutputFormat = "mino.output_format"
	AttrTuneJoined   = "mino.tune.joined"
	AttrOutcome      = "mino.outcome"
	AttrReason       = "mino.next_source.reason"
	AttrTrigger      = "mino.failover.trigger"
	AttrRoute        = "http.route"
	AttrStatusCode   = "http.response.status_code"
	attrExcType      = "exception.type"
)

// mino.outcome values. Each span uses a subset; the exporter accepts the union.
const (
	OutcomeStreaming = "streaming"
	OutcomeRedirect  = "redirect"
	OutcomeRefused   = "refused"
	OutcomeFailed    = "failed"
	OutcomeDraining  = "draining"
	OutcomeAbandoned = "abandoned"

	OutcomeAllowed     = "allowed"
	OutcomeDenied      = "denied"
	OutcomeUnavailable = "unavailable"

	OutcomeSource   = "source"
	OutcomeNoSource = "no_source"
	OutcomeBlocked  = "blocked"

	OutcomeSwitched    = "switched"
	OutcomeNoAlternate = "no_alternate"
	OutcomeUnresolved  = "unresolved"
	OutcomeSameURL     = "same_url"
	OutcomeNoResolver  = "no_resolver"

	OutcomeApplied   = "applied"
	OutcomeUnchanged = "unchanged"
)

// mino.next_source.reason values.
const (
	ReasonTune     = "tune"
	ReasonFailover = "failover"
	ReasonResume   = "resume"
)

// Trigger values (M4 and relay.failover).
const (
	TriggerHealthMonitor    = "health_monitor"
	TriggerMaxRetries       = "max_retries_exceeded"
	TriggerBufferingTimeout = "buffering_timeout"
)

// Output formats (M2, M3, relay.tune).
const (
	FormatMPEGTS = "mpegts"
	FormatFMP4   = "fmp4"
	FormatHLS    = "hls"
)

// HeaderRelayTraceparent carries the authorize hop's trace context across
// nginx (D11). Extract it only from a trusted request.
const HeaderRelayTraceparent = "X-Relay-Traceparent"

var (
	spanNames = setOf(SpanTune, SpanAuthorize, SpanNextSource, SpanFailover, SpanStreamSwitch)
	outcomes  = setOf(
		OutcomeStreaming, OutcomeRedirect, OutcomeRefused, OutcomeFailed, OutcomeDraining, OutcomeAbandoned,
		OutcomeAllowed, OutcomeDenied, OutcomeUnavailable,
		OutcomeSource, OutcomeNoSource, OutcomeBlocked,
		OutcomeSwitched, OutcomeNoAlternate, OutcomeUnresolved, OutcomeSameURL, OutcomeNoResolver,
		OutcomeApplied, OutcomeUnchanged,
	)
	failoverOutcomes = setOf(OutcomeSwitched, OutcomeNoAlternate, OutcomeUnresolved, OutcomeSameURL, OutcomeNoResolver)
	reasons          = setOf(ReasonTune, ReasonFailover, ReasonResume)
	triggers         = setOf(TriggerHealthMonitor, TriggerMaxRetries, TriggerBufferingTimeout)
	formats          = setOf(FormatMPEGTS, FormatFMP4, FormatHLS)
	kinds            = setOf("source", "output", "fmp4", "hls")
	channelStates    = setOf("initializing", "connecting", "waiting_for_clients", "active", "buffering", "error", "stopping", "stopped")
)

func setOf(vs ...string) map[string]struct{} {
	m := make(map[string]struct{}, len(vs))
	for _, v := range vs {
		m[v] = struct{}{}
	}
	return m
}

func in(set map[string]struct{}, v string) bool { _, ok := set[v]; return ok }
