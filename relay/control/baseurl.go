package control

import (
	"fmt"
	"net/url"
	"os"
	"regexp"
	"strings"
)

// asError exists so every failure path reads the same and none of them
// accidentally returns a nil *ErrNotConfigured in a non-nil error interface --
// the classic Go typed-nil trap, which would make errors.As succeed on a
// success path.
func asError(e *ErrNotConfigured) error { return e }

// ErrNotConfigured is the Go counterpart of Django's ImproperlyConfigured on
// this path. A tune that cannot resolve where Django answers fails loudly;
// nothing falls back to a guess, because a relay talking to the wrong address
// answers every internal call with a 403 and nothing says why.
type ErrNotConfigured struct {
	// Variable is the environment variable responsible, or the empty string
	// when the deployment shape supplied the address with no variable.
	Variable string
	Reason   string
}

func (e *ErrNotConfigured) Error() string {
	subject := e.Variable
	if subject == "" {
		subject = "the control-plane URL"
	}
	return subject + " " + e.Reason
}

// hostValidationRe is django.http.request.host_validation_re, transcribed from
// the Django in this deployment's own image -- see this PR's Task for the
// command. It is what HttpRequest.get_host() applies BEFORE ALLOWED_HOSTS, so
// a host it rejects (an underscore anywhere in it, notably) reaches Django as
// an opaque 400 with nothing naming the cause. Checking it here blames the
// variable instead.
var hostValidationRe = regexp.MustCompile(`^([a-z0-9.-]+|\[[a-f0-9]*:[a-f0-9.:]+\])(?::([0-9]+))?$`)

// BaseURL resolves where Django answers for this deployment shape: the D9
// four-branch formula, in the order apps/proxy/internal_base_url.py's
// resolve_base_url applies it -- explicit override, then modular by service
// name, then dev, then AIO through nginx on DISPATCHARR_PORT.
//
// Resolved on every call rather than at startup, which is parity and not
// laziness: Python resolves inside next_source() and lets ImproperlyConfigured
// propagate, so a misconfigured deployment fails visibly on the first tune
// while /healthz keeps answering honestly. Resolving at startup would refuse
// to boot a relay nobody has tuned yet.
func BaseURL() (string, error) {
	if explicit := os.Getenv("DISPATCHARR_INTERNAL_API_BASE_URL"); explicit != "" {
		return validate(strings.TrimRight(explicit, "/"), "DISPATCHARR_INTERNAL_API_BASE_URL")
	}
	switch strings.ToLower(envOr("DISPATCHARR_ENV", "aio")) {
	case "modular":
		host := envOr("DISPATCHARR_WEB_HOST", "web")
		port := envOr("DISPATCHARR_PORT", "9191")
		return validate(fmt.Sprintf("http://%s:%s", host, port), "DISPATCHARR_WEB_HOST")
	case "dev":
		// Hardcoded, not read from DISPATCHARR_PORT: in dev the port that
		// answers is uWSGI's or runserver's own, and DISPATCHARR_PORT names
		// vite's (CLAUDE.md, Commands).
		return validate("http://127.0.0.1:5656", "")
	default:
		return validate("http://127.0.0.1:"+envOr("DISPATCHARR_PORT", "9191"), "")
	}
}

// envOr falls back only when the variable is ABSENT, never when it is set to
// the empty string, because that is what Python's os.environ.get(var, default)
// does and the difference is a silent default.
//
// DISPATCHARR_WEB_HOST= in a compose env file is the case: Python builds
// "http://:9191", validated_base_url finds no domain and raises
// ImproperlyConfigured naming the variable, so the deployment fails visibly on
// the first tune. An os.Getenv-based fallback would quietly resolve
// http://web:9191 instead and talk to whatever answers there -- the
// silent-default shape Global Constraint 13 forbids, in the one place a
// misconfiguration is most likely to come from a half-filled env file.
func envOr(name, fallback string) string {
	if value, set := os.LookupEnv(name); set {
		return value
	}
	return fallback
}

func validate(raw, variable string) (string, error) {
	parsed, err := url.Parse(raw)
	if err != nil {
		return "", asError(&ErrNotConfigured{Variable: variable, Reason: "could not be parsed as a URL."})
	}
	if parsed.Scheme != "http" && parsed.Scheme != "https" {
		return "", asError(&ErrNotConfigured{
			Variable: variable,
			Reason: "is not an http(s) URL: a scheme-less or malformed value " +
				"has no host this client can send.",
		})
	}
	// url.Parse has already separated userinfo into parsed.User, so
	// parsed.Host never contains an "@" and needs no stripping. Python's
	// equivalent DOES strip, because urlsplit().netloc keeps the userinfo --
	// a difference between the two standard libraries, not between the two
	// behaviours. An earlier draft ported the strip anyway; deleting it
	// changed no test, including the one whose name claimed to pin it, which
	// is what dead code with a hollow test looks like.
	if !hostValidationRe.MatchString(strings.ToLower(parsed.Host)) {
		return "", asError(&ErrNotConfigured{
			Variable: variable,
			Reason:   "must be an http(s) URL whose host is letters, digits, dots and hyphens.",
		})
	}
	return raw, nil
}
