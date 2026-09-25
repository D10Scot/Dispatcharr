"""#171: `_transform_url`'s $N step must not inject a NUL or control byte.

`_transform_url` now routes its $N step through
`apps.m3u.utils.convert_js_numbered_backreferences` (JavaScript's own
$n/$nn grammar) instead of a raw `\\$(\\d+) -> \\1` rewrite, which read a
bare `$0` as the octal escape `\\0`.
"""
from types import SimpleNamespace

from django.test import SimpleTestCase

from apps.proxy.vod_proxy.views import _transform_url


class TransformUrlBackreferencesTests(SimpleTestCase):
    def test_vod_transform_dollar_zero_does_not_inject_nul_bytes(self):
        # Issue #171's shrunk counterexample. (.*)$ matches twice (the
        # whole string, then the empty tail), so a literal $0 template is
        # substituted in twice.
        m3u_profile = SimpleNamespace(search_pattern=r"(.*)$", replace_pattern="$0")

        result = _transform_url("/", m3u_profile)

        self.assertEqual(result, "$0$0")
        self.assertNotIn("\x00", result)
