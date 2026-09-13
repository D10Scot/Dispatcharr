package control

import (
	"errors"
	"os"
	"strings"
	"testing"
)

func TestBaseURLFollowsTheFourBranches(t *testing.T) {
	for _, tc := range []struct {
		name string
		env  map[string]string
		want string
	}{
		{
			// A value no branch could produce by accident: not 5656, not
			// 9191, not the default host (hollow shape 2).
			"the explicit override wins, trailing slash stripped",
			map[string]string{
				"DISPATCHARR_INTERNAL_API_BASE_URL": "http://control.invalid:7777/",
				"DISPATCHARR_ENV":                   "dev",
			},
			"http://control.invalid:7777",
		},
		{
			"modular names the service and DISPATCHARR_PORT",
			map[string]string{"DISPATCHARR_ENV": "modular", "DISPATCHARR_PORT": "8888"},
			"http://web:8888",
		},
		{
			"modular honours DISPATCHARR_WEB_HOST",
			map[string]string{"DISPATCHARR_ENV": "modular", "DISPATCHARR_WEB_HOST": "api-host"},
			"http://api-host:9191",
		},
		{
			// Hardcoded, not read from DISPATCHARR_PORT, which names vite's
			// port in dev. Setting it to something else is what shows the
			// branch really ignores it.
			"dev names the application port and ignores DISPATCHARR_PORT",
			map[string]string{"DISPATCHARR_ENV": "dev", "DISPATCHARR_PORT": "8888"},
			"http://127.0.0.1:5656",
		},
		{
			"aio goes through nginx on DISPATCHARR_PORT",
			map[string]string{"DISPATCHARR_ENV": "aio", "DISPATCHARR_PORT": "8888"},
			"http://127.0.0.1:8888",
		},
		{
			"an unset environment is aio",
			map[string]string{},
			"http://127.0.0.1:9191",
		},
	} {
		t.Run(tc.name, func(t *testing.T) {
			// UNSET, not set-to-empty. envOr falls back only on an
			// absent variable, so t.Setenv(name, "") for an unlisted key
			// would test the opposite of the intended branch -- and a table
			// written that way cannot detect the divergence at all, because
			// it depends on it. t.Setenv first so the value is restored on
			// cleanup, then Unsetenv for the keys this case does not supply.
			for _, name := range []string{
				"DISPATCHARR_INTERNAL_API_BASE_URL", "DISPATCHARR_ENV",
				"DISPATCHARR_WEB_HOST", "DISPATCHARR_PORT",
			} {
				t.Setenv(name, "sentinel")
				if value, supplied := tc.env[name]; supplied {
					t.Setenv(name, value)
				} else if err := os.Unsetenv(name); err != nil {
					t.Fatalf("unsetting %s: %v", name, err)
				}
			}
			got, err := BaseURL()
			if err != nil {
				t.Fatalf("BaseURL: %v", err)
			}
			if got != tc.want {
				t.Fatalf("BaseURL = %q, want %q", got, tc.want)
			}
		})
	}
}

// An underscore in a host is what Django's own host_validation_re rejects,
// BEFORE ALLOWED_HOSTS is consulted, so such a URL reaches Django as an opaque
// 400 with nothing naming the cause. Failing here blames the variable instead.
func TestBaseURLRejectsWhatDjangoWouldRefuseAsAHost(t *testing.T) {
	for _, tc := range []struct{ name, value string }{
		{"an underscore in the host", "http://web_host:9191"},
		{"no scheme at all", "web:9191"},
		{"an unsupported scheme", "ftp://web:9191"},
	} {
		t.Run(tc.name, func(t *testing.T) {
			t.Setenv("DISPATCHARR_INTERNAL_API_BASE_URL", tc.value)
			_, err := BaseURL()
			var misconfigured *ErrNotConfigured
			if !errors.As(err, &misconfigured) {
				t.Fatalf("BaseURL(%q) error = %v, want an *ErrNotConfigured", tc.value, err)
			}
			if misconfigured.Variable != "DISPATCHARR_INTERNAL_API_BASE_URL" {
				t.Fatalf("the error names %q, not the responsible variable", misconfigured.Variable)
			}
		})
	}
}

// A URL carrying userinfo is ACCEPTED. That is the property; how it is
// achieved is not. An earlier draft called this test "userinfo is stripped
// before the host is checked" and paired it with a hand-rolled strip -- but
// url.Parse separates userinfo into parsed.User by itself, so the strip was
// dead code and deleting it left this test green. The name now says what is
// pinned, which is what makes it possible to notice that again.
func TestAURLCarryingUserinfoIsAccepted(t *testing.T) {
	t.Setenv("DISPATCHARR_INTERNAL_API_BASE_URL", "http://user:pw@web:9191")
	got, err := BaseURL()
	if err != nil {
		t.Fatalf("a URL with userinfo was rejected: %v", err)
	}
	if got != "http://user:pw@web:9191" {
		t.Fatalf("BaseURL = %q", got)
	}
}

func TestAMisconfigurationMessageNeverEchoesTheValue(t *testing.T) {
	t.Setenv("DISPATCHARR_INTERNAL_API_BASE_URL", "http://user:hunter2@bad_host:9191")
	_, err := BaseURL()
	if err == nil {
		t.Fatal("a bad host was accepted")
	}
	if got := err.Error(); strings.Contains(got, "hunter2") || strings.Contains(got, "bad_host") {
		t.Fatalf("the error echoes the rejected value: %s", got)
	}
}

// SF8's regression. An empty DISPATCHARR_WEB_HOST is what a half-filled
// compose env file produces, and Python fails visibly on it: os.environ.get
// returns "", resolve_base_url builds "http://:9191", and validated_base_url
// finds no domain and raises ImproperlyConfigured naming the variable. A Go
// fallback keyed on emptiness rather than absence would silently resolve
// http://web:9191 and talk to whatever answers there.
func TestAnEmptyHostVariableFailsRatherThanFallingBack(t *testing.T) {
	if err := os.Unsetenv("DISPATCHARR_INTERNAL_API_BASE_URL"); err != nil {
		t.Fatalf("unsetting the override: %v", err)
	}
	t.Setenv("DISPATCHARR_ENV", "modular")
	t.Setenv("DISPATCHARR_WEB_HOST", "")
	t.Setenv("DISPATCHARR_PORT", "9191")

	got, err := BaseURL()
	var misconfigured *ErrNotConfigured
	if !errors.As(err, &misconfigured) {
		t.Fatalf("BaseURL with an empty DISPATCHARR_WEB_HOST = %q, %v; want an "+
			"*ErrNotConfigured, not a silent fallback to the default host", got, err)
	}
	if misconfigured.Variable != "DISPATCHARR_WEB_HOST" {
		t.Fatalf("the error names %q, not the responsible variable", misconfigured.Variable)
	}
}
