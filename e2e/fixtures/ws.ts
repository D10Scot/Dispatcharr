import WebSocket from 'ws';
import fs from 'node:fs';

const TOKENS_FILE = 'playwright/.auth/tokens.json';

/**
 * Subscription to the single `updates` group on /ws/.
 *
 * Auth is a `token` query parameter carrying the access JWT
 * (dispatcharr/jwt_ws_auth.py); an unauthenticated socket is closed
 * immediately. Use this only for state the REST API does not expose — the
 * message vocabulary is a fixed dict in the product and will drift.
 */
export class WsListener {
  private socket: WebSocket;
  private received: any[] = [];
  private waiters: Array<{
    type: string;
    resolve: (message: any) => void;
    reject: (error: Error) => void;
  }> = [];
  // Set once a network-level error fires (connection refused, DNS failure,
  // TLS error) — distinct from an auth rejection, which the server delivers
  // as a clean close, not an 'error' event.
  private connectionError: Error | undefined;
  private readonly sanitizedUrl: string;

  constructor(baseURL: string) {
    const { access } = JSON.parse(fs.readFileSync(TOKENS_FILE, 'utf8'));
    const url = new URL(baseURL);
    url.protocol = url.protocol === 'https:' ? 'wss:' : 'ws:';
    url.pathname = '/ws/';
    this.sanitizedUrl = url.toString();
    url.searchParams.set('token', access);

    this.socket = new WebSocket(url.toString());
    this.socket.on('message', (raw) => {
      const message = JSON.parse(raw.toString());
      this.received.push(message);
      const index = this.waiters.findIndex((w) => w.type === message.type);
      if (index >= 0) this.waiters.splice(index, 1)[0].resolve(message);
    });
    // A `ws` client is a plain Node EventEmitter: an 'error' event with no
    // listener throws and kills the whole worker process, not just this
    // test. Without this, a connection refused/DNS/TLS failure takes down
    // every other test sharing the worker.
    this.socket.on('error', (error: NodeJS.ErrnoException) => {
      // Node's connect-multiple path reports refusal as an AggregateError
      // with an empty .message and the real reason on .code (e.g.
      // 'ECONNREFUSED') — fall back to that, then to the error itself.
      const reason = error.message || error.code || String(error);
      this.connectionError = new Error(
        `websocket error connecting to ${this.sanitizedUrl}: ${reason}`
      );
      const pending = this.waiters.splice(0, this.waiters.length);
      for (const waiter of pending) waiter.reject(this.connectionError);
    });
  }

  waitForMessage(type: string, timeoutMs = 30_000): Promise<any> {
    const already = this.received.find((m) => m.type === type);
    if (already) return Promise.resolve(already);
    if (this.connectionError) return Promise.reject(this.connectionError);

    return new Promise((resolve, reject) => {
      const timer = setTimeout(
        () => reject(new Error(`timed out waiting for ws message '${type}'`)),
        timeoutMs
      );
      this.waiters.push({
        type,
        resolve: (message) => {
          clearTimeout(timer);
          resolve(message);
        },
        reject: (error) => {
          clearTimeout(timer);
          reject(error);
        },
      });
    });
  }

  close(): void {
    this.socket.close();
  }
}
