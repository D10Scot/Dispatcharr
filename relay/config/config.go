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
	// Django SECRET_KEY (entrypoint.sh:103, SECRET_FILE="/data/jwt"), read
	// there ONLY AS A FALLBACK -- see loadSecret's comment for why the
	// environment variable is the primary source. entrypoint.sh reads this
	// file as root before dropping privilege, so every dropped-privilege
	// program (including relay-go, under a non-root PUID/PGID) loses read
	// access to it once the drop happens; only a caller that inherits root
	// or the entrypoint's own exported environment can still get the
	// secret. This constant stays in case a caller has the file but not
	// the environment (a manual `go run`, a test).
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

// Load reads the environment and, if needed, the secret file. It returns an
// error rather than falling back to a generated secret: a relay running on a
// secret no other role shares would answer every internal call with a 403
// and nothing would say why.
func Load() (Config, error) {
	port, err := intFromEnv("DISPATCHARR_RELAY_GO_PORT", DefaultPort)
	if err != nil {
		return Config{}, err
	}

	secret, err := loadSecret()
	if err != nil {
		return Config{}, err
	}

	return Config{Port: port, Secret: secret, DevRoutes: devRoutes()}, nil
}

// loadSecret resolves the deployment's Django SECRET_KEY the way every OTHER
// supervisord program in this deployment gets it: from the DJANGO_SECRET_KEY
// environment variable. docker/entrypoint.sh:138 reads /data/jwt AS ROOT,
// strips it with `tr -d '\r\n'`, and exports DJANGO_SECRET_KEY before it execs
// supervisord -- every program supervisord starts inherits that environment.
// A program that instead opens /data/jwt itself, as this one originally did,
// is opening a file its own (dropped-privilege) process may no longer be
// able to read: under a non-root PUID/PGID, entrypoint.sh's root-owned read
// happens before the privilege drop and this process's does not (found via
// docker/tests/test-puid-pgid.sh -- relay-go BACKOFF-looped to death on
// "permission denied" reading /data/jwt). The environment value needs no
// stripping -- entrypoint.sh already applied tr -d '\r\n' before exporting
// it -- but an EMPTY value is treated as unset, not as an empty secret, so a
// misconfigured deployment falls through to the file rather than silently
// authenticating with "".
//
// The file read stays as a fallback for a caller that has the file but not
// the inherited environment (a manual `go run`, a test), and it keeps its
// own stripping: nothing guarantees a caller reaching that branch already
// applied entrypoint.sh's tr -d '\r\n'. That fallback path is reachable only
// outside supervisord -- a host `go run`, a test -- and cannot worsen a
// missing-environment misconfiguration in the deployed shape: both paths
// fail loudly, naming the cause, rather than authenticating with "".
//
// PRECEDENCE IS LOAD-BEARING, not incidental: the environment must win
// whenever it is set, because that is the value every other program in this
// deployment is authenticating with. Checking the file first would work by
// accident today, when both agree, and diverge silently the day they do not.
func loadSecret() (string, error) {
	if secret := os.Getenv("DJANGO_SECRET_KEY"); secret != "" {
		return secret, nil
	}

	path := os.Getenv("DISPATCHARR_SECRET_FILE")
	if path == "" {
		path = DefaultSecretFile
	}
	return ReadSecretFile(path)
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
