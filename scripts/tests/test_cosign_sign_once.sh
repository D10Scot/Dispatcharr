#!/usr/bin/env bash
# Tests scripts/cosign_sign_once.sh against a fake cosign. Run by lint.yml's
# `cosign-sign-tests` job. The fake is the only cosign on PATH: PATH is built
# from the fake's directory plus the tool directories bash, tee, grep, sed,
# mktemp, rm and sleep live in, and a case aborts if `cosign` does not resolve
# to the fake.
set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SCRIPT="${COSIGN_SIGN_ONCE:-$HERE/../cosign_sign_once.sh}"
TMP="$(mktemp -d)"; trap 'rm -rf "$TMP"' EXIT
BIN="$TMP/bin"; mkdir "$BIN"
fail=0

cat > "$BIN/cosign" <<'FAKE'
#!/usr/bin/env bash
# FAKE_VERIFY: file with verify's exit code. FAKE_SIGNS: one code per sign call. Calls are logged.
echo "$1 $*" >> "$FAKE_LOG"
case "$1" in
  verify) rc=$(cat "$FAKE_VERIFY"); [ "$rc" = 0 ] || echo "fake verify error" >&2; exit "$rc" ;;
  sign)
    n=$(grep -c '^sign' "$FAKE_LOG")
    rc=$(sed -n "${n}p" "$FAKE_SIGNS"); [ -n "$rc" ] || rc=$(tail -n1 "$FAKE_SIGNS")
    case "$rc" in
      0) echo signed ;;
      1) echo 'Error: [POST /api/v1/log/entries][409] createLogEntryConflict {"code":409,"message":"an equivalent entry already exists in the transparency log with UUID x"}' ;;
      *) echo 'Error: fulcio 500' ;;
    esac
    [ "$rc" = 0 ] && exit 0; exit 1 ;;
esac
exit 99
FAKE
chmod +x "$BIN/cosign"
# A logging sleep ahead of the real one, so a case can count how often it ran.
# shellcheck disable=SC2016 # the fake's body must expand when it runs, not now
printf '#!/usr/bin/env bash\necho "sleep $*" >> "$FAKE_LOG"\n' > "$BIN/sleep"; chmod +x "$BIN/sleep"
SAFE_PATH="$BIN:/usr/bin:/bin"

# run <name> <want-rc> <sign-rcs> <verify-rc> <out-substring> <want-sign-calls> [log-substring]
# sign-rcs: space-separated exit codes, one per sign call (the last repeats);
# a code other than 0 and 1 prints a non-409 error, 1 prints the Rekor 409.
run() {
  local wsleep="${WANT_SLEEPS:-}" codes name="$1" want="$2" srcs="$3" vrc="$4" sub="$5" wsign="$6" logsub="${7:-}" out rc nsign nsleep nmsg
  : > "$TMP/log"; read -ra codes <<< "$srcs"; printf '%s\n' "${codes[@]}" > "$TMP/signs"; echo "$vrc" > "$TMP/verify"
  [ "$(PATH="$SAFE_PATH" command -v cosign)" = "$BIN/cosign" ] || { echo "ABORT: cosign does not resolve to the fake"; exit 2; }
  out="$(env -i PATH="$SAFE_PATH" HOME="$TMP" FAKE_LOG="$TMP/log" FAKE_SIGNS="$TMP/signs" FAKE_VERIFY="$TMP/verify" \
        SIGN_RETRIES=2 SIGN_SLEEP=0 IMAGE_REF=ghcr.io/o/r@sha256:abc \
        GITHUB_WORKFLOW_REF=acme/widget/.github/workflows/w.yml@refs/heads/main bash "$SCRIPT" 2>&1)"; rc=$?
  nsign=$(grep -c '^sign' "$TMP/log" || true)
  nsleep=$(grep -c '^sleep' "$TMP/log" || true); nmsg=$(grep -c 're-signing' <<< "$out" || true)
  if { [ -n "$wsleep" ] && { [ "$nsleep" -ne "$wsleep" ] || [ "$nmsg" -ne "$wsleep" ]; }; } || [ "$rc" -ne "$want" ] || [[ "$out" != *"$sub"* ]] || [ "$nsign" -ne "$wsign" ] \
     || { [ -n "$logsub" ] && ! grep -Fq -- "$logsub" "$TMP/log"; } \
     || grep -q -- '--tlog-upload' "$TMP/log"; then
    echo "FAIL $name: exit $rc (want $want), sign calls $nsign (want $wsign), output: $out"; fail=1
  else
    echo "ok   $name"
  fi
}

ID='--certificate-identity https://github.com/acme/widget/.github/workflows/w.yml@refs/heads/main'
run "first sign succeeds, verified"                    0 "0"     0 "Signature verified"          1 "$ID"
run "self-409 then re-sign succeeds"                   0 "1 0"   0 "re-signing with a fresh"     2 "$ID"
WANT_SLEEPS=2 run "409 on every attempt: 3 signs, 2 sleeps and 2 re-sign messages, none after the last" 1 "1" 0 "all 3 attempts" 3
run "non-409 error fails without retry"                1 "7"     0 "reason other than"           1
run "signed but verify fails: fails, shows cosign err" 1 "0"     1 "fake verify error"           1

exit "$fail"
