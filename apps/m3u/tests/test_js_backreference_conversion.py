"""Regression tests for the JS-grammar $N backreference rewrite (#171).

Four copies of a JS-to-Python replacement-template rewrite exist:
``apps.m3u.utils.convert_js_numbered_backreferences`` (this module's
target, and the one this test class exercises directly),
``apps.proxy.next_source.transform_url``, ``apps.proxy.vod_proxy.views.
_transform_url`` and ``apps.m3u.tasks.get_transformed_credentials`` --
all four now call the shared helper for their ``$N`` step.

Under the old rule (``\\$(\\d+)`` -> ``\\1``), a bare ``$0`` became the
octal escape ``\\0`` (a NUL byte) and ``$01`` became ``\\01`` (``\\x01``),
silently corrupting the URL or credential the template was substituted
into. Under JavaScript's own ``$n``/``$nn`` grammar (``$1``-``$9``,
``$01``-``$99``; anything else, including a bare ``$0``, stays literal),
the SPA's own JS preview (``M3uProfileUtils.js:34-38``), the WebSocket
preview and the live transform all agree, and no NUL or control byte is
ever injected by a ``$0``/`$00`` template.
"""
import regex
from django.test import SimpleTestCase, TestCase

from apps.m3u.models import M3UAccount
from apps.m3u.tasks import get_transformed_credentials
from apps.m3u.utils import convert_js_numbered_backreferences


class ConvertJsNumberedBackreferencesTests(SimpleTestCase):
    def test_dollar_zero_is_a_literal_not_a_nul_byte(self):
        safe_replacement = convert_js_numbered_backreferences("[$0]")
        result = regex.sub("(a)", safe_replacement, "a")
        self.assertEqual(result, "[$0]")

    def test_dollar_leading_zero_group_is_the_group_not_an_octal_escape(self):
        safe_replacement = convert_js_numbered_backreferences("$02-$01")
        result = regex.sub(r"(h)/(u)", safe_replacement, "http://h/u/p/1.ts")
        self.assertEqual(result, "http://u-h/p/1.ts")

    def test_replacement_token_grammar_matches_javascript(self):
        """One subTest per case from the #171 analysis's parity table.

        Break-check: point the helper at ``\\$(0?[1-9]\\d?)`` instead of
        ``\\$(0[1-9]|[1-9]\\d?)``. The ``$012`` subTest must then redden
        with ``'l' != 'a2'`` -- the wrong rule reads ``$012`` as group 12
        (JavaScript reads it as group 1 followed by a literal ``2``).
        """
        pattern = r"(a)(b)(c)(d)(e)(f)(g)(h)(i)(j)(k)(l)"
        text = "abcdefghijkl"
        cases = [
            ("$001", "$001"),
            ("$0012", "$0012"),
            ("$012", "a2"),
            ("[$100]", "[j0]"),
        ]
        for replacement, expected in cases:
            with self.subTest(replacement=replacement):
                safe_replacement = convert_js_numbered_backreferences(replacement)
                result = regex.sub(pattern, safe_replacement, text)
                self.assertEqual(result, expected)


class GetTransformedCredentialsBackreferenceTests(TestCase):
    def test_get_transformed_credentials_dollar_zero_does_not_corrupt_the_url(self):
        account = M3UAccount.objects.create(
            name="c-4 backreference account",
            server_url="http://host.example:8080",
            username="myuser",
            password="mypass",
        )
        # The post_save signal creates the default profile; point its
        # transform at the username segment with a $0 template so a NUL
        # byte, if one leaked in, would land in the extracted username.
        profile = account.profiles.get(is_default=True)
        profile.search_pattern = "myuser"
        profile.replace_pattern = "$0-X"
        profile.save()

        _, transformed_username, transformed_password = get_transformed_credentials(
            account
        )

        self.assertNotIn("\x00", transformed_username)
        self.assertNotIn("\x00", transformed_password)
        self.assertIn("$0", transformed_username)
