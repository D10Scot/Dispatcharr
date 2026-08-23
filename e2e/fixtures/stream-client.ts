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

  private async pump(): Promise<boolean> {
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
      const pumping = this.pump();
      // If the timeout below wins, this read is left outstanding. Catch it
      // here so a later rejection (e.g. from close()'s abort()) settles
      // quietly instead of being surfaced as an unhandled rejection.
      pumping.catch(() => {});
      const timed = await Promise.race([
        pumping,
        new Promise<'timeout'>((resolve) => setTimeout(() => resolve('timeout'), remaining)),
      ]);
      if (timed === 'timeout' || timed === false) break;
    }
    const out = this.buffered;
    this.buffered = Buffer.alloc(0);
    return out;
  }

  async close(): Promise<void> {
    this.controller?.abort();
    this.reader = undefined;
    this.buffered = Buffer.alloc(0);
  }
}
