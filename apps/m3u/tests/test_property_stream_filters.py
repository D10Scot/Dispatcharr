"""Property tests for M3U stream filtering (issue #145; seam #262).

Surfaces, with their line at seed a54b09a9:

- ``_compile_m3u_stream_filters`` (``apps/m3u/tasks.py:1017``)
- ``_stream_passes_m3u_filters`` (``apps/m3u/tasks.py:1030``): the first
  filter whose target field matches decides the outcome, as
  ``not filter.exclude``. A stream that no filter matches passes.

The oracle is stdlib ``re`` over a fixed set of benign patterns, on which
``re`` and ``regex`` agree, applied by a first-match loop written here. The
properties survive C-3's #262 change, which moves compilation to ``regex``
with a per-search timeout and keeps ``.search`` and ``.pattern`` on the
compiled object. They assert nothing about timing. They generate no
pathological pattern, because C-3 makes a timed-out filter non-matching and
that is C-3's own example test to pin.
"""

import re
from types import SimpleNamespace

from django.test import SimpleTestCase
from hypothesis import given, settings as hyp_settings, strategies as st

from apps.m3u.tasks import _compile_m3u_stream_filters, _stream_passes_m3u_filters

# CI-deterministic profile, byte-identical to tests/test_redaction.py's. derandomize=True seeds each
# test from a hash of its own source and implies database=None (hypothesis/_settings.py), so
# nothing is written to .hypothesis/ on the read-only /repo mount and every CI run draws the same
# examples. deadline=None: CI containers are loaded and a timing deadline would flake.
hyp_settings.register_profile(
    "dispatcharr-ci", max_examples=200, derandomize=True, deadline=None
)
hyp_settings.load_profile("dispatcharr-ci")

PATTERNS = ["news", "Sport", "hd$", "^uk", r"\d+", "adult|xxx", "[A-Z]{2}", "x"]
fields = st.none() | st.text(alphabet="newsSportHDhduUkKaltxXX0123 |/:.", max_size=30)
filters = st.builds(
    SimpleNamespace,
    filter_type=st.sampled_from(("name", "url", "group", "other")),
    exclude=st.booleans(),
    regex_pattern=st.sampled_from(PATTERNS),
    custom_properties=st.sampled_from(
        (None, {}, {"case_sensitive": True}, {"case_sensitive": False})
    ),
)


def _expected(name, url, group, filter_objs):
    """First-match-decides, re-derived from the documented contract."""
    for f in filter_objs:
        flags = re.IGNORECASE if (f.custom_properties or {}).get("case_sensitive", True) is False else 0
        target = {"url": url, "group": group}.get(f.filter_type, name)
        if re.search(f.regex_pattern, target or "", flags):
            return not f.exclude
    return True


class StreamPassesM3UFiltersProperties(SimpleTestCase):
    @given(name=fields, url=fields, group=fields)
    def test_with_no_filters_every_stream_passes(self, name, url, group):
        self.assertIs(_stream_passes_m3u_filters(name, url, group, []), True)

    @given(name=fields, url=fields, group=fields, filter_objs=st.lists(filters, min_size=1, max_size=4))
    def test_the_first_matching_filter_decides_by_its_exclude_flag(self, name, url, group, filter_objs):
        compiled = _compile_m3u_stream_filters(filter_objs)
        self.assertEqual(
            _stream_passes_m3u_filters(name, url, group, compiled),
            _expected(name, url, group, filter_objs),
        )

    @given(name=fields, url=fields, group=fields, filter_objs=st.lists(filters, min_size=1, max_size=4))
    def test_include_only_filters_never_reject(self, name, url, group, filter_objs):
        for f in filter_objs:
            f.exclude = False
        compiled = _compile_m3u_stream_filters(filter_objs)
        self.assertIs(_stream_passes_m3u_filters(name, url, group, compiled), True)
