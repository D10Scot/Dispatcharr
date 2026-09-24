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

    @patch("core.http_security.socket.getaddrinfo", return_value=_fake_addrinfo("93.184.216.34"))
    def test_allows_and_normalises_an_internationalised_hostname(self, mock_gai):
        # requests IDNA-encodes a non-ASCII host before dialling it
        # (xn--mnchen-3ya.example); urlparse leaves it as the raw unicode
        # 'münchen.example'. Comparing the two without encoding both sides
        # the same way falsely refuses every internationalised domain --
        # a regression for core.image_proxy and any other caller, not just
        # the plugin fetches (round 2 finding 1).
        validate_outbound_http_url("http://münchen.example/x.png", allow_private=True)
        mock_gai.assert_called_once_with("xn--mnchen-3ya.example", None)

    def test_a_refusal_message_never_carries_userinfo_or_a_query_token(self):
        # Round 2 finding 2, extended by round 3 finding 5: the
        # parser-differential refusal messages used to interpolate the
        # whole URL or netloc, which can carry a credential in userinfo or
        # a query string -- and scripts/check_credential_logging.py cannot
        # see inside a raised ValueError's message to catch that once it
        # reaches a response body or a log line. Parametrised over the four
        # distinct branches that can raise before a bare hostname is all
        # that is left to name, so a future message edit on any one of them
        # trips this test rather than only the branch someone happened to
        # think of:
        cases = {
            # urlparse() itself raises: a netloc character (fullwidth '@')
            # NFKC-normalises to '@', which urlparse refuses to parse
            # rather than silently reinterpreting -- round 3 finding 1.
            "urlparse_raises": "http://user:s3cret@public.example＠127.0.0.1/?token=abc",
            # The literal-backslash authority check.
            "backslash_authority": (
                r"http://user:s3cret@127.0.0.1:8765\@public.example/?token=abc"
            ),
            # urlparse and urllib3 parse a percent-encoded host label
            # differently ('%41.example' vs the decoded 'a.example'),
            # tripping the host-disagreement check.
            "host_disagreement": "http://user:s3cret@%41.example/?token=abc",
            # requests.Request(...).prepare() itself raises (a wildcard
            # host label is invalid per RFC 3986 and requests refuses it).
            "prepare_failure": "http://user:s3cret@*.example.com/?token=abc",
        }
        for case_name, url in cases.items():
            with self.subTest(case=case_name):
                with self.assertRaises(ValueError) as ctx:
                    validate_outbound_http_url(
                        url, allow_private=True, allow_loopback=True
                    )
                msg = str(ctx.exception)
                self.assertNotIn("s3cret", msg)
                self.assertNotIn("token=abc", msg)
                self.assertNotIn(url, msg)

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
            cookies={"session": "abc"},
            headers={
                "Authorization": "Bearer secret",
                "Cookie": "a=b",
                "X-Custom": "keep",
            },
        )

        first_kwargs = mock_get.call_args_list[0].kwargs
        second_kwargs = mock_get.call_args_list[1].kwargs
        self.assertEqual(first_kwargs.get("auth"), ("user", "pass"))
        self.assertEqual(first_kwargs.get("cookies"), {"session": "abc"})
        self.assertEqual(first_kwargs["headers"].get("Authorization"), "Bearer secret")
        self.assertNotIn("auth", second_kwargs)
        self.assertNotIn("cookies", second_kwargs)
        self.assertNotIn("Authorization", second_kwargs.get("headers", {}))
        self.assertNotIn("Cookie", second_kwargs.get("headers", {}))
        self.assertEqual(second_kwargs.get("headers", {}).get("X-Custom"), "keep")

    @patch("core.http_security.requests.get")
    @patch("core.http_security.socket.getaddrinfo")
    def test_auth_and_cookies_are_dropped_on_an_https_to_http_downgrade(
        self, mock_gai, mock_get
    ):
        # requests.Session.should_strip_auth strips on ANY scheme change
        # except the http-to-https upgrade at default ports (the next test)
        # -- a same-host https-to-http downgrade must still strip, or a
        # credential meant for an encrypted connection is replayed in the
        # clear (round 2 finding 3).
        mock_gai.side_effect = _addrinfo_side_effect(
            {"public.example": "93.184.216.34"}
        )
        first = MagicMock(
            status_code=302, headers={"Location": "http://public.example/next"}
        )
        second = MagicMock(status_code=200, headers={})
        mock_get.side_effect = [first, second]

        fetch_outbound_http(
            "https://public.example/m.json",
            auth=("user", "pass"),
            cookies={"session": "abc"},
        )

        second_kwargs = mock_get.call_args_list[1].kwargs
        self.assertNotIn("auth", second_kwargs)
        self.assertNotIn("cookies", second_kwargs)

    @patch("core.http_security.requests.get")
    @patch("core.http_security.socket.getaddrinfo")
    def test_auth_is_dropped_on_a_port_change(self, mock_gai, mock_get):
        mock_gai.side_effect = _addrinfo_side_effect(
            {"public.example": "93.184.216.34"}
        )
        first = MagicMock(
            status_code=302,
            headers={"Location": "http://public.example:8080/next"},
        )
        second = MagicMock(status_code=200, headers={})
        mock_get.side_effect = [first, second]

        fetch_outbound_http("http://public.example/m.json", auth=("user", "pass"))

        second_kwargs = mock_get.call_args_list[1].kwargs
        self.assertNotIn("auth", second_kwargs)

    @patch("core.http_security.requests.get")
    @patch("core.http_security.socket.getaddrinfo")
    def test_auth_is_kept_on_an_http_to_https_upgrade_at_default_ports(
        self, mock_gai, mock_get
    ):
        # The one exemption requests.Session.should_strip_auth carries,
        # kept for backwards compatibility: upgrading to https on the
        # standard ports is not treated as a new origin.
        mock_gai.side_effect = _addrinfo_side_effect(
            {"public.example": "93.184.216.34"}
        )
        first = MagicMock(
            status_code=302, headers={"Location": "https://public.example/next"}
        )
        second = MagicMock(status_code=200, headers={})
        mock_get.side_effect = [first, second]

        fetch_outbound_http("http://public.example/m.json", auth=("user", "pass"))

        second_kwargs = mock_get.call_args_list[1].kwargs
        self.assertEqual(second_kwargs.get("auth"), ("user", "pass"))

    @patch("core.http_security.requests.get")
    @patch("core.http_security.socket.getaddrinfo")
    def test_params_are_not_resent_on_a_later_hop(self, mock_gai, mock_get):
        # requests bakes `params` into hop 0's URL once and then follows a
        # redirect's Location literally; it never re-appends them. Calling
        # requests.get fresh on every hop with the same kwargs would append
        # the same query string to every Location too, unless dropped
        # (round 3 finding 4).
        mock_gai.side_effect = _addrinfo_side_effect(
            {"public.example": "93.184.216.34"}
        )
        first = MagicMock(status_code=302, headers={"Location": "/next"})
        second = MagicMock(status_code=200, headers={})
        mock_get.side_effect = [first, second]

        fetch_outbound_http(
            "http://public.example/m.json", params={"token": "abc"}
        )

        first_kwargs = mock_get.call_args_list[0].kwargs
        second_kwargs = mock_get.call_args_list[1].kwargs
        self.assertEqual(first_kwargs.get("params"), {"token": "abc"})
        self.assertNotIn("params", second_kwargs)
