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

// DefaultRules is the table the relay starts with. O4's census test fails when
// a literal slog key in the module has no entry, and the table grows there;
// until then it carries only the keys the spec names.
var DefaultRules = Rules{
	Keys: map[string]Rule{
		"channel": {Class: ClassChannel},
		"format":  {Class: ClassProfileKey},
		"trigger": {Class: ClassEnum, Enum: TriggerValues},
		"error":   {Class: ClassError},
		"err":     {Class: ClassError},
	},
	Groups: map[string]bool{},
}
