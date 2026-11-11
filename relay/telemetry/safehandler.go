package telemetry

import (
	"context"
	"fmt"
	"log/slog"
	"reflect"
)

// SafeHandler is the typed log-field allowlist of D9 for the relay. It sits in
// front of BOTH new sinks, the JSON handler and the otelslog bridge; the text
// format is untouched.
//
// The steps, in order, stopping at the first drop: resolve the value, recurse
// into groups, route an error to <key>.type, apply the key's rule, reject a
// UUID-shaped string under any key but a channel key, check the class. The
// message is the log body and is scrubbed best effort, which is no stronger
// than stdout.
type SafeHandler struct {
	inner   slog.Handler
	rules   Rules
	ids     *ChannelIDs
	dropAll bool // inside a group name that is not allowlisted
}

// NewSafeHandler wraps inner. A nil ids behaves as an empty ChannelIDs.
func NewSafeHandler(inner slog.Handler, rules Rules, ids *ChannelIDs) *SafeHandler {
	return &SafeHandler{inner: inner, rules: rules, ids: ids}
}

// Enabled reports whether the inner handler is.
func (h *SafeHandler) Enabled(ctx context.Context, l slog.Level) bool {
	return h.inner.Enabled(ctx, l)
}

// Handle cleans the record's attributes and scrubs its message.
func (h *SafeHandler) Handle(ctx context.Context, r slog.Record) error {
	out := slog.NewRecord(r.Time, r.Level, scrub(r.Message), r.PC)
	if !h.dropAll {
		r.Attrs(func(a slog.Attr) bool {
			out.AddAttrs(h.clean(a)...)
			return true
		})
	}
	return h.inner.Handle(ctx, out)
}

// WithAttrs classifies the attributes when they are attached, so the handler
// stores the cleaned ones. That covers a With from any package.
func (h *SafeHandler) WithAttrs(attrs []slog.Attr) slog.Handler {
	if h.dropAll {
		return h
	}
	var cleaned []slog.Attr
	for _, a := range attrs {
		cleaned = append(cleaned, h.clean(a)...)
	}
	next := *h
	next.inner = h.inner.WithAttrs(cleaned)
	return &next
}

// WithGroup opens a group only if its name is allowlisted. Anything attached
// under another name is dropped, because a group name is a key and a computed
// one could carry a secret.
func (h *SafeHandler) WithGroup(name string) slog.Handler {
	if name == "" {
		return h
	}
	next := *h
	if h.dropAll || !h.rules.Groups[name] {
		next.dropAll = true
		return &next
	}
	next.inner = h.inner.WithGroup(name)
	return &next
}

func (h *SafeHandler) clean(a slog.Attr) []slog.Attr {
	v := a.Value.Resolve()
	switch v.Kind() {
	case slog.KindGroup:
		members := v.Group()
		if len(members) == 0 {
			return nil
		}
		if a.Key == "" { // an inline group
			var out []slog.Attr
			for _, m := range members {
				out = append(out, h.clean(m)...)
			}
			return out
		}
		if !h.rules.Groups[a.Key] {
			return nil
		}
		var kept []slog.Attr
		for _, m := range members {
			kept = append(kept, h.clean(m)...)
		}
		if len(kept) == 0 {
			return nil
		}
		return []slog.Attr{{Key: a.Key, Value: slog.GroupValue(kept...)}}
	case slog.KindAny:
		err, isErr := v.Any().(error)
		if !isErr || err == nil {
			return nil // structs, maps, slices and pointers have no rule
		}
		if h.rules.Keys[a.Key].Class != ClassError {
			return nil
		}
		return []slog.Attr{slog.String(a.Key+".type", innermostType(err))}
	case slog.KindString:
		return h.one(a.Key, val{k: vStr, s: v.String()})
	case slog.KindInt64:
		return h.one(a.Key, val{k: vInt, i: v.Int64()})
	case slog.KindUint64:
		u := v.Uint64()
		if u > 1<<63-1 {
			return nil
		}
		return h.one(a.Key, val{k: vInt, i: int64(u)})
	case slog.KindBool:
		return h.one(a.Key, val{k: vBool, b: v.Bool()})
	case slog.KindDuration:
		return h.one(a.Key, val{k: vDur, d: v.Duration()})
	default: // KindFloat64, KindTime and anything added later have no class
		return nil
	}
}

func (h *SafeHandler) one(key string, v val) []slog.Attr {
	k, out, ok := h.rules.classify(key, v, h.ids)
	if !ok {
		return nil
	}
	switch out.k {
	case vInt:
		return []slog.Attr{slog.Int64(k, out.i)}
	case vBool:
		return []slog.Attr{slog.Bool(k, out.b)}
	case vDur:
		return []slog.Attr{slog.Duration(k, out.d)}
	default:
		return []slog.Attr{slog.String(k, out.s)}
	}
}

// maxUnwrap bounds innermostType's walk, so a cyclic Unwrap chain ends.
const maxUnwrap = 64

// innermostType is the %T of the innermost error errors.Unwrap reaches. An
// error's text is never exported: a *url.Error prints the whole URL.
//
// It is total. A typed-nil error (a nil *url.Error in a non-nil error
// interface) is not unwrapped, because its Unwrap would dereference nil; the
// walk stops after maxUnwrap hops; and an Unwrap that panics anyway ends the
// walk at the last error reached. A logging or span call must never be what
// takes the relay down.
func innermostType(err error) (typ string) {
	// credential-logging: ok - %T prints the type name only, never the error text
	typ = fmt.Sprintf("%T", err)
	// On a panic the named result already holds the last type reached.
	defer func() { _ = recover() }()
	for range maxUnwrap {
		if isNilPointer(err) {
			break
		}
		u, ok := err.(interface{ Unwrap() error }) //nolint:errorlint // walking the chain by hand is the point
		if !ok {
			break
		}
		next := u.Unwrap()
		if next == nil {
			break
		}
		err = next
		// credential-logging: ok - %T prints the type name only, never the error text
		typ = fmt.Sprintf("%T", err)
	}
	return typ
}

// isNilPointer reports whether err holds a nil pointer of some error type.
func isNilPointer(err error) bool {
	v := reflect.ValueOf(err)
	return v.Kind() == reflect.Pointer && v.IsNil()
}
