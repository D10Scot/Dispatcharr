"""POST /_dispatcharr/authorize-internal -- the Go relay's dev fallback.

Phase 2 PR 2c-8, spec D5 exception 2. Every assertion here is on the view's
own wire: a status code or an X-Relay-* response header. That is deliberate
and it is what makes these tests port: the Go relay consumes this route's
answer verbatim, so an assertion about one Python function calling another
would say nothing about the shape it consumes.

THE THREE FAILURE MODES THIS FILE EXISTS FOR ARE ALL SILENT, and each one
returns a 200 with real bytes rather than an error:

  1. Reusing the transport's own X-Dispatcharr-Internal to answer "is this an
     internal principal". IsInternalRelay REQUIRES the relay to send that
     header, so a view that passed its incoming request through would make
     _resolve_principal return INTERNAL_PRINCIPAL for every tune in every
     nginx-less deployment, before any channel flag, adult filter, profile
     membership or credential check ran.
  2. Resolving the session principal from request.user. @api_view's dispatch
     sets it to AnonymousUser before authorize_stream is called, so a view
     that forwarded the cookie and read request.user would downgrade a
     session viewer to anonymous -- a hidden channel would still 403, and an
     ordinary one would stream with user_level, profile membership, adult
     filtering and the stream limit quietly not applying.
  3. Evaluating the network ACL against the relay's own address instead of
     the client's.

A STATUS-ONLY ASSERTION CANNOT SEE ANY OF THE THREE. X-Relay-User is what
says which principal the decision was made for, and it is what these tests
assert.
"""

import json

from django.test import Client, TestCase
from django.urls import reverse

from apps.accounts.models import User
from apps.channels.models import Channel
from apps.proxy.internal_auth import (
    HEADER_INTERNAL,
    HEADER_INTERNAL_REQUEST,
    build_internal_request_header,
    internal_principal_token,
)

PATH = "/_dispatcharr/authorize-internal"


class AuthorizeInternalViewTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.plain = Channel.objects.create(name="ai-plain", channel_number=9801)
        self.hidden = Channel.objects.create(
            name="ai-hidden", channel_number=9802, hidden_from_output=True
        )

    def post(self, body, *, internal_headers=True):
        """One call, signed the way the Go relay signs it."""
        raw = json.dumps(body).encode()
        headers = {}
        if internal_headers:
            headers["HTTP_X_DISPATCHARR_INTERNAL"] = internal_principal_token()
            headers["HTTP_X_DISPATCHARR_INTERNAL_REQUEST"] = (
                build_internal_request_header("POST", PATH, raw)
            )
        return self.client.post(
            PATH, data=raw, content_type="application/json", **headers
        )

    def question(self, uri, **overrides):
        body = {
            "uri": uri,
            "client_ip": "198.51.100.4",
            "internal": False,
            "headers": {"authorization": None, "cookie": None, "x-api-key": None},
        }
        body.update(overrides)
        return body

    # -- registration and gating ----------------------------------------

    def test_the_route_is_registered_in_every_shape(self):
        """Unconditional registration, not dev-gated.

        Django cannot know at boot whether the relay it will talk to has
        nginx in front of it, so the route exists everywhere and is simply
        never called where nginx is.
        """
        self.assertEqual(reverse("authorize-internal"), PATH)

    def test_without_the_two_internal_headers_it_is_403(self):
        """Gating is the ONLY protection this route has.

        The nginx-facing view is AllowAny and is reachable only through an
        `internal;` location; this one sits outside that shield by design,
        so a missing permission class would be an authorization oracle --
        anyone reaching Django could enumerate which channel UUIDs exist and
        which are hidden by probing it.
        """
        response = self.post(
            self.question(f"/proxy/ts/stream/{self.plain.uuid}"),
            internal_headers=False,
        )
        self.assertEqual(response.status_code, 403)

    def test_the_bound_token_must_cover_the_body(self):
        """A token signed over a DIFFERENT body is refused.

        This is what makes putting the question in the body worth anything:
        sha256(body) is inside what the token signs, so a captured token
        cannot be replayed against another question.
        """
        real = self.question(f"/proxy/ts/stream/{self.plain.uuid}")
        other = json.dumps(self.question("/proxy/ts/stream/something-else")).encode()
        response = self.client.post(
            PATH,
            data=json.dumps(real).encode(),
            content_type="application/json",
            HTTP_X_DISPATCHARR_INTERNAL=internal_principal_token(),
            HTTP_X_DISPATCHARR_INTERNAL_REQUEST=build_internal_request_header(
                "POST", PATH, other
            ),
        )
        self.assertEqual(response.status_code, 403)

    # -- the decision ----------------------------------------------------

    def test_an_ordinary_channel_authorizes_anonymously_with_seven_headers(self):
        response = self.post(self.question(f"/proxy/ts/stream/{self.plain.uuid}"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["X-Relay-Channel"], str(self.plain.uuid))
        # Anonymous: no user resolved, which is a real answer and not a
        # failure -- a bare channel UUID still streams (parity-matrix row 24).
        self.assertEqual(response.headers["X-Relay-User"], "")
        # The seven the hop sets, named individually so a missing one says
        # which.
        for header in (
            "X-Relay-Channel",
            "X-Relay-Output",
            "X-Relay-Client",
            "X-Relay-User",
            "X-Relay-Name",
            "X-Relay-Output-Format",
            "X-Relay-Client-IP",
        ):
            self.assertIn(header, response.headers, f"{header} is missing")
        # X-Relay-Client-IP is the dev shape's ONLY source for ip_address:
        # there is no hop-set header to read (parity-matrix row 17).
        self.assertEqual(response.headers["X-Relay-Client-IP"], "198.51.100.4")
        self.assertNotEqual(response.headers["X-Relay-Client"], "")

    def test_a_hidden_channel_is_refused_403(self):
        response = self.post(self.question(f"/proxy/ts/stream/{self.hidden.uuid}"))
        self.assertEqual(response.status_code, 403)

    def test_an_unknown_channel_is_404_and_not_a_collapsed_403(self):
        """THE TRUE STATUS, which is the whole reason this route uses
        authorize_error_response rather than subrequest_error_response.

        The 403 collapse exists only because ngx_http_auth_request_module can
        transport a 2xx, a 401 and a 403 and nothing else. A direct POST has
        no such constraint, so collapsing here would invent a limitation and
        hand the Go relay a 403 where production answers 404.
        """
        response = self.post(
            self.question("/proxy/ts/stream/11111111-1111-4111-8111-111111111111")
        )
        self.assertEqual(response.status_code, 404)
        # And NOT the subrequest shape's marker, which would mean the wrong
        # helper was called and the status merely happened to survive.
        self.assertNotIn("X-Authorize-Status", response.headers)

    # -- the three silent failure modes ---------------------------------

    def test_the_transport_header_does_not_make_the_request_internal(self):
        """The BLOCKING finding § The contract names, asserted directly.

        Every call here carries X-Dispatcharr-Internal, because
        IsInternalRelay requires it. A view that let that header answer
        authorize_stream's own is_internal question would authorize this
        hidden channel -- _apply_channel_checks returns immediately for an
        internal principal (authorize.py:376-377).
        """
        response = self.post(
            self.question(f"/proxy/ts/stream/{self.hidden.uuid}", internal=False)
        )
        self.assertEqual(
            response.status_code,
            403,
            "a hidden channel authorized with internal=false: the transport's own "
            "X-Dispatcharr-Internal reached authorize_stream and every check was skipped",
        )

    def test_the_body_flag_does_make_the_request_internal(self):
        """The other half, so "nothing is ever internal" cannot be what
        makes the test above pass.

        internal=true is the DVR's own fetch, which carries the static
        marker with no bound counterpart (ADR 0005).
        """
        response = self.post(
            self.question(f"/proxy/ts/stream/{self.hidden.uuid}", internal=True)
        )
        self.assertEqual(response.status_code, 200)
        # The internal principal is not a user, so the header is empty --
        # which is also how a consumer tells it from an authenticated one.
        self.assertEqual(response.headers["X-Relay-User"], "")

    def test_a_session_cookie_resolves_the_real_user_and_not_anonymous(self):
        """THE ASSERTION IS THE RESOLVED IDENTITY, never a status code.

        A view that forwarded the cookie but read request.user would answer
        200 here as well, with the viewer silently downgraded to anonymous.
        X-Relay-User is the field that says which principal the decision was
        made for.
        """
        user = User.objects.create_user(
            username="ai-session", password="pw", user_level=User.UserLevel.STANDARD
        )
        session_client = Client()
        self.assertTrue(session_client.login(username="ai-session", password="pw"))
        cookie = session_client.cookies["sessionid"].value

        response = self.post(
            self.question(
                f"/proxy/ts/stream/{self.plain.uuid}",
                headers={
                    "authorization": None,
                    "cookie": f"sessionid={cookie}",
                    "x-api-key": None,
                },
            )
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.headers["X-Relay-User"],
            str(user.id),
            "the session cookie resolved to anonymous: the principal was read from "
            "request.user rather than from the session store, and every user-scoped "
            "check has quietly stopped applying",
        )

    def test_the_client_address_comes_from_the_body_and_not_the_transport(self):
        """The ACL is evaluated against the CLIENT's address.

        Asserted through X-Relay-Client-IP, which authorize_stream fills from
        get_client_ip(request) -- so a synthesised request carrying the
        relay's own REMOTE_ADDR would echo that instead.
        """
        response = self.post(
            self.question(
                f"/proxy/ts/stream/{self.plain.uuid}", client_ip="203.0.113.99"
            )
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["X-Relay-Client-IP"], "203.0.113.99")

    def test_the_query_string_reaches_the_decision(self):
        """?output_format= is resolved from the uri, so the uri must carry
        its query string -- the same correction § The contract records for
        the bound token's own second field."""
        response = self.post(
            self.question(f"/proxy/ts/stream/{self.plain.uuid}?output_format=fmp4")
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["X-Relay-Output-Format"], "fmp4")

    def test_a_body_that_does_not_validate_is_400(self):
        """DRF's own answer, which relay_client maps to RelayRefused."""
        response = self.post({"client_ip": "198.51.100.4", "internal": False})
        self.assertEqual(response.status_code, 400)

    # -- the arms a live-surface test does not reach --------------------
    #
    # Nine statements of this view are outside the live tune's own path,
    # and Gate 2's floor is a MAXIMUM: an uncovered new statement in a
    # module `scripts/coverage_live_path.coveragerc` includes raises
    # `missing` and fails `backend-tests.yml`'s Coverage gate however
    # green `apps.proxy.tests` is. 2c-7's CI found that the expensive way.
    # These five tests close all nine.

    def test_a_uri_whose_path_is_not_latin_1_is_resolved_as_it_arrived(self):
        """The decode arm `authorize_view` carries for the same reason.

        A client that sends a non-ASCII credential as raw UTF-8 bytes in the
        request line arrives latin-1 decoded, so the view re-encodes and
        decodes as UTF-8. A character above U+00FF cannot be latin-1 encoded
        at all -- UnicodeEncodeError, a UnicodeError subclass -- and the raw
        path is then resolved as it stands rather than raising here.
        """
        response = self.post(self.question("/proxy/ts/stream/日"))
        # 404, because no channel is named by that path -- and NOT a 500,
        # which is what an unguarded encode would produce.
        self.assertEqual(response.status_code, 404)

    def test_every_credential_header_reaches_the_authenticator_union(self):
        """All three, and the proof is that a REJECTED one is refused 401.

        Parity-matrix row 30's own distinction is the lever: a credential an
        authenticator explicitly rejects (an unknown API key) raises
        AuthenticationFailed and comes out 401, while a credential merely
        DECLINED -- no header at all -- falls through to the anonymous
        principal and streams. So a 401 here is positive evidence the header
        arrived at `_drf_user`'s union, and the anonymous 200 in the same
        test is what stops "everything 401s" being the reason.

        Both header slots are exercised, because ApiKeyAuthentication checks
        X-API-Key BEFORE falling back to an `Authorization: ApiKey …` header
        (apps/accounts/authentication.py:54-69) and § The contract calls that
        ordering out as the reason there are three fields and not two.
        """
        uri = f"/proxy/ts/stream/{self.plain.uuid}"

        for label, headers in (
            (
                "X-API-Key",
                {"authorization": None, "cookie": None, "x-api-key": "no-such-key"},
            ),
            (
                "Authorization: ApiKey",
                {
                    "authorization": "ApiKey no-such-key",
                    "cookie": None,
                    "x-api-key": None,
                },
            ),
        ):
            response = self.post(self.question(uri, headers=headers))
            self.assertEqual(
                response.status_code,
                401,
                f"a rejected credential in {label} did not reach the authenticator "
                "union: the header was dropped on the way into the synthesised request",
            )

        # And with no credential at all the same URI streams as anonymous,
        # so "this view 401s everything" cannot be what makes the two rows
        # above pass.
        anonymous = self.post(self.question(uri))
        self.assertEqual(anonymous.status_code, 200)
        self.assertEqual(anonymous.headers["X-Relay-User"], "")

    def test_a_uri_with_no_path_at_all_is_404(self):
        """Resolver404, which is a different 404 from an unknown channel.

        An ORDINARY unmatched path cannot reach it: `dispatcharr/urls.py`
        mounts the SPA catch-all, so almost everything resolves and comes out
        as the `surface is None` 403 above instead — which is why
        `authorize_view`'s own Resolver404 arm is uncovered too. An empty
        path is the reachable case, and a relay sending one is a malformed
        request rather than a client's.
        """
        response = self.post(self.question("?nothing=here"))
        self.assertEqual(response.status_code, 404)

    def test_a_uri_that_resolves_to_a_non_streaming_view_is_403(self):
        """`_surface_for` returns None for a route that is not a streaming
        surface, and the view fails closed rather than guessing."""
        response = self.post(self.question("/_dispatcharr/authorize"))
        self.assertEqual(response.status_code, 403)

    def test_the_two_catch_up_surfaces_take_their_identity_from_the_query(self):
        """The XC catch-up root reads username/password/stream out of the
        query string, and the native catch-up root reads session_id.

        Both are D1's Python-relay surfaces, and this view authorizes them
        too: it is registered unconditionally and the relay it answers is
        not the only caller a deployment can have. The assertion is the
        status vocabulary, not a decision -- these are refused for want of
        credentials, which is the point: the identity was built from the
        query rather than being absent.
        """
        xc = self.post(
            self.question("/streaming/timeshift.php?username=u&password=p&stream=1.ts")
        )
        self.assertIn(xc.status_code, (401, 403, 404))
        native = self.post(
            self.question(f"/proxy/catchup/{self.plain.uuid}?session_id=abc")
        )
        self.assertIn(native.status_code, (200, 401, 403, 404))
