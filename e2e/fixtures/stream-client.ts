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

export interface StreamOpenOptions {
  headers?: Record<string, string>;
  /**
   * Defaults to 'follow'. Pass 'manual' when the response is expected to be a
   * redirect to a container-internal hostname — Dispatcharr's Redirect profile
   * 302s to the original upstream URL, which this process cannot resolve.
   */
  redirect?: RequestRedirect;
}

/**
 * A DNS failure on the provider's container-internal name is the single most
 * likely way a streaming test goes wrong, and Node reports it as a bare
 * "fetch failed" with the cause buried. Naming it costs one function and
 * saves the reader the whole investigation.
 */
function describeFetchFailure(url: string, cause: unknown): string {
  const code = (cause as { cause?: { code?: string } })?.cause?.code;
  const dnsFailure = code === 'ENOTFOUND' || code === 'EAI_AGAIN';

  if (dnsFailure && url.includes('e2e-upstream')) {
    return (
      `stream open failed: cannot resolve ${url} from the test process. ` +
      `That hostname resolves only inside the Docker network. If this came ` +
      `from following a redirect, open with { redirect: 'manual' } and pass ` +
      `each Location through upstream.toControl().`
    );
  }
  return `stream open failed: ${url} — ${String(cause)}`;
}

/**
 * Reads endless HTTP byte streams. Node fetch, not Playwright's request
 * fixture: APIResponse.body() returns Promise<Buffer> and internally awaits
 * the full download, so it never resolves against /proxy/ts/stream/<uuid>.
 */
export class StreamClient {
  private controller?: AbortController;
  private reader?: ReadableStreamDefaultReader<Uint8Array>;
  /** Set once `open()` resolves. Lets a redirect test read `Location`. */
  status?: number;
  headers?: Headers;
  /**
   * Chunks as they arrived, oldest first. Concatenated only when bytes are
   * handed out.
   *
   * A list rather than one growing Buffer because `Buffer.concat` on every
   * chunk copies the whole accumulation to append one chunk — quadratic in
   * the length of the collection window. The fake upstream provider
   * (`e2e-upstream/`) paces at its own nominal bitrate times a per-scenario
   * `rate` multiplier, so a `collectFor(60_000)` — well inside the streaming
   * project's 300s per-test budget, and what a dead-air or failover test will
   * do — accumulates megabytes across thousands of chunks; at any rate above
   * 1 the copy volume from a growing Buffer scales quadratically well past
   * what one test should cost. Against a real provider at several Mbit/s,
   * worse still.
   */
  private chunks: Buffer[] = [];
  /** Total bytes held in `chunks`, so readPackets() need not sum them. */
  private bufferedBytes = 0;
  /** The single outstanding pump(), if any. See pump(). */
  private inFlight?: Promise<boolean>;

  constructor(private baseURL: string) {}

  /** `path` may be absolute or relative to baseURL. */
  async open(path: string, options: StreamOpenOptions = {}): Promise<void> {
    // Cleared up front, not just set on success: otherwise a failed open on
    // an instance already used once leaves `status`/`headers` holding a
    // stale prior response — a stale 200 read after a failure is a
    // genuinely misleading thing to hand someone mid-debug.
    this.status = undefined;
    this.headers = undefined;
    this.controller = new AbortController();
    const url = path.startsWith('http') ? path : new URL(path, this.baseURL).toString();

    let response: Response;
    try {
      response = await fetch(url, {
        headers: options.headers ?? {},
        redirect: options.redirect ?? 'follow',
        signal: this.controller.signal,
      });
    } catch (cause) {
      throw new Error(describeFetchFailure(url, cause), { cause });
    }

    // With redirect: 'manual', a 3xx is the expected outcome, not a failure —
    // the caller reads Location and walks the chain. res.ok is false for it,
    // so the check below must not reject it.
    if (
      !response.ok &&
      !(options.redirect === 'manual' && response.status >= 300 && response.status < 400)
    ) {
      throw new Error(`stream open failed: ${response.status} ${response.statusText}`);
    }
    this.status = response.status;
    this.headers = response.headers;
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
    const chunk = Buffer.from(value);
    this.chunks.push(chunk);
    this.bufferedBytes += chunk.byteLength;
    return true;
  }

  /**
   * Remove and return the first `wanted` buffered bytes. Only those are
   * copied: a chunk straddling the boundary is split and its tail put back, so
   * a small `readPackets` against a large accumulation stays proportional to
   * what it asked for rather than to what is held.
   */
  private takeBytes(wanted: number): Buffer {
    const out = Buffer.allocUnsafe(wanted);
    let filled = 0;
    while (filled < wanted) {
      const chunk = this.chunks[0];
      const take = Math.min(chunk.byteLength, wanted - filled);
      chunk.copy(out, filled, 0, take);
      filled += take;
      if (take === chunk.byteLength) this.chunks.shift();
      else this.chunks[0] = chunk.subarray(take);
    }
    this.bufferedBytes -= wanted;
    return out;
  }

  /** Exactly `count` TS packets (count * 188 bytes). */
  async readPackets(count: number): Promise<Buffer> {
    const wanted = count * TS_PACKET_SIZE;
    while (this.bufferedBytes < wanted) {
      if (!(await this.pump())) {
        throw new Error(
          `stream ended after ${this.bufferedBytes} bytes, wanted ${wanted}`
        );
      }
    }
    return this.takeBytes(wanted);
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
    // The one concat, over the whole window, instead of one per chunk.
    const out = Buffer.concat(this.chunks, this.bufferedBytes);
    this.chunks = [];
    this.bufferedBytes = 0;
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
    this.chunks = [];
    this.bufferedBytes = 0;
  }
}

/** The null PID carries stuffing only and has no meaningful counter. */
const TS_NULL_PID = 0x1fff;

/** PID is 13 bits: the low 5 of byte 1 and all of byte 2. */
function pidAt(buffer: Buffer, offset: number): number {
  return ((buffer[offset + 1] & 0x1f) << 8) | buffer[offset + 2];
}

/**
 * The busiest PID that is not the null PID. Which PID carries video is a
 * property of the asset, not of Dispatcharr, so tests derive it rather than
 * hard-coding it — a re-muxed asset would otherwise silently assert nothing.
 */
export function videoPidOf(buffer: Buffer): number {
  const counts = new Map<number, number>();
  for (let off = 0; off + TS_PACKET_SIZE <= buffer.byteLength; off += TS_PACKET_SIZE) {
    const pid = pidAt(buffer, off);
    if (pid === TS_NULL_PID) continue;
    counts.set(pid, (counts.get(pid) ?? 0) + 1);
  }
  let best = -1;
  let bestCount = 0;
  for (const [pid, n] of counts) {
    if (n > bestCount) {
      best = pid;
      bestCount = n;
    }
  }
  expect(best, 'buffer contains no non-null PID').toBeGreaterThanOrEqual(0);
  return best;
}

/**
 * Assert the 4-bit continuity counter on `pid` increments by exactly one per
 * payload-bearing packet, wrapping at 16.
 *
 * This is what proves nothing was lost or spliced. A byte count proves only
 * that bytes arrived — and the defect this suite most needs to catch (two
 * owners interleaving chunks at alternating indices) produces a stream whose
 * length is perfectly correct.
 *
 * Packets with adaptation_field_control 0b00 or 0b10 carry no payload and do
 * not advance the counter; skipping them is required by the TS spec, not an
 * optimisation.
 *
 * This is not a general splice detector, and reports two spec-legal cases as
 * gaps:
 *
 *   1. A single repeated (duplicate) continuity counter, which ISO 13818-1
 *      permits for packet retransmission.
 *   2. A packet whose adaptation field sets `discontinuity_indicator`, which
 *      legitimately resets the counter — precisely what a remux may emit
 *      across a stream switch.
 *
 * Every current call site reads packets from within a single, unswitched
 * stream, so neither case arises in practice. A caller that points this at a
 * buffer spanning a stream switch would get a false positive from case 2, and
 * must not do so without first handling the discontinuity indicator — this
 * function does not.
 */
export function expectContiguous(buffer: Buffer, pid: number): void {
  let previous: number | null = null;
  let checked = 0;

  for (let off = 0; off + TS_PACKET_SIZE <= buffer.byteLength; off += TS_PACKET_SIZE) {
    if (pidAt(buffer, off) !== pid) continue;

    const afc = (buffer[off + 3] >> 4) & 0x03;
    if (afc === 0b00 || afc === 0b10) continue; // no payload: counter does not advance

    const cc = buffer[off + 3] & 0x0f;
    if (previous !== null) {
      const expected = (previous + 1) & 0x0f;
      expect(
        cc,
        `continuity counter gap on PID 0x${pid.toString(16)} at byte ${off}: ` +
          `expected ${expected}, saw ${cc}`
      ).toBe(expected);
    }
    previous = cc;
    checked++;
  }

  // >1, not >0: with checked === 1 the loop made zero comparisons —
  // `previous` is null on the first packet — so a single payload-bearing
  // packet would pass having asserted nothing about contiguity at all.
  expect(checked, `too few payload-bearing packets on PID 0x${pid.toString(16)} to prove contiguity`).toBeGreaterThan(1);
}
