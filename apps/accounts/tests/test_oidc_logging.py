"""No OIDC secret reaches a log line or a SystemEvent (SSO spec 3.3, 7; T16, T17).

Logs are captured by a recording handler on each configured logger (``apps``, ``core``,
``core.utils``, ``django`` and the root), because ``apps`` and ``core.utils`` do not
propagate; an empty capture is a pass.
"""

import json
from unittest import mock

import requests
from rest_framework.test import APIClient

from apps.accounts.models import User
from core.models import SystemEvent

from .oidc_flow_support import (
    FlowTestCase,
    capture_all_logs,
    fragment_code,
    query_of,
    sso_error,
)
from .oidc_support import SECRET_SENTINEL

SUB_SENTINEL = "SENTINEL-SUBJECT-5d1e"
DESCRIPTION_SENTINEL = "SENTINEL-ERROR-DESCRIPTION-9c2b"


class OidcLoggingTests(FlowTestCase):
    def setUp(self):
        super().setUp()
        self.provider = self.make_flow_provider()
        self.sentinels = {"client secret": SECRET_SENTINEL, "sub": SUB_SENTINEL, "error_description": DESCRIPTION_SENTINEL}

    def note(self, name, value):
        if value:
            self.sentinels[f"{name} #{len(self.sentinels)}"] = value

    def run_flow(self, client, claims=None, *, exchange=True):
        """A whole flow, recording every secret value it produced."""
        url = self.start(client, self.provider)
        query = query_of(url)
        self.note("state", query["state"])
        self.note("nonce", query["nonce"])
        params = self.op.authorize(url, claims or {"roles": ["staff"], "sub": SUB_SENTINEL})
        self.note("code", params["code"])
        self.note("id token", self.op.codes.get(params["code"], {}).get("id_token"))
        response = self.callback(client, self.provider, params)
        for request in self.op.token_requests:
            self.note("code verifier", request["form"].get("code_verifier"))
        if exchange and sso_error(response) is None:
            self.note("handoff code", fragment_code(response["Location"]))
            body = self.exchange(client, response).json()
            self.note("access token", body["access"])
            self.note("refresh token", body["refresh"])
        return response

    def test_no_sentinel_in_any_logger(self):
        with capture_all_logs() as logs:
            # A happy callback, with preferred_username and email both absent.
            self.assertIsNone(sso_error(self.run_flow(APIClient())))
            # A token endpoint 500.
            self.op.token_response = (500, {"error": "server_error", "error_description": DESCRIPTION_SENTINEL})
            self.assertEqual(sso_error(self.run_flow(APIClient())), "token_exchange_failed")
            self.op.token_response = None
            # A token endpoint connection error.
            with mock.patch("requests.post", side_effect=requests.ConnectionError(f"refused {SECRET_SENTINEL}")):
                self.assertEqual(sso_error(self.run_flow(APIClient())), "token_exchange_failed")
            # The IdP's error, with a free-text description.
            client = APIClient()
            url = self.start(client, self.provider)
            state = query_of(url)["state"]
            self.note("state", state)
            response = self.callback(
                client, self.provider,
                {"state": state, "error": "access_denied", "error_description": DESCRIPTION_SENTINEL},
            )
            self.assertEqual(sso_error(response), "idp_error")

        self.assertGreater(len(self.sentinels), 10)
        for logger_name, text in logs:
            for what, value in self.sentinels.items():
                self.assertNotIn(value, text, f"the {what} sentinel reached logger {logger_name!r}: {text[:200]!r}")

    def test_no_sentinel_in_any_event(self):
        self.assertIsNone(sso_error(self.run_flow(APIClient())))
        username = User.objects.get().username
        self.assertRegex(username, r"^sso-[0-9a-f]{8}$")
        for claims, expected in (
            ({"roles": ["nothing"], "sub": SUB_SENTINEL}, "no_mapping"),
            ({"roles": ["staff"], "sub": SUB_SENTINEL, "nonce": "wrong"}, "id_token_invalid"),
        ):
            self.assertEqual(sso_error(self.run_flow(APIClient(), claims)), expected)
        self.op.token_response = (401, {"error": "invalid_client", "error_description": DESCRIPTION_SENTINEL})
        self.assertEqual(sso_error(self.run_flow(APIClient())), "client_auth_failed")

        events = list(SystemEvent.objects.filter(event_type__in=["login_success", "login_failed"]))
        self.assertGreaterEqual(len(events), 4)
        success = [e for e in events if e.event_type == "login_success"]
        self.assertEqual(success[0].details["user"], username)
        self.assertEqual(success[0].details["method"], "oidc")
        for event in events:
            text = json.dumps(event.details)
            for what, value in self.sentinels.items():
                self.assertNotIn(value, text, f"the {what} sentinel is in a {event.event_type} event: {text}")
            self.assertLessEqual(
                set(event.details), {"user", "client_ip", "user_agent", "method", "provider", "reason", "idp_error", "admin"},
                text,
            )
