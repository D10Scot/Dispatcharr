package telemetry

// Class is how SafeHandler judges the value under a log key (D9). There is
// no free-text class and no character-set class: a charset rule accepts a
// channel UUID and a bare secret alike, so every retained string is bound to
// an identity this code controls.
type Class int

const (
	// ClassDrop is the zero value: a key with no rule, and a key deliberately
	// classed `drop` (client ids, user agents, addresses, paths, names).
	ClassDrop Class = iota
	// ClassInt accepts slog.KindInt64 and KindUint64.
	ClassInt
	// ClassBool accepts slog.KindBool.
	ClassBool
	// ClassDuration accepts slog.KindDuration.
	ClassDuration
	// ClassEnum accepts a string equal to a member of Rule.Enum.
	ClassEnum
	// ClassProfileKey accepts mpegts|fmp4|hls with an optional :p<positive int64>.
	ClassProfileKey
	// ClassChannel accepts a channel UUID and emits channel_id, the numeric id.
	ClassChannel
	// ClassError accepts an error and emits <key>.type, the %T of the
	// innermost error. Its text is never exported.
	ClassError
	// ClassType accepts the %T of an error (pkg.Type) a call site computed
	// itself, such as the OTel error handler's error.type.
	ClassType
)

// Rule is one key's classification.
type Rule struct {
	Class Class
	// Enum is the closed set a ClassEnum value must equal.
	Enum []string
}

// Rules is the classification table. Keys are matched by the leaf key, under
// whatever group path the record reached them by.
type Rules struct {
	Keys map[string]Rule
	// Groups lists the group names (slog.Group, WithGroup) that may appear in
	// output. Anything under another group name is dropped.
	Groups map[string]bool
}

// TriggerValues are the three failover triggers (M4).
var TriggerValues = []string{"health_monitor", "max_retries_exceeded", "buffering_timeout"}

// The closed sets of the enum-classed keys below. Each is what the relay's
// own code writes under that key; anything else is dropped.
var (
	// logTriggers adds "operator", which advance.go logs for a switch an
	// admin asked for, to the three failover triggers.
	logTriggers = append(append([]string{}, TriggerValues...), "operator")
	// streamKinds are the stream_profile.kind values (control.Kind*). An
	// unserved kind arrives from the control plane, so it is not in the set
	// and is dropped from the line that names it.
	streamKinds = []string{"proxy", "redirect", "transcode"}
	// eventTypes are the relay events channel/ and httpapi/ emit.
	eventTypes = []string{
		"channel_start", "channel_stop", "channel_error", "channel_failover",
		"channel_reconnect", "channel_buffering", "stream_switch",
		"client_connect", "client_disconnect",
	}
	// reclaimCases are channel.ReclaimCase's String values.
	reclaimCases = []string{"nothing", "waited", "stopped", "declined", "unknown"}
	// reasons are the automatic HLS profile's copy-refusal reasons
	// (hls/automatic.go), the rewind store's degradation reason and the
	// control client's fixed Unavailable reasons. A reason built with a
	// status code in it is not in the set and is dropped.
	logReasons = []string{
		"field_order", "codec", "profile", "bit_depth", "keyframes", "keyframe_interval",
		"geometry", "frame_rate", "family", "level", "bitrate", "forced",
		"the writer queue is full",
		"transport failure",
	}
	videoFamilies = []string{"h264", "hevc"}
	fillKinds     = []string{"encode", "copy", "silence"}
	renditions    = []string{"video", "aac", "ac3", "eac3"}
	// drainWaits are drain.waitFor's `what` values.
	drainWaits = []string{"the channels to stop", "the rewind directory to be removed", "the relay events to flush"}
)

// variableNames is every environment variable name a relay log line names:
// the control-plane address variables (control/baseurl.go) and the ones this
// package's LoadConfig warns about. A variable NAME is not a value, and the
// set is closed, so a value logged under the key by mistake is dropped.
func variableNames() []string {
	names := []string{
		"DISPATCHARR_INTERNAL_API_BASE_URL", "DISPATCHARR_WEB_HOST",
		envLogFormat, envSamplerArg, envProtocol,
		"OTEL_EXPORTER_OTLP_TRACES_PROTOCOL", "OTEL_EXPORTER_OTLP_METRICS_PROTOCOL", "OTEL_EXPORTER_OTLP_LOGS_PROTOCOL",
		"OTEL_METRIC_EXPORT_INTERVAL", "OTEL_METRIC_EXPORT_TIMEOUT",
	}
	for _, sig := range otlpSignals {
		for _, suffix := range []string{"HEADERS", "ENDPOINT", "TIMEOUT", "CERTIFICATE", "CLIENT_CERTIFICATE", "CLIENT_KEY"} {
			names = append(names, otlpNamespace+sig+suffix)
		}
	}
	return names
}

// DefaultRules is the relay's classification table: one rule for every
// literal slog key the module's non-test code writes. logkeys_test.go re-runs
// that census over the source and fails naming any key that has no entry, so
// a new log call is classified deliberately (D9). The census is inventory;
// the enforcement is SafeHandler, which drops every key that is not here and
// every value whose kind or shape its rule does not accept.
//
// `drop` is written out for the keys that are deliberately not exported, so
// the census can tell "decided" from "forgotten": free text (stderr lines,
// probe descriptions, messages), externally supplied values (client ids,
// device paths, stream ids from ffprobe), floats (no class accepts one), a
// second channel identity, and the four fields ContextHandler adds itself
// behind SafeHandler, which a caller must never be able to supply.
var DefaultRules = Rules{
	Keys: map[string]Rule{
		// Identity.
		"channel": {Class: ClassChannel},

		// Errors: the %T of the innermost error, never its text.
		"error":      {Class: ClassError},
		"err":        {Class: ClassError},
		"error.type": {Class: ClassType},

		// Closed sets.
		"format":      {Class: ClassProfileKey},
		"key":         {Class: ClassProfileKey},
		"trigger":     {Class: ClassEnum, Enum: logTriggers},
		"kind":        {Class: ClassEnum, Enum: streamKinds},
		"type":        {Class: ClassEnum, Enum: eventTypes},
		"reclaim":     {Class: ClassEnum, Enum: reclaimCases},
		"reason":      {Class: ClassEnum, Enum: logReasons},
		"family":      {Class: ClassEnum, Enum: videoFamilies},
		"fill":        {Class: ClassEnum, Enum: fillKinds},
		"rendition":   {Class: ClassEnum, Enum: renditions},
		"for":         {Class: ClassEnum, Enum: drainWaits},
		"waiting_for": {Class: ClassEnum, Enum: drainWaits},
		"variable":    {Class: ClassEnum, Enum: variableNames()},
		"supported":   {Class: ClassEnum, Enum: []string{protocolHTTPProtobuf}},

		// Numbers: counts, ids the relay holds as integers, sizes, statuses.
		"attempt":        {Class: ClassInt},
		"attempts":       {Class: ClassInt},
		"boundary":       {Class: ClassInt},
		"bytes":          {Class: ClassInt},
		"cap":            {Class: ClassInt},
		"deaths":         {Class: ClassInt},
		"events":         {Class: ClassInt},
		"generation":     {Class: ClassInt},
		"head":           {Class: ClassInt},
		"height":         {Class: ClassInt},
		"keyframes":      {Class: ClassInt},
		"length":         {Class: ClassInt},
		"level":          {Class: ClassInt},
		"m3u_profile":    {Class: ClassInt},
		"max":            {Class: ClassInt},
		"output_profile": {Class: ClassInt},
		"profile":        {Class: ClassInt},
		"run":            {Class: ClassInt},
		"segments":       {Class: ClassInt},
		"sequence":       {Class: ClassInt},
		"skipped":        {Class: ClassInt},
		"source":         {Class: ClassInt},
		"status":         {Class: ClassInt},
		"stream":         {Class: ClassInt},
		"switches":       {Class: ClassInt},
		"target":         {Class: ClassInt},
		"width":          {Class: ClassInt},

		// Booleans.
		"automatic":              {Class: ClassBool},
		"released":               {Class: ClassBool},
		"stream_profile_present": {Class: ClassBool},
		"url_present":            {Class: ClassBool},
		"valid":                  {Class: ClassBool},

		// Durations.
		"after":              {Class: ClassDuration},
		"after_input_closed": {Class: ClassDuration},
		"analyze":            {Class: ClassDuration},
		"budget":             {Class: ClassDuration},
		"buffering_for":      {Class: ClassDuration},
		"client_grace":       {Class: ClassDuration},
		"duration":           {Class: ClassDuration},
		"elapsed":            {Class: ClassDuration},
		"grace":              {Class: ClassDuration},
		"in":                 {Class: ClassDuration},
		"inactive":           {Class: ClassDuration},
		"keyframe_interval":  {Class: ClassDuration},
		"linger":             {Class: ClassDuration},
		"retry_in":           {Class: ClassDuration},
		"stable":             {Class: ClassDuration},
		"stalled_for":        {Class: ClassDuration},
		"timeout":            {Class: ClassDuration},
		"waited":             {Class: ClassDuration},
		"within":             {Class: ClassDuration},

		// Deliberately dropped.
		"audio":             {Class: ClassDrop}, // ffprobe's stream descriptions
		"chosen":            {Class: ClassDrop}, // an ffprobe stream id
		"client":            {Class: ClassDrop}, // minted from X-Relay-Client
		"codec":             {Class: ClassDrop}, // from the source's probe
		"device":            {Class: ClassDrop}, // a device path
		"engine":            {Class: ClassDrop}, // a named type: KindAny
		"field_order":       {Class: ClassDrop}, // from the source's probe
		"frame_rate":        {Class: ClassDrop}, // a struct: KindAny
		"line":              {Class: ClassDrop}, // a stderr line
		"profile_ids":       {Class: ClassDrop}, // a slice: KindAny
		"reclaimed_channel": {Class: ClassDrop}, // a second channel identity
		"result":            {Class: ClassDrop}, // a validation message
		"speed":             {Class: ClassDrop}, // a float
		"stderr":            {Class: ClassDrop}, // stderr lines
		"threshold":         {Class: ClassDrop}, // a float
		"video":             {Class: ClassDrop}, // ffprobe's stream description
		"service.name":      {Class: ClassDrop}, // added by ContextHandler
		"mino.program":      {Class: ClassDrop}, // added by ContextHandler
		"trace_id":          {Class: ClassDrop}, // added by ContextHandler
		"span_id":           {Class: ClassDrop}, // added by ContextHandler
	},
	Groups: map[string]bool{},
}
