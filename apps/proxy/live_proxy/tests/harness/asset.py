"""A synthetic MPEG-TS asset, and the TS-shape assertions tests make about it.

Synthetic rather than ffmpeg-produced on purpose: nothing on the live path
decodes video. input/buffer.py realigns on the 0x47 sync byte at a 188-byte
stride and the ring buffer carries whatever it is given, so a structurally
valid transport stream is exactly as useful here as a real encode, costs no
ffmpeg, and is byte-for-byte deterministic. Where a REAL remuxer's output is
required -- the fMP4 path, which parses moof/moov boxes -- use
build_real_ts_asset() instead; that is 2a-6's territory.
"""

TS_PACKET_SIZE = 188
TS_SYNC_BYTE = 0x47


def synthetic_ts(packets: int = 512, pid: int = 0x100) -> bytes:
    """`packets` transport-stream packets on `pid`, with a real continuity counter.

    Each packet is: 0x47, then the 13-bit PID split across two bytes with the
    payload-unit-start flag clear, then 0x10 | (counter % 16) -- adaptation
    field control 01 (payload only) in the high nibble, the continuity counter
    in the low one -- then 184 bytes of a repeating, position-derived pattern so
    a test can tell one packet from another.
    """
    if packets < 1:
        raise ValueError("packets must be >= 1")
    if not 0 <= pid <= 0x1FFF:
        raise ValueError("pid must fit in 13 bits")

    out = bytearray()
    for i in range(packets):
        out.append(TS_SYNC_BYTE)
        out.append((pid >> 8) & 0x1F)
        out.append(pid & 0xFF)
        out.append(0x10 | (i % 16))
        out.extend(bytes((i + j) % 256 for j in range(TS_PACKET_SIZE - 4)))
    return bytes(out)


def assert_ts_aligned(data: bytes) -> None:
    """Fail unless `data` is a whole number of packets, each starting with 0x47."""
    if not data:
        raise AssertionError("no bytes at all")
    if len(data) % TS_PACKET_SIZE:
        raise AssertionError(
            f"{len(data)} bytes is not a whole number of {TS_PACKET_SIZE}-byte packets"
        )
    for offset in range(0, len(data), TS_PACKET_SIZE):
        if data[offset] != TS_SYNC_BYTE:
            raise AssertionError(
                f"byte {offset} is {data[offset]:#04x}, not the sync byte {TS_SYNC_BYTE:#04x}"
            )
