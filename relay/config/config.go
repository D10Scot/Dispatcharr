// Package config turns the deployment's environment into the handful of
// values the relay needs at startup. It is deliberately small and has no
// dependencies on the rest of the module: everything here is read once, in
// main, before anything else exists.
package config

import (
	"errors"
	"fmt"
	"os"
	"strconv"
	"strings"
)

const (
	// DefaultPort is the port the Go relay binds. Spec § Stage 2c: 5658,
	// confirmed free against the tree (nothing else in the repo names it).
	DefaultPort = 5658

	// DefaultSecretFile is where docker/entrypoint.sh puts the deployment's
	// Django SECRET_KEY (entrypoint.sh:103, SECRET_FILE="/data/jwt"). Every
	// role reads the same file from the same mounted volume; the api/all role
	// is the only one that creates it (entrypoint.sh:105-137), and the
	// entrypoint blocks until it exists before exec'ing supervisord, so by
	// the time this process starts the file is there.
	//
	// #nosec G101 -- a filesystem path, not a credential. gosec matches on
	// the IDENTIFIER containing "Secret"; the value is "/data/jwt".
	DefaultSecretFile = "/data/jwt"
)

// ErrEmptySecret is returned when the secret file exists but holds nothing
// usable. A named error rather than a message, so callers can test for the
// condition instead of matching a substring.
var ErrEmptySecret = errors.New("secret file is empty")

// Config is everything main needs. Every field is resolved before any
// goroutine starts, so nothing here is read concurrently.
type Config struct {
	// Port is the TCP port to bind, from DISPATCHARR_RELAY_GO_PORT.
	Port int

	// Secret is the deployment's Django SECRET_KEY, the HMAC key for every
	// token in package control.
	Secret string

	// DevRoutes gates every route that is not /healthz or /readyz. This PR
	// ships no such route beyond a stub, and nginx does not route to this
	// process until stage 2d, so the flag is the second of two reasons this
	// PR is inert in a production deployment.
	DevRoutes bool
}

// Load reads the environment and the secret file. It returns an error rather
// than falling back to a generated secret: a relay running on a secret no
// other role shares would answer every internal call with a 403 and nothing
// would say why.
func Load() (Config, error) {
	port, err := intFromEnv("DISPATCHARR_RELAY_GO_PORT", DefaultPort)
	if err != nil {
		return Config{}, err
	}

	path := os.Getenv("DISPATCHARR_SECRET_FILE")
	if path == "" {
		path = DefaultSecretFile
	}
	secret, err := ReadSecretFile(path)
	if err != nil {
		return Config{}, err
	}

	return Config{Port: port, Secret: secret, DevRoutes: devRoutes()}, nil
}

// ReadSecretFile reads path and strips exactly what docker/entrypoint.sh:138
// strips: `tr -d '\r\n'` deletes every CR and every LF anywhere in the file
// and nothing else. strings.TrimSpace is NOT equivalent -- it also removes
// spaces and tabs, and only at the ends -- and the difference is a different
// HMAC key, which surfaces as a 403 on every internal call with no error
// naming the cause.
func ReadSecretFile(path string) (string, error) {
	// #nosec G304,G703 -- `path` is deployment configuration
	// (DISPATCHARR_SECRET_FILE, or the /data/jwt default), never client
	// input; reading an operator-named file is this function's whole job.
	// BOTH rule ids are needed: silencing G304 alone leaves gosec's
	// taint-analysis rule G703 firing on the same line, and G703 only
	// becomes visible once G304 is suppressed — found by running the
	// linter, not by reading it.
	raw, err := os.ReadFile(path)
	if err != nil {
		return "", fmt.Errorf("reading secret file %s: %w", path, err)
	}
	secret := strings.NewReplacer("\r", "", "\n", "").Replace(string(raw))
	if secret == "" {
		return "", fmt.Errorf("%s: %w", path, ErrEmptySecret)
	}
	return secret, nil
}

// devRoutes reports whether routes beyond the health endpoints are served.
// DISPATCHARR_RELAY_GO_DEV_ROUTES wins when set, so an operator can turn the
// routes off in a dev container as well as on elsewhere; otherwise it follows
// DISPATCHARR_ENV, which is how the rest of the deployment decides dev-ness
// (docker/entrypoint.sh:491 selects the all-dev supervisord rung from it).
func devRoutes() bool {
	if raw := os.Getenv("DISPATCHARR_RELAY_GO_DEV_ROUTES"); raw != "" {
		enabled, err := strconv.ParseBool(raw)
		if err != nil {
			return false
		}
		return enabled
	}
	return os.Getenv("DISPATCHARR_ENV") == "dev"
}

func intFromEnv(name string, fallback int) (int, error) {
	raw := os.Getenv(name)
	if raw == "" {
		return fallback, nil
	}
	value, err := strconv.Atoi(raw)
	if err != nil {
		return 0, fmt.Errorf("%s=%q is not an integer", name, raw)
	}
	if value < 1 || value > 65535 {
		return 0, fmt.Errorf("%s=%d is not a TCP port", name, value)
	}
	return value, nil
}
