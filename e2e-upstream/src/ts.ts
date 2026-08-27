export const TS_PACKET_SIZE = 188;
export const TS_SYNC_BYTE = 0x47;
/** Null packets carry no continuity obligation and must not be renumbered. */
export const NULL_PID = 0x1fff;

export function pidOf(packet: Buffer): number {
  return ((packet[1] & 0x1f) << 8) | packet[2];
}

function adaptationFieldControl(packet: Buffer): number {
  return (packet[3] >> 4) & 0x03;
}

export function hasPayload(packet: Buffer): boolean {
  const afc = adaptationFieldControl(packet);
  return afc === 0b01 || afc === 0b11;
}

export function hasAdaptationField(packet: Buffer): boolean {
  const afc = adaptationFieldControl(packet);
  return afc === 0b10 || afc === 0b11;
}

export function payloadUnitStart(packet: Buffer): boolean {
  return (packet[1] & 0x40) !== 0;
}

export function payloadOffset(packet: Buffer): number {
  if (!hasPayload(packet)) return -1;
  if (!hasAdaptationField(packet)) return 4;
  const offset = 5 + packet[4];
  if (offset > TS_PACKET_SIZE) return -1;
  return offset;
}

/**
 * PCR base is 33 bits at 90 kHz — the same clock as PTS/DTS — spanning bytes
 * 6..10 (bit 7 of byte 10 is its least significant bit). The 9-bit 27 MHz
 * extension that follows is deliberately not touched by any of this: adding a
 * whole-loop offset at 90 kHz leaves it correct.
 */
export function readPcrBase(packet: Buffer): bigint | null {
  if (!hasAdaptationField(packet)) return null;
  // The PCR itself needs 6 bytes after the 1-byte flags field, and the
  // adaptation field as declared must actually fit in the packet.
  if (packet[4] < 7) return null;
  if (5 + packet[4] > TS_PACKET_SIZE) return null;
  if ((packet[5] & 0x10) === 0) return null;

  return (
    (BigInt(packet[6]) << 25n) |
    (BigInt(packet[7]) << 17n) |
    (BigInt(packet[8]) << 9n) |
    (BigInt(packet[9]) << 1n) |
    (BigInt(packet[10]) >> 7n)
  );
}

export function writePcrBase(packet: Buffer, base: bigint): void {
  const value = base & 0x1ffffffffn;
  packet[6] = Number((value >> 25n) & 0xffn);
  packet[7] = Number((value >> 17n) & 0xffn);
  packet[8] = Number((value >> 9n) & 0xffn);
  packet[9] = Number((value >> 1n) & 0xffn);
  // Only bit 7 belongs to the base; the rest is reserved bits and the top bit
  // of the extension, so mask them through untouched.
  packet[10] = (packet[10] & 0x7f) | (Number(value & 0x01n) << 7);
}

/**
 * A PTS or DTS: 33 bits spread across 5 bytes, interleaved with a 4-bit
 * prefix and three marker bits that must stay set.
 */
export function readTimestamp(buffer: Buffer, offset: number): bigint {
  const b0 = (BigInt(buffer[offset]) >> 1n) & 0x07n;
  const b1 = BigInt(buffer[offset + 1]);
  const b2 = (BigInt(buffer[offset + 2]) >> 1n) & 0x7fn;
  const b3 = BigInt(buffer[offset + 3]);
  const b4 = (BigInt(buffer[offset + 4]) >> 1n) & 0x7fn;

  return (b0 << 30n) | (b1 << 22n) | (b2 << 15n) | (b3 << 7n) | b4;
}

export function writeTimestamp(
  buffer: Buffer,
  offset: number,
  value: bigint,
  prefix: number
): void {
  const v = value & 0x1ffffffffn;
  buffer[offset] = ((prefix & 0x0f) << 4) | (Number((v >> 30n) & 0x07n) << 1) | 0x01;
  buffer[offset + 1] = Number((v >> 22n) & 0xffn);
  buffer[offset + 2] = (Number((v >> 15n) & 0x7fn) << 1) | 0x01;
  buffer[offset + 3] = Number((v >> 7n) & 0xffn);
  buffer[offset + 4] = (Number(v & 0x7fn) << 1) | 0x01;
}
