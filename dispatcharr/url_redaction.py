"""The three constants of URL credential redaction, in a stdlib-only leaf module.

``dispatcharr/utils.py`` imports ``django.http`` and ``core.models``, so the log
scrubber (``dispatcharr/log_scrub.py``), which is imported before Django settings
exist, cannot import it. ``utils`` re-exports all three names; nothing else moved
and ``redact_url`` is unchanged. Keep this module free of any non-stdlib import
(``tests/test_url_redaction_leaf.py`` enforces it).
"""

REDACTED = "***"

# Query parameter names whose *values* are masked (compared case-insensitively,
# after percent-decoding the name).
SENSITIVE_QUERY_KEYS = frozenset(
    {
        "password",
        "username",
        "token",
        "api_key",
        # OIDC (SSO spec 3.3): an authorization code, the state that redeems it, and every
        # token or client credential the flow handles.
        "code",
        "state",
        "session_state",
        "id_token",
        "access_token",
        "refresh_token",
        "client_secret",
        "client_assertion",
        "code_verifier",
    }
)

# Path segments after which the next two segments are the Xtream username and
# password. Matched anywhere in the path, because a provider's server URL may
# carry a sub-path before /live/ (see apps/m3u/tasks.py).
XTREAM_PATH_PREFIXES = frozenset({"live", "movie", "series", "timeshift"})
