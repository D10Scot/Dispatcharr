// Package control speaks the two internal HTTP contracts: the /api/relay/...
// calls the relay makes to Django, and the /proxy/relay/... calls Django
// makes to the relay. At 2c-1 it holds only the tokens both directions
// authenticate with; the HTTP client and server arrive in 2c-5 and 2c-8.
//
// The wire contract is apps/proxy/internal_auth.py, read in full. Three
// context-separated HMACs of the deployment's Django SECRET_KEY:
//
//	X-Dispatcharr-Authorized       HMAC(key, "relay-trust")
//	    nginx sets it on every relay-bound location. The relay only ever
//	    VERIFIES it; nginx is the producer.
//	X-Dispatcharr-Internal         HMAC(key, "internal-principal")
//	    "this caller is part of this deployment". Long-lived and shared.
//	X-Dispatcharr-Internal-Request v1.<unix_ts>.<hex>
//	    binds one request -- method, full path, body, timestamp.
package control

import (
	"crypto/hmac"
	"crypto/sha256"
	"encoding/hex"
	"strconv"
	"strings"
	"time"
)

// Header names, spelled exactly as apps/proxy/internal_auth.py spells them.
const (
	HeaderAuthorized      = "X-Dispatcharr-Authorized"
	HeaderInternal        = "X-Dispatcharr-Internal"
	HeaderInternalRequest = "X-Dispatcharr-Internal-Request"
)

// RequestWindow is how far a bound token's timestamp may sit from now, in
// EITHER direction: internal_auth.py's check is `abs(now - ts) > 120`, so a
// token up to 120s in the future is accepted too. Reproduced, not narrowed --
// narrowing it would reject calls a correctly-clocked peer makes.
const RequestWindow = 120 * time.Second

var (
	contextRelayTrust        = []byte("relay-trust")
	contextInternalPrincipal = []byte("internal-principal")
	contextInternalRequest   = []byte("internal-request")
)

func staticToken(secret string, context []byte) string {
	mac := hmac.New(sha256.New, []byte(secret))
	mac.Write(context)
	return hex.EncodeToString(mac.Sum(nil))
}

// RelayTrustToken is the value nginx puts in X-Dispatcharr-Authorized. The
// relay derives it only so it can compare, never to send.
func RelayTrustToken(secret string) string {
	return staticToken(secret, contextRelayTrust)
}

// InternalPrincipalToken is the value this process puts in
// X-Dispatcharr-Internal on every call it makes to Django.
func InternalPrincipalToken(secret string) string {
	return staticToken(secret, contextInternalPrincipal)
}

// IsRelayTrusted reports whether value is this deployment's relay-trust
// marker. Constant-time, and it treats an empty or non-ASCII value as a
// mismatch rather than an error, matching internal_auth._matches.
func IsRelayTrusted(secret, value string) bool {
	return matches(value, RelayTrustToken(secret))
}

// IsInternalPrincipal reports whether value is this deployment's static
// internal-principal marker.
func IsInternalPrincipal(secret, value string) bool {
	return matches(value, InternalPrincipalToken(secret))
}

func matches(value, expected string) bool {
	if value == "" || expected == "" {
		return false
	}
	// internal_auth._matches rejects non-ASCII before comparing, because
	// hmac.compare_digest raises on it. Go's subtle.ConstantTimeCompare does
	// not raise, but the two sides must agree on what they reject or a
	// malformed header is accepted here and refused there.
	for i := 0; i < len(value); i++ {
		if value[i] >= 0x80 {
			return false
		}
	}
	return hmac.Equal([]byte(value), []byte(expected))
}

// InternalRequestToken is the hex digest half of X-Dispatcharr-Internal-Request.
//
// The message is five fields joined on a literal '\n' byte
// (internal_auth.internal_request_token):
//
//	"internal-request" \n METHOD \n FULL_PATH \n TIMESTAMP \n hex(sha256(BODY))
//
// fullPath is the path WITH its query string -- Django verifies against
// request.get_full_path(), not request.path, and internal_auth.py's own
// comment says why: "the query string is part of what a caller is asking
// for, so it has to be part of what the token binds". A client built against
// the bare path 403s every call that carries a query.
//
// An empty body hashes as sha256 of zero bytes, not as an omitted field.
func InternalRequestToken(secret, method, fullPath string, body []byte, timestamp int64) string {
	bodyDigest := sha256.Sum256(body)

	var message []byte
	message = append(message, contextInternalRequest...)
	message = append(message, '\n')
	message = append(message, strings.ToUpper(method)...)
	message = append(message, '\n')
	message = append(message, fullPath...)
	message = append(message, '\n')
	message = append(message, strconv.FormatInt(timestamp, 10)...)
	message = append(message, '\n')
	message = append(message, hex.EncodeToString(bodyDigest[:])...)

	mac := hmac.New(sha256.New, []byte(secret))
	mac.Write(message)
	return hex.EncodeToString(mac.Sum(nil))
}

// InternalRequestHeader is the full X-Dispatcharr-Internal-Request value:
// the literal version prefix "v1", the timestamp, and the digest, joined on
// ASCII '.'. The verifier splits on '.' into EXACTLY three parts and rejects
// anything else, so no field here may contain one.
func InternalRequestHeader(secret, method, fullPath string, body []byte, timestamp int64) string {
	return "v1." + strconv.FormatInt(timestamp, 10) + "." +
		InternalRequestToken(secret, method, fullPath, body, timestamp)
}

// VerifyInternalRequest checks a header this process received. The four rules
// are internal_auth.request_is_internal_request's, in its order: exactly
// three dot-separated parts, a literal "v1" first part, a parsable integer
// timestamp within RequestWindow in either direction, and a constant-time
// digest match.
func VerifyInternalRequest(secret, header, method, fullPath string, body []byte, now time.Time) bool {
	parts := strings.Split(header, ".")
	if len(parts) != 3 || parts[0] != "v1" {
		return false
	}
	timestamp, err := strconv.ParseInt(parts[1], 10, 64)
	if err != nil {
		return false
	}
	skew := now.Unix() - timestamp
	if skew < 0 {
		skew = -skew
	}
	if skew > int64(RequestWindow/time.Second) {
		return false
	}
	return matches(parts[2], InternalRequestToken(secret, method, fullPath, body, timestamp))
}
