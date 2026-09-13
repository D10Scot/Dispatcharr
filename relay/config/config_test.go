package config

import (
	"errors"
	"os"
	"path/filepath"
	"testing"
)

func TestPortDefaultsTo5658(t *testing.T) {
	t.Setenv("DISPATCHARR_RELAY_GO_PORT", "")
	got, err := intFromEnv("DISPATCHARR_RELAY_GO_PORT", DefaultPort)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if got != 5658 {
		t.Fatalf("default port = %d, want 5658", got)
	}
}

func TestPortReadsTheEnvironment(t *testing.T) {
	// 5999 rather than 5658: a value the default cannot produce, so this
	// test fails if the environment read is deleted.
	t.Setenv("DISPATCHARR_RELAY_GO_PORT", "5999")
	got, err := intFromEnv("DISPATCHARR_RELAY_GO_PORT", DefaultPort)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if got != 5999 {
		t.Fatalf("port = %d, want 5999", got)
	}
}

func TestPortRejectsGarbageRatherThanFallingBack(t *testing.T) {
	t.Setenv("DISPATCHARR_RELAY_GO_PORT", "not-a-port")
	if _, err := intFromEnv("DISPATCHARR_RELAY_GO_PORT", DefaultPort); err == nil {
		t.Fatal("a non-numeric port was accepted; it must fail loudly, not fall back")
	}
}

func TestPortRejectsOutOfRange(t *testing.T) {
	t.Setenv("DISPATCHARR_RELAY_GO_PORT", "70000")
	if _, err := intFromEnv("DISPATCHARR_RELAY_GO_PORT", DefaultPort); err == nil {
		t.Fatal("70000 was accepted as a TCP port")
	}
}

// The reason package config exists. docker/entrypoint.sh:138 uses
// `tr -d '\r\n'`, which DELETES every CR and LF anywhere in the file --
// it does not replace them with anything, and it touches nothing else.
// This fixture has an interior CRLF and surrounding spaces, so:
//
//	tr -d '\r\n'        -> "  abcdef  "    (what Django's SECRET_KEY becomes)
//	strings.TrimSpace   -> "abc\r\ndef"    (a different HMAC key)
//	strings.TrimRight   -> "  abc\r\ndef"  (a third one)
//
// Only the first is correct, and the three differ on this fixture, which
// is what makes this test able to fail. Confirm the expected value against
// the shell rather than reasoning about it -- an earlier draft of this
// plan wrote "  abc def  ", with a space where the deleted CRLF had been,
// and it is exactly the kind of error a test can encode permanently:
//
//	printf '  abc\r\ndef  \n' | tr -d '\r\n' | od -c
func TestReadSecretFileMatchesEntrypointStripping(t *testing.T) {
	dir := t.TempDir()
	path := filepath.Join(dir, "jwt")
	if err := os.WriteFile(path, []byte("  abc\r\ndef  \n"), 0o600); err != nil {
		t.Fatalf("writing fixture: %v", err)
	}

	got, err := ReadSecretFile(path)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	const want = "  abcdef  "
	if got != want {
		t.Fatalf("secret = %q, want %q", got, want)
	}
}

func TestReadSecretFileRejectsAnEmptyFile(t *testing.T) {
	dir := t.TempDir()
	path := filepath.Join(dir, "jwt")
	if err := os.WriteFile(path, []byte("\n\r\n"), 0o600); err != nil {
		t.Fatalf("writing fixture: %v", err)
	}
	_, err := ReadSecretFile(path)
	if !errors.Is(err, ErrEmptySecret) {
		t.Fatalf("error = %v, want ErrEmptySecret", err)
	}
}

func TestReadSecretFileReportsAMissingFile(t *testing.T) {
	_, err := ReadSecretFile(filepath.Join(t.TempDir(), "absent"))
	if !errors.Is(err, os.ErrNotExist) {
		t.Fatalf("error = %v, want os.ErrNotExist", err)
	}
}

func TestDevRoutesFollowDispatcharrEnv(t *testing.T) {
	t.Setenv("DISPATCHARR_RELAY_GO_DEV_ROUTES", "")
	t.Setenv("DISPATCHARR_ENV", "dev")
	if !devRoutes() {
		t.Fatal("DISPATCHARR_ENV=dev must enable the dev routes")
	}
	t.Setenv("DISPATCHARR_ENV", "aio")
	if devRoutes() {
		t.Fatal("DISPATCHARR_ENV=aio must leave the dev routes off")
	}
}

func TestDevRoutesOverrideWinsBothWays(t *testing.T) {
	t.Setenv("DISPATCHARR_ENV", "aio")
	t.Setenv("DISPATCHARR_RELAY_GO_DEV_ROUTES", "1")
	if !devRoutes() {
		t.Fatal("an explicit 1 must enable the routes outside dev")
	}
	t.Setenv("DISPATCHARR_ENV", "dev")
	t.Setenv("DISPATCHARR_RELAY_GO_DEV_ROUTES", "0")
	if devRoutes() {
		t.Fatal("an explicit 0 must disable the routes inside dev")
	}
}

// Everything above tests intFromEnv, ReadSecretFile and devRoutes directly,
// which leaves Load() -- the only function main actually calls -- entirely
// unpinned. Three defects would redden nothing without this test: a wrong
// environment variable name in Load's own call, reading the path from the
// wrong variable, and dropping DevRoutes from the returned struct. That is
// hollow shape 3 aimed at the wiring rather than the logic: each part is
// proven and the assembly is not.
//
// Asserts all three fields in one call, so it fails on any of them, and
// supplies values the defaults cannot produce (shape 2): 5999 is not 5658,
// the secret is a literal no fallback generates, and DevRoutes is forced on
// while DISPATCHARR_ENV is unset.
func TestLoadWiresAllThreeFields(t *testing.T) {
	dir := t.TempDir()
	path := filepath.Join(dir, "jwt")
	if err := os.WriteFile(path, []byte("wired-secret\n"), 0o600); err != nil {
		t.Fatalf("writing fixture: %v", err)
	}
	t.Setenv("DISPATCHARR_SECRET_FILE", path)
	t.Setenv("DISPATCHARR_RELAY_GO_PORT", "5999")
	t.Setenv("DISPATCHARR_RELAY_GO_DEV_ROUTES", "1")

	cfg, err := Load()
	if err != nil {
		t.Fatalf("Load() failed: %v", err)
	}
	if cfg.Port != 5999 {
		t.Errorf("Port = %d, want 5999", cfg.Port)
	}
	if cfg.Secret != "wired-secret" {
		t.Errorf("Secret = %q, want %q", cfg.Secret, "wired-secret")
	}
	if !cfg.DevRoutes {
		t.Error("DevRoutes = false, want true")
	}
}
