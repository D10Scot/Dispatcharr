#!/usr/bin/env bash
# Keyless-sign an image digest unless this repository's workflows already have.
#
# Why (#682): a merge that does not change the image rebuilds a byte-identical
# digest, and ci.yml and docker-build.yml both sign the same digest on every
# push to main. Rekor answers the second signer
#   [POST /api/v1/log/entries][409] createLogEntryConflict ... an equivalent
#   entry already exists
# and `cosign sign` exits 1 although the digest is signed. This script:
#   1. verifies first and skips when a signature from one of this repo's four
#      signing workflows already exists;
#   2. otherwise signs, with the transparency log on (never --tlog-upload=false);
#   3. on exactly that 409, treats it as success ONLY if a verify then finds the
#      signature (retried, because the other signer uploads to Rekor before it
#      pushes to the registry). A 409 with no verifiable signature fails.
# Any other signing error fails at once.
#
# Usage: IMAGE_REF=<image>@<digest> GITHUB_REPOSITORY=<owner/repo> \
#          scripts/cosign_sign_once.sh
# Test knobs: VERIFY_RETRIES (default 6), VERIFY_SLEEP seconds (default 10).
set -euo pipefail

: "${IMAGE_REF:?IMAGE_REF (image@sha256:digest) is required}"
: "${GITHUB_REPOSITORY:?GITHUB_REPOSITORY (owner/repo) is required}"
RETRIES="${VERIFY_RETRIES:-6}"
SLEEP="${VERIFY_SLEEP:-10}"
ISSUER="https://token.actions.githubusercontent.com"

# Every workflow that signs an image of this repository, on a branch or a tag.
repo_re="$(printf '%s' "$GITHUB_REPOSITORY" | sed 's/[][\.^$*+?(){}|]/\\&/g')"
IDENTITY_RE="^https://github\\.com/${repo_re}/\\.github/workflows/(ci|docker-build|base-image|release)\\.yml@refs/(heads|tags)/.+\$"

verified() {
  cosign verify "$IMAGE_REF" \
    --certificate-identity-regexp="$IDENTITY_RE" \
    --certificate-oidc-issuer="$ISSUER" >/dev/null 2>&1
}

if verified; then
  echo "${IMAGE_REF} already carries a signature from this repository's workflows; not signing again."
  exit 0
fi

sign_out="$(mktemp)"
trap 'rm -f "$sign_out"' EXIT
if cosign sign --yes "$IMAGE_REF" 2>&1 | tee "$sign_out"; then
  exit 0
fi

if ! grep -Fq '[409]' "$sign_out" || ! grep -Fq 'an equivalent entry already exists' "$sign_out"; then
  echo "cosign sign failed for a reason other than a duplicate Rekor entry." >&2
  exit 1
fi

echo "Rekor already holds an equivalent entry; waiting for its signature to be verifiable."
for ((i = 1; i <= RETRIES; i++)); do
  if verified; then
    echo "Signature present after ${i} check(s); treating the 409 as success."
    exit 0
  fi
  sleep "$SLEEP"
done
echo "Rekor reported a duplicate entry but no signature from this repository verifies on ${IMAGE_REF}." >&2
exit 1
