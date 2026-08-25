import { describe, it, expect } from 'vitest';
import {
  TS_PACKET_SIZE,
  pidOf,
  hasPayload,
  hasAdaptationField,
  payloadUnitStart,
  payloadOffset,
  readPcrBase,
  writePcrBase,
  readTimestamp,
  writeTimestamp,
} from '../src/ts.js';
import { makeSyntheticTs } from './helpers/synthetic-ts.js';

const PID = 0x0100;

function onePacket(): Buffer {
  return makeSyntheticTs({ packets: 1, pid: PID, step: 0n, start: 900_000n });
}

describe('TS packet primitives', () => {
  it('reads the PID out of the 13 bits spanning bytes 1 and 2', () => {
    expect(pidOf(onePacket())).toBe(PID);
  });

  it('recognises adaptation field plus payload', () => {
    const packet = onePacket();
    expect(hasAdaptationField(packet)).toBe(true);
    expect(hasPayload(packet)).toBe(true);
    expect(payloadUnitStart(packet)).toBe(true);
  });

  it('places the payload after the adaptation field', () => {
    // 4 header bytes + 1 length byte + 7 adaptation bytes
    expect(payloadOffset(onePacket())).toBe(12);
  });

  it('reports no payload offset for an adaptation-only packet', () => {
    const packet = onePacket();
    packet[3] = 0x20; // AFC = 10, adaptation only
    expect(hasPayload(packet)).toBe(false);
    expect(payloadOffset(packet)).toBe(-1);
  });

  it('round-trips a PCR base without disturbing the extension bits', () => {
    const packet = onePacket();
    const before = packet[10] & 0x7f;

    writePcrBase(packet, 1_234_567n);

    expect(readPcrBase(packet)).toBe(1_234_567n);
    expect(packet[10] & 0x7f).toBe(before);
  });

  it('round-trips a 33-bit timestamp at its maximum value', () => {
    const packet = onePacket();
    const max = 0x1ffffffffn;

    writeTimestamp(packet, 21, max, 0b0011);

    expect(readTimestamp(packet, 21)).toBe(max);
  });

  it('preserves the four-bit prefix that distinguishes PTS from DTS', () => {
    const packet = onePacket();
    writeTimestamp(packet, 26, 5_000n, 0b0001);
    expect(packet[26] >> 4).toBe(0b0001);
  });

  it('leaves marker bits set, which decoders require', () => {
    const packet = onePacket();
    writeTimestamp(packet, 21, 12_345n, 0b0011);

    expect(packet[21] & 0x01).toBe(1);
    expect(packet[23] & 0x01).toBe(1);
    expect(packet[25] & 0x01).toBe(1);
  });

  it('builds packets of exactly 188 bytes', () => {
    expect(makeSyntheticTs({ packets: 3, pid: PID, step: 3600n }).byteLength).toBe(
      3 * TS_PACKET_SIZE
    );
  });
});
