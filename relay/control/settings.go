package control

import (
	"encoding/json"
	"fmt"
	"time"
)

// Settings is the next-source answer's proxy_settings object, held as raw JSON
// keyed by name rather than as a struct.
//
// A MAP, NOT A STRUCT, and the reason is the whole point of Amendment A1.4.
// Django sends EFFECTIVE settings: the stored CoreSettings group's seven
// snake_case keys, plus every one of apps/proxy/config.py's TSConfig
// class-attribute defaults under its own SCREAMING_CASE name. The relay
// therefore holds no default of its own and there is no second copy to drift.
//
// A struct would reintroduce exactly that. An absent key unmarshals into a
// struct field as the zero value, silently -- a chunk size of 0 deadlocks the
// ring and a retention of 0 empties it -- and only the fields somebody
// remembered to make a pointer would say so. Every accessor below FAILS on an
// absent key instead, for every key, including ones a later PR starts reading.
type Settings map[string]json.RawMessage

// ErrSettingAbsent names a key the control plane did not send.
type ErrSettingAbsent struct{ Key string }

func (e *ErrSettingAbsent) Error() string {
	return fmt.Sprintf("proxy_settings carries no %q: Django sends effective settings, so an "+
		"absent key means the control plane is older than this relay", e.Key)
}

// Int reads an integer setting.
func (s Settings) Int(key string) (int, error) {
	raw, ok := s[key]
	if !ok {
		return 0, &ErrSettingAbsent{Key: key}
	}
	// Through float64: the serializer declares several of these as FloatField,
	// so 15 arrives as 15.0 and json.Unmarshal into an int refuses it.
	var value float64
	if err := json.Unmarshal(raw, &value); err != nil {
		return 0, fmt.Errorf("proxy_settings[%q] is not a number: %w", key, err) // credential-logging: ok - an encoding/json error over a settings value, which is a number or a short string
	}
	return int(value), nil
}

// Float reads a floating-point setting.
func (s Settings) Float(key string) (float64, error) {
	raw, ok := s[key]
	if !ok {
		return 0, &ErrSettingAbsent{Key: key}
	}
	var value float64
	if err := json.Unmarshal(raw, &value); err != nil {
		return 0, fmt.Errorf("proxy_settings[%q] is not a number: %w", key, err) // credential-logging: ok - an encoding/json error over a settings value
	}
	return value, nil
}

// Seconds reads a setting expressed in seconds as a duration. Fractional
// values are honoured: KEEPALIVE_INTERVAL is 0.5.
func (s Settings) Seconds(key string) (time.Duration, error) {
	value, err := s.Float(key)
	if err != nil {
		return 0, err
	}
	return time.Duration(value * float64(time.Second)), nil
}

// String reads a string setting.
func (s Settings) String(key string) (string, error) {
	raw, ok := s[key]
	if !ok {
		return "", &ErrSettingAbsent{Key: key}
	}
	var value string
	if err := json.Unmarshal(raw, &value); err != nil {
		return "", fmt.Errorf("proxy_settings[%q] is not a string: %w", key, err) // credential-logging: ok - an encoding/json error over a settings value; DEFAULT_USER_AGENT is the only string and is not a credential
	}
	return value, nil
}
