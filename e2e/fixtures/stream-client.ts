import { expect } from '@playwright/test';

export const TS_PACKET_SIZE = 188;
export const TS_SYNC_BYTE = 0x47;

/**
 * Asserts a buffer is 188-byte-aligned MPEG-TS: every packet boundary carries
 * the 0x47 sync byte. apps/proxy/live_proxy/input/buffer.py realigns to this
 * before writing chunks, so a misaligned read is a real defect.
 */
export function expectTsAligned(buffer: Buffer): void {
  expect(
    buffer.byteLength % TS_PACKET_SIZE,
    `buffer of ${buffer.byteLength} bytes is not a whole number of 188-byte packets`
  ).toBe(0);

  for (let offset = 0; offset < buffer.byteLength; offset += TS_PACKET_SIZE) {
    expect(
      buffer[offset],
      `expected sync byte 0x47 at offset ${offset}, got 0x${buffer[offset].toString(16)}`
    ).toBe(TS_SYNC_BYTE);
  }
}

/**
 * Reads endless HTTP byte streams. Node fetch, not Playwright's request
 * fixture: APIResponse.body() returns Promise<Buffer> and internally awaits
 * the full download, so it never resolves against /proxy/ts/stream/<uuid>.
 */
export class StreamClient {
  private controller?: AbortController;
  private reader?: ReadableStreamDefaultReader<Uint8Array>;
  private buffered: Buffer = Buffer.alloc(0);
  /** The single outstanding pump(), if any. See pump(). */
  private inFlight?: Promise<boolean>;

  constructor(private baseURL: string) {}

  /** `path` may be absolute or relative to baseURL. */
  async open(path: string, headers: Record<string, string> = {}): Promise<void> {
    this.controller = new AbortController();
    const url = path.startsWith('http') ? path : new URL(path, this.baseURL).toString();

    const response = await fetch(url, {
      headers,
      signal: this.controller.signal,
    });
    if (!response.ok) {
      throw new Error(`stream open failed: ${response.status} ${response.statusText}`);
    }
    if (!response.body) {
      throw new Error('stream response carried no body');
    }
    this.reader = response.body.getReader();
  }

  /**
   * Appends the next chunk to `buffered`; false once the stream ends.
   *
   * At most one `reader.read()` is ever outstanding. This matters because
   * collectFor abandons its pump() when the timer wins, and read requests
   * queue FIFO (ECMA/streams: read() pushes onto [[readRequests]], and an
   * arriving chunk fulfils the *first* pending request). A second
   * reader.read() would therefore sit behind the abandoned one: on a stalled
   * stream the abandoned read takes the chunk and appends it here, while the
   * new caller waits on a chunk after it that may never come — blocking with
   * the bytes it asked for already in the buffer. Memoising the in-flight
   * read makes the later caller wake on the *same* chunk instead.
   */
  private pump(): Promise<boolean> {
    if (this.inFlight) return this.inFlight;
    const pending: Promise<boolean> = this.readChunk().finally(() => {
      if (this.inFlight === pending) this.inFlight = undefined;
    });
    this.inFlight = pending;
    return pending;
  }

  private async readChunk(): Promise<boolean> {
    if (!this.reader) throw new Error('open() must be called before reading');
    const { done, value } = await this.reader.read();
    if (done) return false;
    this.buffered = Buffer.concat([this.buffered, Buffer.from(value)]);
    return true;
  }

  /** Exactly `count` TS packets (count * 188 bytes). */
  async readPackets(count: number): Promise<Buffer> {
    const wanted = count * TS_PACKET_SIZE;
    while (this.buffered.byteLength < wanted) {
      if (!(await this.pump())) {
        throw new Error(
          `stream ended after ${this.buffered.byteLength} bytes, wanted ${wanted}`
        );
      }
    }
    const out = this.buffered.subarray(0, wanted);
    this.buffered = this.buffered.subarray(wanted);
    return Buffer.from(out);
  }

  /** Everything that arrives within `ms`. */
  async collectFor(ms: number): Promise<Buffer> {
    const deadline = Date.now() + ms;
    while (Date.now() < deadline) {
      const remaining = deadline - Date.now();
      // If the timeout below wins, this pump() is left outstanding. Two
      // separate reasons that is safe, both load-bearing:
      //
      // 1. It is not an unhandled rejection. Promise.race attaches a handler
      //    to every input promise, not just the winner (ECMA-262
      //    PerformPromiseRace), so the losing pump() is already handled and
      //    needs no .catch() here. Verified under
      //    `node --unhandled-rejections=strict` (no warning across 30
      //    iterations of open/readPackets/collectFor/close). If this race is
      //    ever replaced with something that does not handle losers, that
      //    changes.
      // 2. It does not strand the next caller. pump() memoises the in-flight
      //    read, so a later readPackets() awaits *this* promise rather than
      //    queueing a second reader.read() behind it. See pump().
      const timed = await Promise.race([
        this.pump(),
        new Promise<'timeout'>((resolve) => setTimeout(() => resolve('timeout'), remaining)),
      ]);
      if (timed === 'timeout' || timed === false) break;
    }
    const out = this.buffered;
    this.buffered = Buffer.alloc(0);
    return out;
  }

  async close(): Promise<void> {
    const pending = this.inFlight;
    this.reader = undefined;
    this.inFlight = undefined;

    this.controller?.abort();
    this.controller = undefined;

    // abort() errors the body stream, so a queued read rejects rather than
    // hanging. Await it so a closed client leaves nothing outstanding — and
    // drop the buffer only afterwards, because a read that resolved just
    // before the abort landed still appends its chunk on the way out. The
    // rejection is the abort we just caused, so swallowing it is deliberate.
    if (pending) await pending.catch(() => {});
    this.buffered = Buffer.alloc(0);
  }
}
