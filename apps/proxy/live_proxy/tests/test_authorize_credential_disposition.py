"""Row 30: a credential an authenticator REJECTS is 401; one it DECLINES is anonymous.

`_drf_user` (apps/proxy/authorize.py:251-265) has two exits that a porter reads as
one. `AuthenticationFailed` -- raised by JWTAuthentication for a malformed or
unverifiable Bearer token, and by ApiKeyAuthentication for an unknown key --
becomes AuthorizeDenied(401). Every other outcome, including "no credential was
presented at all", returns None and the caller falls through to the anonymous
principal, which is still allowed to stream an ordinary channel by UUID.

A Go port that flattens both to "anonymous" fails no other test in this suite, and
the failure it introduces is silent: a request carrying a credential the control
plane rejected streams anyway.

The two requests below differ in exactly one thing -- whether an Authorization
header is present -- and they must get different answers.

WHY the first assertion is driven at /_dispatcharr/authorize rather than directly
at /proxy/ts/stream/<uuid>, which is where every other test in this file (and the
plan's first draft of this one) drives a tune: stream_ts is `@api_view(["GET"])`
with no `@authentication_classes` override, so DRF's own dispatch() runs
`perform_authentication()` against the project DEFAULT_AUTHENTICATION_CLASSES
(JWTAuthentication, ApiKeyAuthentication -- settings.py DEFAULT_AUTHENTICATION_CLASSES)
BEFORE the view body, and therefore before resolve_authorization()/_drf_user(), ever
runs. A malformed Bearer token or a rejected API key is refused right there, by
rest_framework_simplejwt or ApiKeyAuthentication's own AuthenticationFailed -- and
DRF's generic exception handler turns that into a 401 with DRF's own body shape
({"detail": "...", ...}), never authorize.py's ({"error": "..."}). A test that
asserts only the status code on that surface passes whether or not _drf_user's own
two-way disposition is correct, which is exactly the flattening this row exists to
catch. Verified for both credential types this row cites: a malformed Bearer token
against /proxy/ts/stream/ 401s with rest_framework_simplejwt's
{"detail":"Given token not valid for any token type","code":"token_not_valid",...};
a rejected X-API-Key against the same URL 401s with {"detail":"Invalid API key"} --
DRF's generic wrapping of ApiKeyAuthentication's own AuthenticationFailed message,
not authorize.py's. Both are evidence about a dependency, not about this module.

/_dispatcharr/authorize (authorize_views.py, @authentication_classes([])) is where
_drf_user's own three-class list (apps/proxy/authorize.py:93-97) gets an unshadowed
turn: an empty authentication_classes list means DRF's dispatch() runs zero
authenticators, so nothing raises AuthenticationFailed at the dispatch layer --
though dispatch() still calls perform_authentication(), which still sets
request.user to AnonymousUser as a side effect (why _session_user reads
django.contrib.auth.get_user(http_request) directly rather than trusting
request.user -- see its own docstring). The request-under-test then reaches
resolve_authorization() -> _drf_user() for real, and the same malformed Bearer
token there 401s with authorize.py's own body, {"error": "Invalid credentials"} --
confirmed by driving it, not assumed.

This is also, concretely, the surface nginx's auth_request hits once per tune in
every deployment shape that has nginx in front -- so this test exercises the
production decision path, and the direct-tune surface used by every OTHER test in
this file exercises resolve_authorization()'s inline fallback (no nginx: dev
runserver, or the two locations S8 excludes from auth_request). The consequence for
row 30 specifically: on the direct-tune surface, the answer to "was this credential
rejected or merely declined" is currently being given by DRF's own defaults, not by
authorize.py -- so a Go port that faithfully reproduces authorize.py's _drf_user and
is then driven at a bare streaming URL with no auth_request in front of it would
diverge from Python's behaviour there not because the port got authorize.py wrong,
but because Python itself never runs authorize.py's disposition logic on that path
for these two credential types. That is a D5 parity fact about this specific pair of
surfaces, not a footnote to this test.
"""

from .harness.asset import TS_PACKET_SIZE
from .harness.relay import RelayHarnessTestCase
from .manager_support import proxy_stream_profile


class CredentialDispositionTests(RelayHarnessTestCase):
    def hop(self, uri, *, headers=None):
        """One auth_request subrequest, exactly as nginx makes it.

        Copied from test_authorize_matrix_over_http.py's own idiom (2a-5) rather
        than reinvented -- that file already established this is how a row is
        decided over real HTTP, at the surface the decision is actually made on.
        """
        import requests

        return requests.get(
            f"{self.live_server_url}/_dispatcharr/authorize",
            headers={"X-Original-URI": uri, **(headers or {})},
            timeout=10,
        )

    def assertDenied(self, response, real_status):
        self.assertIn(response.status_code, (401, 403))
        self.assertEqual(response.headers.get("X-Authorize-Status"), str(real_status))

    def test_a_rejected_bearer_token_is_refused_with_401(self):
        channel = self.make_channel(
            upstream_url=self.upstream.url, profile=proxy_stream_profile()
        )
        response = self.hop(
            f"/proxy/ts/stream/{channel.uuid}",
            headers={"Authorization": "Bearer not.a.jwt"},
        )
        self.assertDenied(response, 401)
        self.assertEqual(
            response.json().get("error"),
            "Invalid credentials",
            "the body did not carry authorize.py's own denial -- if this looks "
            "like rest_framework_simplejwt's {'detail': ..., 'code': ...} shape "
            "instead, the request never reached _drf_user at all",
        )

    def test_no_credential_at_all_streams_as_anonymous(self):
        channel = self.make_channel(
            upstream_url=self.upstream.url, profile=proxy_stream_profile()
        )
        with self.tuned(channel) as stream:
            served = stream.read(20 * TS_PACKET_SIZE)
        self.assertTrue(
            served,
            "an anonymous tune of an ordinary channel served no bytes; the "
            "declined-credential half of row 30 is the one that must NOT 401",
        )
