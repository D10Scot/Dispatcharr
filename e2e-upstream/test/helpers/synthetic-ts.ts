import { TS_PACKET_SIZE } from '../../src/ts.js';

export interface SyntheticOptions {
  packets: number;
  pid: number;
  /** 90 kHz ticks between consecutive packets. */
  step: bigint;
  /** 90 kHz value of the first packet. */
  start?: bigint;
}

function writeTs(buffer: Buffer, offset: number, value: bigint, prefix: number): void {
  const v = value & 0x1ffffffffn;
  buffer[offset] = ((prefix & 0x0f) << 4) | (Number((v >> 30n) & 0x07n) << 1) | 0x01;
  buffer[offset + 1] = Number((v >> 22n) & 0xffn);
  buffer[offset + 2] = (Number((v >> 15n) & 0x7fn) << 1) | 0x01;
  buffer[offset + 3] = Number((v >> 7n) & 0xffn);
  buffer[offset + 4] = (Number(v & 0x7fn) << 1) | 0x01;
}

/**
 * A deliberately unrealistic stream: every packet carries an adaptation field
 * with a PCR and a complete PES header with PTS and DTS. Real video looks
 * nothing like this, and that is the point — the rewriter must not care what
 * the asset contains, so the test gives it the densest possible case.
 *
 * Layout, matching the offsets LoopRewriter computes:
 *   0..3    TS header, AFC=11 (adaptation + payload), PUSI set
 *   4       adaptation_field_length = 7
 *   5       adaptation flags = 0x10 (PCR present)
 *   6..11   PCR (33-bit base at 90 kHz, 6 reserved bits, 9-bit extension)
 *   12..14  PES start code 00 00 01
 *   15      stream_id 0xE0 (video)
 *   16..17  PES_packet_length (0 = unbounded, legal for video)
 *   18      PES flags 1
 *   19      PES flags 2 = 0xC0 (PTS and DTS present)
 *   20      PES_header_data_length = 10
 *   21..25  PTS
 *   26..30  DTS
 *   31..187 0xFF padding
 */
export function makeSyntheticTs(options: SyntheticOptions): Buffer {
  const { packets, pid, step } = options;
  const start = options.start ?? 0n;
  const out = Buffer.alloc(packets * TS_PACKET_SIZE, 0xff);

  for (let index = 0; index < packets; index += 1) {
    const base = out.subarray(index * TS_PACKET_SIZE, (index + 1) * TS_PACKET_SIZE);
    const stamp = start + step * BigInt(index);

    base[0] = 0x47;
    base[1] = 0x40 | ((pid >> 8) & 0x1f);
    base[2] = pid & 0xff;
    base[3] = 0x30 | (index & 0x0f); // AFC = 11, continuity counter
    base[4] = 7;
    base[5] = 0x10;

    // PCR base is 33 bits at 90 kHz — the same clock as PTS — so the seam
    // offset added to PTS applies unchanged. The 9-bit extension is left
    // alone.
    base[6] = Number((stamp >> 25n) & 0xffn);
    base[7] = Number((stamp >> 17n) & 0xffn);
    base[8] = Number((stamp >> 9n) & 0xffn);
    base[9] = Number((stamp >> 1n) & 0xffn);
    base[10] = (Number(stamp & 0x01n) << 7) | 0x7e;
    base[11] = 0x00;

    base[12] = 0x00;
    base[13] = 0x00;
    base[14] = 0x01;
    base[15] = 0xe0;
    base[16] = 0x00;
    base[17] = 0x00;
    base[18] = 0x80;
    base[19] = 0xc0;
    base[20] = 10;
    writeTs(base, 21, stamp, 0b0011);
    writeTs(base, 26, stamp, 0b0001);
  }

  return out;
}
