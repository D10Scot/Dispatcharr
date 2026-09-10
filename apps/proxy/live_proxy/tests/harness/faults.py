"""The fault vocabulary, ported from e2e-upstream/src/faults.ts.

e2e-upstream declares twelve faults (faults.ts:4-16). Eight are live-TS faults
and are reproduced here; four belong to surfaces Phase 2's D1 leaves in Python
(VOD, catch-up, the XC listing API) and are recorded in NOT_PORTED rather than
dropped, so 2c's Go fixtures can copy the whole vocabulary and see which four
were left behind and why.

Deliberately NOT a port of the TypeScript implementation: there is no scenario
id and no per-channel scope here. One FakeUpstream serves one channel in a
backend test, so a fault is either armed on that server or it is not.
"""

DEAD_AIR = "dead-air"
SLOW_TRICKLE = "slow-trickle"
DISCONNECT = "disconnect"
NOT_FOUND = "not-found"
AUTH_FAILURE = "auth-failure"
CONNECTION_LIMIT = "connection-limit"
REDIRECT_CHAIN = "redirect-chain"
NON_TS_BYTES = "non-ts-bytes"

PORTED_FAULTS: tuple[str, ...] = (
    DEAD_AIR,
    SLOW_TRICKLE,
    DISCONNECT,
    NOT_FOUND,
    AUTH_FAILURE,
    CONNECTION_LIMIT,
    REDIRECT_CHAIN,
    NON_TS_BYTES,
)

NOT_PORTED: dict[str, str] = {
    "xc-auth-envelope": (
        "shapes the XC player_api.php envelope, a listing surface the Go relay "
        "never serves (D1)"
    ),
    "no-tv-archive": "XC catch-up advertisement; catch-up stays Python (D1)",
    "catchup-layout-404": "catch-up URL layout; catch-up stays Python (D1)",
    "range-unsupported": "VOD Range handling; VOD stays Python (D1)",
}

# Defaults chosen to match e2e-upstream's own (faults.ts:75 DEFAULT_REDIRECT_DEPTH,
# and DEFAULT_TRICKLE_RATE = 0.1) so a fault armed the same way behaves the same
# way in both suites.
_DEFAULTS: dict[str, dict] = {
    DEAD_AIR: {},
    SLOW_TRICKLE: {"rate": 0.1},
    DISCONNECT: {"clean": False, "after_bytes": 0},
    NOT_FOUND: {},
    AUTH_FAILURE: {},
    CONNECTION_LIMIT: {},
    REDIRECT_CHAIN: {"depth": 2},
    NON_TS_BYTES: {},
}


class FaultStore:
    """Which faults are armed on one FakeUpstream, and with what configuration."""

    def __init__(self) -> None:
        self._armed: dict[str, dict] = {}

    def arm(self, fault: str, **config) -> None:
        if fault in NOT_PORTED:
            raise ValueError(f"{fault!r} is not ported to the backend harness: {NOT_PORTED[fault]}")
        if fault not in _DEFAULTS:
            raise ValueError(f"unknown fault {fault!r}; expected one of {', '.join(PORTED_FAULTS)}")
        unknown = set(config) - set(_DEFAULTS[fault])
        if unknown:
            raise ValueError(f"{fault!r} takes no option(s): {', '.join(sorted(unknown))}")
        merged = dict(_DEFAULTS[fault])
        merged.update(config)
        self._armed[fault] = merged

    def clear(self, fault: str) -> None:
        self._armed.pop(fault, None)

    def clear_all(self) -> None:
        self._armed.clear()

    def is_active(self, fault: str) -> bool:
        return fault in self._armed

    def config_of(self, fault: str) -> dict:
        return dict(self._armed.get(fault, {}))
