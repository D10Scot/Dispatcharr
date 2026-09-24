from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase

from core.http_security import fetch_outbound_http, validate_outbound_http_url


def _fake_addrinfo(*addrs):
    """Build getaddrinfo-style results for the given IP strings."""
    results = []
    for addr in addrs:
        # sockaddr is (ip, port) for AF_INET; port unused by validator.
        results.append((None, None, None, None, (addr, 0)))
    return results


class ValidateOutboundHttpUrlTests(SimpleTestCase):
    def test_rejects_non_http_schemes(self):
        with self.assertRaises(ValueError):
            validate_outbound_http_url("ftp://example.com/x")

    def test_rejects_missing_hostname(self):
        with self.assertRaises(ValueError):
            validate_outbound_http_url("http:///nohost")

    @patch("core.http_security.socket.getaddrinfo", return_value=_fake_addrinfo("93.184.216.34"))
    def test_allows_public_address(self, _mock_gai):
        validate_outbound_http_url("https://cdn.example.com/a.png")

    @patch("core.http_security.socket.getaddrinfo", return_value=_fake_addrinfo("192.168.1.10"))
    def test_rejects_private_by_default(self, _mock_gai):
        with self.assertRaises(ValueError):
            validate_outbound_http_url("http://nas.local/logo.png")

    @patch("core.http_security.socket.getaddrinfo", return_value=_fake_addrinfo("192.168.1.10"))
    def test_allows_private_when_enabled(self, _mock_gai):
        validate_outbound_http_url(
            "http://nas.local/logo.png",
            allow_private=True,
        )

    @patch("core.http_security.socket.getaddrinfo", return_value=_fake_addrinfo("127.0.0.1"))
    def test_rejects_loopback_even_when_private_allowed(self, _mock_gai):
        with self.assertRaises(ValueError):
            validate_outbound_http_url(
                "http://127.0.0.1/logo.png",
                allow_private=True,
            )

    @patch("core.http_security.socket.getaddrinfo", return_value=_fake_addrinfo("169.254.169.254"))
    def test_rejects_link_local_metadata(self, _mock_gai):
        with self.assertRaises(ValueError):
            validate_outbound_http_url(
                "http://169.254.169.254/latest/meta-data/",
                allow_private=True,
            )

    @patch("core.http_security.socket.getaddrinfo", return_value=_fake_addrinfo("127.0.0.1"))
    def test_allows_loopback_when_enabled(self, _mock_gai):
        validate_outbound_http_url(
            "http://127.0.0.1/logo.png",
            allow_loopback=True,
        )

    def test_rejects_a_backslash_authority_before_resolving_any_host(self):
        # urlparse reads http://127.0.0.1:8765\@public.example/'s host as
        # 'public.example' (everything after the last '@' in the netloc),
        # but requests/urllib3 -- what actually opens the connection -- read
        # the authority as ending at the backslash and dial '127.0.0.1'.
        # _validate_fetch_url (apps/plugins/api_views.py) and
        # core.image_proxy call this function directly on a first hop, with
        # no redirect loop around it, so the refusal has to live here rather
        # than only in fetch_outbound_http's loop. Assert getaddrinfo was
        # never reached, proving the refusal fires before any DNS lookup --
        # let alone a connection -- to either candidate host.
        with patch("core.http_security.socket.getaddrinfo") as mock_gai:
            with self.assertRaises(ValueError):
                validate_outbound_http_url(
                    r"http://127.0.0.1:8765\@public.example/",
                    allow_private=False,
                    allow_loopback=False,
                )
            mock_gai.assert_not_called()


def _addrinfo_side_effect(mapping):
    """A getaddrinfo side_effect keyed by hostname, for a multi-hop fetch."""

    def _side_effect(host, *args, **kwargs):
        try:
            addr = mapping[host]
        except KeyError:
            raise AssertionError(f"unexpected getaddrinfo for {host!r}")
        return _fake_addrinfo(addr)

    return _side_effect


class FetchOutboundHttpTests(SimpleTestCase):
    @patch("core.http_security.requests.get")
    @patch("core.http_security.socket.getaddrinfo")
    def test_a_redirect_to_link_local_was_followed_after_a_validated_first_hop(
        self, mock_gai, mock_get
    ):
        mock_gai.side_effect = _addrinfo_side_effect(
            {
                "public.example": "93.184.216.34",
                "169.254.169.254": "169.254.169.254",
            }
        )
        redirect = MagicMock(
            status_code=302, headers={"Location": "http://169.254.169.254/latest/"}
        )
        mock_get.return_value = redirect

        with self.assertRaises(ValueError):
            fetch_outbound_http("http://public.example/m.json")

        self.assertEqual(mock_get.call_count, 1)

    @patch("core.http_security.requests.get")
    @patch("core.http_security.socket.getaddrinfo")
    def test_a_relative_redirect_is_resolved_against_the_current_hop(
        self, mock_gai, mock_get
    ):
        mock_gai.side_effect = _addrinfo_side_effect(
            {"public.example": "93.184.216.34"}
        )
        first = MagicMock(status_code=302, headers={"Location": "/next"})
        second = MagicMock(status_code=200, headers={})
        mock_get.side_effect = [first, second]

        result = fetch_outbound_http("http://public.example/m.json")

        self.assertIs(result, second)
        self.assertEqual(
            [call.args[0] for call in mock_get.call_args_list],
            ["http://public.example/m.json", "http://public.example/next"],
        )

    @patch("core.http_security.requests.get")
    @patch("core.http_security.socket.getaddrinfo")
    def test_every_hop_is_requested_with_allow_redirects_false(
        self, mock_gai, mock_get
    ):
        mock_gai.side_effect = _addrinfo_side_effect(
            {"public.example": "93.184.216.34"}
        )
        first = MagicMock(status_code=302, headers={"Location": "/next"})
        second = MagicMock(status_code=200, headers={})
        mock_get.side_effect = [first, second]

        fetch_outbound_http("http://public.example/m.json", timeout=5)

        self.assertEqual(mock_get.call_count, 2)
        for call in mock_get.call_args_list:
            self.assertIs(call.kwargs.get("allow_redirects"), False)
            self.assertEqual(call.kwargs.get("timeout"), 5)

    @patch("core.http_security.requests.get")
    @patch("core.http_security.socket.getaddrinfo")
    def test_more_than_max_redirects_is_refused(self, mock_gai, mock_get):
        mock_gai.side_effect = _addrinfo_side_effect(
            {"public.example": "93.184.216.34"}
        )
        redirect = MagicMock(
            status_code=302, headers={"Location": "http://public.example/m.json"}
        )
        mock_get.return_value = redirect

        with self.assertRaises(ValueError):
            fetch_outbound_http("http://public.example/m.json", max_redirects=5)

        self.assertEqual(mock_get.call_count, 6)

    @patch("core.http_security.requests.get")
    @patch("core.http_security.socket.getaddrinfo")
    def test_a_redirect_to_a_backslash_authority_is_refused_as_the_host_it_would_dial(
        self, mock_gai, mock_get
    ):
        # Same parser differential as
        # ValidateOutboundHttpUrlTests.test_rejects_a_backslash_authority_before_resolving_any_host,
        # but reached through a redirect (hop 1) rather than the URL a
        # caller supplies directly (hop 0) -- the loop must re-run the same
        # check on every Location, not just the one it started with.
        mock_gai.side_effect = _addrinfo_side_effect(
            {"public.example": "93.184.216.34"}
        )
        redirect = MagicMock(
            status_code=302,
            headers={"Location": r"http://127.0.0.1:5656\@public.example/"},
        )
        mock_get.return_value = redirect

        with self.assertRaises(ValueError):
            fetch_outbound_http("http://public.example/m.json")

        # Exactly one request (hop 0): hop 1 was refused before any request
        # was made for it, not merely eventually bounded by max_redirects.
        self.assertEqual(mock_get.call_count, 1)

    @patch("core.http_security.requests.get")
    @patch("core.http_security.socket.getaddrinfo")
    def test_a_redirect_to_a_private_address_is_refused_with_allow_private_false(
        self, mock_gai, mock_get
    ):
        # Pins that the caller's *own* flags reach hop >= 1, not just hop 0.
        # Without this, a helper that silently loosened validation after the
        # first hop would pass every other test in this file: the only other
        # hop-2 refusal test (test_a_redirect_to_link_local_was_followed_...)
        # uses a link-local address, which is refused under any flag value.
        mock_gai.side_effect = _addrinfo_side_effect(
            {"public.example": "93.184.216.34", "internal.example": "10.0.0.5"}
        )
        redirect = MagicMock(
            status_code=302, headers={"Location": "http://internal.example/"}
        )
        mock_get.return_value = redirect

        with self.assertRaises(ValueError) as ctx:
            fetch_outbound_http("http://public.example/m.json", allow_private=False)

        # The message names the refused address, not a hop-count bound --
        # proof the request was never made rather than merely eventually
        # capped by max_redirects.
        self.assertIn("10.0.0.5", str(ctx.exception))
        self.assertNotIn("redirect", str(ctx.exception).lower())
        self.assertEqual(mock_get.call_count, 1)

    @patch("core.http_security.requests.get")
    @patch("core.http_security.socket.getaddrinfo")
    def test_a_redirect_to_a_private_address_is_followed_with_allow_private_true(
        self, mock_gai, mock_get
    ):
        mock_gai.side_effect = _addrinfo_side_effect(
            {"public.example": "93.184.216.34", "internal.example": "10.0.0.5"}
        )
        first = MagicMock(
            status_code=302, headers={"Location": "http://internal.example/"}
        )
        second = MagicMock(status_code=200, headers={})
        mock_get.side_effect = [first, second]

        result = fetch_outbound_http(
            "http://public.example/m.json", allow_private=True
        )

        self.assertIs(result, second)
        self.assertEqual(mock_get.call_count, 2)

    @patch("core.http_security.requests.get")
    @patch("core.http_security.socket.getaddrinfo")
    def test_a_redirect_to_loopback_is_refused_with_allow_loopback_false_even_when_private_is_allowed(
        self, mock_gai, mock_get
    ):
        mock_gai.side_effect = _addrinfo_side_effect(
            {"public.example": "93.184.216.34", "127.0.0.1": "127.0.0.1"}
        )
        redirect = MagicMock(status_code=302, headers={"Location": "http://127.0.0.1/"})
        mock_get.return_value = redirect

        with self.assertRaises(ValueError) as ctx:
            fetch_outbound_http(
                "http://public.example/m.json",
                allow_private=True,
                allow_loopback=False,
            )

        self.assertIn("127.0.0.1", str(ctx.exception))
        self.assertNotIn("redirect", str(ctx.exception).lower())
        self.assertEqual(mock_get.call_count, 1)

    @patch("core.http_security.requests.get")
    @patch("core.http_security.socket.getaddrinfo")
    def test_auth_and_sensitive_headers_are_dropped_on_a_cross_host_redirect(
        self, mock_gai, mock_get
    ):
        mock_gai.side_effect = _addrinfo_side_effect(
            {"public.example": "93.184.216.34", "other.example": "93.184.216.35"}
        )
        first = MagicMock(
            status_code=302, headers={"Location": "http://other.example/next"}
        )
        second = MagicMock(status_code=200, headers={})
        mock_get.side_effect = [first, second]

        fetch_outbound_http(
            "http://public.example/m.json",
            auth=("user", "pass"),
            headers={
                "Authorization": "Bearer secret",
                "Cookie": "a=b",
                "X-Custom": "keep",
            },
        )

        first_kwargs = mock_get.call_args_list[0].kwargs
        second_kwargs = mock_get.call_args_list[1].kwargs
        self.assertEqual(first_kwargs.get("auth"), ("user", "pass"))
        self.assertEqual(first_kwargs["headers"].get("Authorization"), "Bearer secret")
        self.assertNotIn("auth", second_kwargs)
        self.assertNotIn("Authorization", second_kwargs.get("headers", {}))
        self.assertNotIn("Cookie", second_kwargs.get("headers", {}))
        self.assertEqual(second_kwargs.get("headers", {}).get("X-Custom"), "keep")
