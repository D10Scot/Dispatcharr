"""The stage-2a subprocess harness.

Every spawn in this harness is a real child process created by the relay's own
unmodified os.posix_spawn call sites. What that child *runs* is chosen through
two production mechanisms -- a StreamProfile row's `command`, and PATH -- so the
harness needs no seam, no patch and no production-code change. See README.md.
"""

from .asset import TS_PACKET_SIZE, TS_SYNC_BYTE, assert_ts_aligned, synthetic_ts
from .faults import NOT_PORTED, PORTED_FAULTS, FaultStore

__all__ = [
    "TS_PACKET_SIZE",
    "TS_SYNC_BYTE",
    "assert_ts_aligned",
    "synthetic_ts",
    "NOT_PORTED",
    "PORTED_FAULTS",
    "FaultStore",
]
