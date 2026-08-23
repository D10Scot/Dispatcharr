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
  private waiters: Array<{ type: string; resolve: (message: any) => void }> = [];

  constructor(baseURL: string) {
    const { access } = JSON.parse(fs.readFileSync(TOKENS_FILE, 'utf8'));
    const url = new URL(baseURL);
    url.protocol = url.protocol === 'https:' ? 'wss:' : 'ws:';
    url.pathname = '/ws/';
    url.searchParams.set('token', access);

    this.socket = new WebSocket(url.toString());
    this.socket.on('message', (raw) => {
      const message = JSON.parse(raw.toString());
      this.received.push(message);
      const index = this.waiters.findIndex((w) => w.type === message.type);
      if (index >= 0) this.waiters.splice(index, 1)[0].resolve(message);
    });
  }

  waitForMessage(type: string, timeoutMs = 30_000): Promise<any> {
    const already = this.received.find((m) => m.type === type);
    if (already) return Promise.resolve(already);

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
      });
    });
  }

  close(): void {
    this.socket.close();
  }
}
