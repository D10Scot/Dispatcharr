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
