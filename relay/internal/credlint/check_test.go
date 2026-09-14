package main

import (
	"strings"
	"testing"
)

// A fixture package with every shape the rule speaks to. Each line that
// must be reported names itself in a comment, so a finding's line is
// checked against the fixture rather than counted.
const fixture = `package fixture

import (
	"errors"
	"fmt"
	"log"
	"log/slog"
	"net/url"

	"github.com/D10Scot/Dispatcharr/relay/redact"
)

type wrapped struct{ err error }

func (w wrapped) Error() string { return fmt.Sprintf("wrapped: %v", w.err) } // BAD: a method formatting an error field

func shapes(logger *slog.Logger, err error) error {
	_ = fmt.Errorf("plain: %w", err)                  // BAD
	_ = fmt.Errorf("redacted: %w", redact.Error(err)) // ok: through the redactor
	_ = fmt.Errorf("marked: %w", err)                 // credential-logging: ok - a test fixture with a reason
	// credential-logging: ok - a marker on the line above
	_ = fmt.Errorf("marked above: %w", err)
	_ = fmt.Errorf("bare marker: %w", err) // credential-logging: ok
	_ = fmt.Errorf("no error here: %s", "text")
	_ = fmt.Errorf("nil is fine: %w", nil)
	logger.Error("slog method", "error", err)                // BAD
	logger.Error("slog redacted", "error", redact.Error(err)) // ok
	slog.Warn("slog package", "error", err)                   // BAD
	log.Printf("log package: %v", err)                        // BAD
	_ = slog.Any("error", err)                                // BAD
	var uerr *url.Error
	if errors.As(err, &uerr) {
		return fmt.Errorf("typed: %w", uerr) // BAD: a *url.Error is an error
	}
	return wrapped{err: err} // not a call: the known composite-literal gap
}
`

// newCheckerWithRedact type-checks the module's own redact package first, so
// the fixture's import of it resolves to the real package and the allowlist
// is exercised against the name go/types gives it.
func newCheckerWithRedact(t *testing.T) *Checker {
	t.Helper()
	_, pkgs, err := ListPackages("../..", "./redact")
	if err != nil {
		t.Fatalf("listing the redact package: %v", err)
	}
	c := NewChecker()
	for _, p := range pkgs {
		if err := c.CheckPackage(p); err != nil {
			t.Fatalf("checking %s: %v", p.ImportPath, err)
		}
	}
	if len(c.Findings) != 0 {
		t.Fatalf("the redact package itself has findings: %v", c.Findings)
	}
	return c
}

func TestTheRuleReportsExactlyTheBadLines(t *testing.T) {
	c := newCheckerWithRedact(t)
	if err := c.CheckSources("example.com/fixture", map[string]string{"fixture.go": fixture}); err != nil {
		t.Fatalf("type-checking the fixture: %v", err)
	}
	want := map[int]bool{}
	for i, line := range strings.Split(fixture, "\n") {
		if strings.Contains(line, "// BAD") || strings.Contains(line, "bare marker") {
			want[i+1] = true
		}
	}
	got := map[int]bool{}
	for _, f := range c.Findings {
		got[f.Pos.Line] = true
	}
	for line := range want {
		if !got[line] {
			t.Errorf("line %d was not reported: %s", line, strings.Split(fixture, "\n")[line-1])
		}
	}
	for line := range got {
		if !want[line] {
			t.Errorf("line %d was reported and should not have been: %s", line, strings.Split(fixture, "\n")[line-1])
		}
	}
	for _, f := range c.Findings {
		if strings.Contains(strings.Split(fixture, "\n")[f.Pos.Line-1], "bare marker") && !strings.Contains(f.Reason, "no reason") {
			t.Errorf("the bare marker was reported for the wrong reason: %s", f.Reason)
		}
	}
}

// The redactor allowlist is the ONE function, spelled as go/types spells
// it. A rename on either side must fail here, not silently clear every call.
func TestTheRedactorIsExactlyRedactError(t *testing.T) {
	if len(Redactors) != 1 || !Redactors["github.com/D10Scot/Dispatcharr/relay/redact.Error"] {
		t.Fatalf("Redactors = %v, want exactly relay/redact.Error", Redactors)
	}
	c := NewChecker()
	// A package that defines its own Error and calls it: NOT a redactor.
	src := `package fixture
import "fmt"
func Error(err error) error { return err }
func f(err error) error { return fmt.Errorf("local: %w", Error(err)) } // BAD
`
	if err := c.CheckSources("example.com/local", map[string]string{"local.go": src}); err != nil {
		t.Fatal(err)
	}
	if len(c.Findings) != 1 {
		t.Fatalf("a local function named Error cleared the call: %v", c.Findings)
	}
}
