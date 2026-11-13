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
# FAKE_VERIFY: file holding one exit code per verify call (last repeats).
# FAKE_SIGN_RC / FAKE_SIGN_MSG: result of `sign`. Calls are logged.
echo "$1 $*" >> "$FAKE_LOG"
case "$1" in
  verify)
    n=$(grep -c '^verify' "$FAKE_LOG")
    rc=$(sed -n "${n}p" "$FAKE_VERIFY"); [ -n "$rc" ] || rc=$(tail -n1 "$FAKE_VERIFY")
    exit "$rc" ;;
  sign) echo "$FAKE_SIGN_MSG"; exit "$FAKE_SIGN_RC" ;;
esac
exit 99
FAKE
chmod +x "$BIN/cosign"
SAFE_PATH="$BIN:/usr/bin:/bin"

# run <name> <want-rc> <verify-codes> <sign-rc> <sign-msg> <out-substring> <want-sign-calls> [identity-substring]
run() {
  local name="$1" want="$2" vcodes="$3" src="$4" smsg="$5" sub="$6" wsign="$7" idsub="${8:-}" out rc nsign
  : > "$TMP/log"; printf '%b' "$vcodes" > "$TMP/verify"
  [ "$(PATH="$SAFE_PATH" command -v cosign)" = "$BIN/cosign" ] || { echo "ABORT: cosign does not resolve to the fake"; exit 2; }
  out="$(env -i PATH="$SAFE_PATH" HOME="$TMP" FAKE_LOG="$TMP/log" FAKE_VERIFY="$TMP/verify" \
        FAKE_SIGN_RC="$src" FAKE_SIGN_MSG="$smsg" VERIFY_RETRIES=3 VERIFY_SLEEP=0 \
        IMAGE_REF=ghcr.io/o/r@sha256:abc GITHUB_REPOSITORY=acme/widget.x bash "$SCRIPT" 2>&1)"; rc=$?
  nsign=$(grep -c '^sign' "$TMP/log" || true)
  if [ "$rc" -ne "$want" ] || [[ "$out" != *"$sub"* ]] || [ "$nsign" -ne "$wsign" ] \
     || { [ -n "$idsub" ] && ! grep -Fq -- "$idsub" "$TMP/log"; } \
     || grep -q -- '--tlog-upload' "$TMP/log"; then
    echo "FAIL $name: exit $rc (want $want), sign calls $nsign (want $wsign), output: $out"; fail=1
  else
    echo "ok   $name"
  fi
}

CONFLICT='Error: [POST /api/v1/log/entries][409] createLogEntryConflict {"code":409,"message":"an equivalent entry already exists in the transparency log with UUID x"}'

run "already signed: verify passes, no sign"   0 '0\n' 0 ''          "not signing again" 0 'acme/widget\.x/'
run "unsigned: signs"                          0 '1\n' 0 'signed'   ""                  1
run "409 and signature appears on re-verify"   0 '1\n1\n0\n' 1 "$CONFLICT" "treating the 409 as success" 1
run "409 and no signature ever: fails"         1 '1\n' 1 "$CONFLICT" "no signature from this repository verifies" 1
run "other sign error: fails, no retry"        1 '1\n0\n' 1 'Error: fulcio 500' "reason other than a duplicate" 1
run "409 text without the Rekor message fails" 1 '1\n0\n' 1 'Error: [409] conflict elsewhere' "reason other than a duplicate" 1

exit "$fail"
