"""#57: an `/api/…` path the `apps.api.urls` urlconf does not match falls
through Django's resolver to the SPA catch-all patterns (`dispatcharr/urls.py`
`:97-98`) and answers 200 with `index.html`, instead of a 404. That includes
`/api/` itself, which has no root route of its own.

This matters beyond an unhelpful 200: `apps/proxy/authorize_views.py`'s
`_surface_for()` resolves a tune's `X-Original-URI` through this same
resolver and keys on the matched view's `__name__` to decide which
authorization rules apply. An unmatched `/api/…` URI resolving to
`TemplateView` (the SPA shell's view) rather than a dedicated 404 view is
incidentally harmless for that check — neither is a streaming surface — but
it is still the wrong behaviour for every other `/api/` client, browser and
tooling alike, all of which read a 200 as success.
"""

from django.test import SimpleTestCase
from django.urls import resolve
from django.views.generic import TemplateView


class UnmatchedApiPathsTests(SimpleTestCase):
    def test_unmatched_api_paths_resolve_to_a_404_not_the_spa(self):
        for path in ("/api/does-not-exist/", "/api/channels/does-not-exist/"):
            match = resolve(path)
            self.assertEqual(
                match.func.__name__,
                "api_not_found",
                f"{path} resolved to {match.func.__name__!r}, not api_not_found "
                "-- it is falling through to the SPA catch-all",
            )

    def test_unmatched_api_path_answers_json_404(self):
        for path in ("/api/does-not-exist/", "/api/channels/does-not-exist/"):
            response = self.client.get(path)
            self.assertEqual(response.status_code, 404)
            self.assertEqual(response["Content-Type"], "application/json")
            self.assertEqual(response.json(), {"detail": "Not found."})

    def test_spa_routes_and_real_api_routes_are_unchanged(self):
        # Control: a non-API SPA route still serves the React shell...
        spa_match = resolve("/channels")
        self.assertEqual(getattr(spa_match.func, "view_class", None), TemplateView)

        # ...and a real API route still resolves to its own viewset, not the
        # new catch-all.
        api_match = resolve("/api/channels/channels/")
        self.assertNotEqual(api_match.func.__name__, "api_not_found")
