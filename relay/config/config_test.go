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

// SF2: no other test exercises this literal -- every Load()-level test below
// sets DISPATCHARR_SECRET_FILE explicitly and most never reach the file
// branch at all, since DJANGO_SECRET_KEY short-circuits it. A typo in
// DefaultSecretFile would still compile and would still pass every other
// test in this package, and would ship as a silent startup failure in every
// deployment role that ever falls through to the file (a manual `go run`, a
// container whose entrypoint hasn't exported the variable yet).
func TestDefaultSecretFileIsPinned(t *testing.T) {
	const want = "/data/jwt" // docker/entrypoint.sh:103's SECRET_FILE
	if DefaultSecretFile != want {
		t.Fatalf("DefaultSecretFile = %q, want %q", DefaultSecretFile, want)
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
// environment variable name in Load's own call, reading the secret from the
// wrong source, and dropping DevRoutes from the returned struct. That is
// hollow shape 3 aimed at the wiring rather than the logic: each part is
// proven and the assembly is not.
//
// The secret comes from DJANGO_SECRET_KEY, not DISPATCHARR_SECRET_FILE:
// that is the realistic path (every supervisord program in this deployment
// gets its secret this way -- see loadSecret's comment), and it is also the
// path every OTHER role reaches, so this is the assembly this test should
// pin. DISPATCHARR_SECRET_FILE is left unset entirely, and Load() must
// still succeed without ever touching a file that may not exist on this
// host -- which is itself part of what this test proves.
//
// Asserts all three fields in one call, so it fails on any of them, and
// supplies values the defaults cannot produce (shape 2): 5999 is not 5658,
// the secret is a literal no fallback generates, and DevRoutes is forced on
// while DISPATCHARR_ENV is unset.
func TestLoadWiresAllThreeFields(t *testing.T) {
	t.Setenv("DJANGO_SECRET_KEY", "wired-secret")
	t.Setenv("DISPATCHARR_SECRET_FILE", "")
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

// A0: relay-go originally read /data/jwt directly, which BACKOFF-looped it
// to death under a non-root PUID/PGID (docker/tests/test-puid-pgid.sh) --
// entrypoint.sh reads that file as root before dropping privilege, and this
// process's own read happens after the drop. This test is the fallback path
// that survives when there genuinely is no inherited environment (a manual
// `go run`, a test that wants to exercise ReadSecretFile's stripping through
// Load() rather than by calling it directly).
func TestLoadFallsBackToTheSecretFileWhenTheEnvironmentIsUnset(t *testing.T) {
	dir := t.TempDir()
	path := filepath.Join(dir, "jwt")
	if err := os.WriteFile(path, []byte("file-only-secret\n"), 0o600); err != nil {
		t.Fatalf("writing fixture: %v", err)
	}
	t.Setenv("DJANGO_SECRET_KEY", "")
	t.Setenv("DISPATCHARR_SECRET_FILE", path)

	cfg, err := Load()
	if err != nil {
		t.Fatalf("Load() failed: %v", err)
	}
	if cfg.Secret != "file-only-secret" {
		t.Fatalf("Secret = %q, want %q", cfg.Secret, "file-only-secret")
	}
}

// The one test that actually exercises precedence, and the only one of the
// three Load()-level secret tests whose outcome depends on which source
// loadSecret checks first: the other two never set both sources to
// different values, so a break-check that swaps loadSecret's order reddens
// exactly this test.
func TestLoadPrefersTheEnvironmentOverTheFile(t *testing.T) {
	dir := t.TempDir()
	path := filepath.Join(dir, "jwt")
	if err := os.WriteFile(path, []byte("file-secret\n"), 0o600); err != nil {
		t.Fatalf("writing fixture: %v", err)
	}
	t.Setenv("DJANGO_SECRET_KEY", "env-secret")
	t.Setenv("DISPATCHARR_SECRET_FILE", path)

	cfg, err := Load()
	if err != nil {
		t.Fatalf("Load() failed: %v", err)
	}
	if cfg.Secret != "env-secret" {
		t.Fatalf("Secret = %q, want %q (the environment must win over the file)", cfg.Secret, "env-secret")
	}
}

// Neither source set: the existing loud startup failure, unchanged. A
// relay that fell back to a generated or empty secret here would answer
// every internal call with a silent 403.
func TestLoadFailsLoudlyWhenNeitherSourceIsSet(t *testing.T) {
	t.Setenv("DJANGO_SECRET_KEY", "")
	t.Setenv("DISPATCHARR_SECRET_FILE", filepath.Join(t.TempDir(), "absent"))

	if _, err := Load(); err == nil {
		t.Fatal("Load() succeeded with neither DJANGO_SECRET_KEY set nor a readable secret file")
	}
}
