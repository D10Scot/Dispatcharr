#!/usr/bin/env bash
# Keyless-sign an image digest, surviving Rekor's self-conflict 409 (#682).
#
# Cause: `cosign sign` POSTs its entry to Rekor, the client can time out (about
# 30 s) after the entry landed, and its automatic retry of the same request is
# answered
#   [POST /api/v1/log/entries][409] createLogEntryConflict ... an equivalent
#   entry already exists
# by the job's OWN entry. cosign then exits 1 before pushing the signature, so
# the digest stays unsigned. (run 43465281821: entry certificate and run-URL
# extension were the failing run itself, 30.7 s after "Signing artifact...".)
#
# Fix: on exactly that 409, run `cosign sign` again. A new invocation mints a
# fresh ephemeral key and certificate, so it cannot conflict; the orphan entry
# is harmless. The transparency log stays on (never --tlog-upload=false), any
# other error fails at once, and after a successful sign one `cosign verify`
# against this job's own exact identity proves the signature is in the registry.
#
# Usage: IMAGE_REF=<image>@<digest> GITHUB_WORKFLOW_REF=<owner/repo/path@ref> \
#          scripts/cosign_sign_once.sh
# Test knobs: SIGN_RETRIES re-runs after the first 409 (default 2),
#             SIGN_SLEEP seconds between attempts (default 5).
set -euo pipefail

: "${IMAGE_REF:?IMAGE_REF (image@sha256:digest) is required}"
: "${GITHUB_WORKFLOW_REF:?GITHUB_WORKFLOW_REF (owner/repo/.github/workflows/x.yml@ref) is required}"
RETRIES="${SIGN_RETRIES:-2}"
SLEEP="${SIGN_SLEEP:-5}"
ISSUER="https://token.actions.githubusercontent.com"
IDENTITY="https://github.com/${GITHUB_WORKFLOW_REF}"

out="$(mktemp)"
trap 'rm -f "$out"' EXIT

signed=0
for ((attempt = 1; attempt <= RETRIES + 1; attempt++)); do
  if cosign sign --yes "$IMAGE_REF" 2>&1 | tee "$out"; then
    signed=1
    break
  fi
  if ! grep -Fq '[409]' "$out" || ! grep -Fq 'an equivalent entry already exists' "$out"; then
    echo "cosign sign failed for a reason other than a duplicate Rekor entry." >&2
    exit 1
  fi
  echo "Rekor 409 (attempt ${attempt}): re-signing with a fresh ephemeral key."
  sleep "$SLEEP"
done

if [ "$signed" -ne 1 ]; then
  echo "cosign sign hit Rekor's duplicate-entry 409 on all $((RETRIES + 1)) attempts." >&2
  exit 1
fi

if ! cosign verify "$IMAGE_REF" \
  --certificate-identity "$IDENTITY" \
  --certificate-oidc-issuer "$ISSUER" >/dev/null 2>"$out"; then
  echo "Signed, but verification against ${IDENTITY} failed:" >&2
  cat "$out" >&2
  exit 1
fi
echo "Signature verified for ${IDENTITY}."
