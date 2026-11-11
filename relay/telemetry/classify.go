package telemetry

import (
	"regexp"
	"slices"
	"strconv"
	"strings"
	"time"
)

type vkind int8

const (
	vInt vkind = iota + 1
	vBool
	vDur
	vStr
)

// val is a log value reduced to the four shapes any class accepts.
type val struct {
	k vkind
	i int64
	d time.Duration
	b bool
	s string
}

var (
	profileKeyPattern = regexp.MustCompile(`^(mpegts|fmp4|hls)(:p([1-9][0-9]{0,18}))?$`)
	uuidExact         = regexp.MustCompile(`(?i)^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$`)
	digits            = regexp.MustCompile(`^[0-9]{1,19}$`)
	// typeNamePattern is the shape of a %T: package-qualified, pointer and
	// generic punctuation. It is applied to a string this code produced.
	typeNamePattern = regexp.MustCompile(`^[*\w.\[\]/,-]{1,256}$`)
)

// validProfileKey is the domain output.FormatKey can produce for the ids the
// relay accepts: a closed prefix and a positive int64 with no leading zero.
func validProfileKey(s string) bool {
	m := profileKeyPattern.FindStringSubmatch(s)
	if m == nil {
		return false
	}
	if m[3] == "" {
		return true
	}
	n, err := strconv.ParseInt(m[3], 10, 64)
	return err == nil && n > 0
}

// classify applies D9's steps 5 and 6 to one leaf: the key's rule, UUID
// rejection under every key but a channel key, then the class check. It
// returns the key to emit (a channel key is emitted as channel_id) and the
// value, or ok=false to drop.
func (r Rules) classify(key string, v val, ids *ChannelIDs) (outKey string, out val, ok bool) {
	rule, known := r.Keys[key]
	if !known {
		return "", val{}, false
	}
	if v.k == vStr && rule.Class != ClassChannel && uuidPattern.MatchString(v.s) {
		return "", val{}, false
	}
	switch rule.Class {
	case ClassInt:
		if v.k == vInt {
			return key, v, true
		}
	case ClassBool:
		if v.k == vBool {
			return key, v, true
		}
	case ClassDuration:
		if v.k == vDur {
			return key, v, true
		}
	case ClassEnum:
		if v.k == vStr && slices.Contains(rule.Enum, v.s) {
			return key, v, true
		}
	case ClassProfileKey:
		if v.k == vStr && validProfileKey(v.s) {
			return key, v, true
		}
	case ClassChannel:
		if v.k == vStr && uuidExact.MatchString(v.s) {
			id := 0
			if ids != nil {
				id = ids.Get(v.s)
			}
			return "channel_id", val{k: vStr, s: strconv.Itoa(id)}, true
		}
	case ClassDrop, ClassError:
		// ClassError is reached only through the error route.
	}
	return "", val{}, false
}

// classifyExported judges an attribute the exporter finds on a record that
// has ALREADY passed (or bypassed) SafeHandler, so its keys may be the
// derived ones SafeHandler emits: channel_id and <errorkey>.type. A key
// SafeHandler would have dropped is dropped here too.
func (r Rules) classifyExported(key string, v val) bool {
	if key == "channel_id" {
		return v.k == vStr && digits.MatchString(v.s)
	}
	if base, ok := strings.CutSuffix(key, ".type"); ok {
		if rule, known := r.Keys[base]; known && rule.Class == ClassError {
			return v.k == vStr && typeNamePattern.MatchString(v.s) && !uuidPattern.MatchString(v.s)
		}
	}
	rule, known := r.Keys[key]
	if !known || rule.Class == ClassChannel {
		return false
	}
	if rule.Class == ClassDuration && v.k == vInt {
		v = val{k: vDur, d: time.Duration(v.i)}
	}
	_, _, ok := r.classify(key, v, nil)
	return ok
}
