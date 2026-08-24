import WebSocket from 'ws';

/**
 * Subscription to the single `updates` group on /ws/.
 *
 * Auth is a `token` query parameter carrying the access JWT
 * (dispatcharr/jwt_ws_auth.py); an unauthenticated socket is refused at the
 * handshake. Use this only for state the REST API does not expose — the
 * message vocabulary is a fixed dict in the product and will drift.
 *
 * The token is passed in rather than read from `playwright/.auth/tokens.json`
 * here: a query-parameter token is fixed at connect time and this class has
 * no way to refresh it, so it must be handed one that is known live. The `ws`
 * fixture gets that from `api.freshAccessToken()`.
 *
 * Two message shapes exist on the wire, and `waitForMessage` matches either:
 *  - top-level `type`, e.g. `{"type": "connection_established", "data": {...}}`
 *    — the handful of connect-time pushes `dispatcharr/consumers.py` sends
 *    directly.
 *  - nested `data.type`, e.g. `{"type": "update", "data": {"type":
 *    "playlist_created", ...}}` — every product event sent through
 *    `send_websocket_update()` (`core/utils.py`). Virtually every call site
 *    passes `event_type="update"` and puts the real event name one level
 *    down inside `data`; `consumers.py`'s `update()` handler forwards that
 *    dict to the client verbatim. Confirmed empirically against a live
 *    container: creating an M3U account produced exactly
 *    `{"type": "update", "data": {"type": "playlist_created", "playlist_id": 4}}`.
 *    So `waitForMessage('playlist_created')` matches it correctly.
 *    Waiting on the literal `'update'` is almost never what you want — it
 *    matches *every* product event indiscriminately, including ones fired by
 *    another test running concurrently against the shared instance.
 */

/**
 * The wire-level `type` every product event is sent under — see the class
 * doc comment. Named so `describeReceived()` doesn't repeat the bare literal.
 */
const UPDATE_ENVELOPE_TYPE = 'update';

/** True when `message` carries `type` at the top level or nested under `data`. */
function messageMatches(message: any, type: string): boolean {
  return message?.type === type || message?.data?.type === type;
}

export class WsListener {
  private socket: WebSocket;
  private received: any[] = [];
  private waiters: Array<{
    type: string;
    resolve: (message: any) => void;
    reject: (error: Error) => void;
  }> = [];
  // Set once a network-level error fires (connection refused, DNS failure,
  // TLS error) or the server closes the socket on us. Either one makes every
  // subsequent wait pointless, so it is remembered rather than just used to
  // reject whoever happened to be waiting at the time.
  private connectionError: Error | undefined;
  // Set by close(): a socket we closed ourselves is not a failure, and its
  // 'close' event must not be reported as one.
  private closedByUs = false;
  private readonly sanitizedUrl: string;

  constructor(baseURL: string, accessToken: string) {
    const url = new URL(baseURL);
    url.protocol = url.protocol === 'https:' ? 'wss:' : 'ws:';
    url.pathname = '/ws/';
    this.sanitizedUrl = url.toString();
    url.searchParams.set('token', accessToken);

    this.socket = new WebSocket(url.toString());
    this.socket.on('message', (raw) => {
      const message = JSON.parse(raw.toString());
      this.received.push(message);
      const index = this.waiters.findIndex((w) => messageMatches(message, w.type));
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
      this.fail(`websocket error connecting to ${this.sanitizedUrl}: ${reason}`);
    });
    // A close after the handshake — daphne going away, the container being
    // restarted mid-suite, the consumer dropping us — is otherwise entirely
    // invisible: no 'error' fires, no waiter is rejected, and every pending
    // wait burns its full 30 seconds before failing with a bare "timed out
    // waiting for ws message" that names neither the cause nor the socket.
    //
    // Measured, not assumed: an *auth* rejection does not arrive here.
    // dispatcharr/consumers.py calls `close()` before `accept()`, which
    // rejects the HTTP upgrade itself, and `ws` reports that as an 'error'
    // with "Unexpected server response: 403" — the same for a malformed
    // token, a correctly signed refresh token and a tampered signature.
    // This handler is for the socket that dies after it was established.
    this.socket.on('close', (code: number, reason: Buffer) => {
      // `ws` emits 'close' after 'error' too; the error already named the
      // real cause, so don't overwrite it with the generic close message.
      if (this.closedByUs || this.connectionError) return;
      const why = reason?.toString() || 'none given';
      this.fail(
        `websocket to ${this.sanitizedUrl} was closed by the server ` +
          `(code ${code}, reason: ${why})${this.describeReceived()}. ` +
          'The socket was established and then dropped, so this is the ' +
          'server going away — a restarted or crashed container, or daphne ' +
          'being reloaded — and not the access token: a rejected token is ' +
          'refused earlier, at the handshake, and surfaces as a 403 error.'
      );
    });
  }

  /**
   * Types of the messages this socket has actually seen, for diagnostics.
   * Not every push carries a top-level `type` — the cached-IP message on
   * connect nests it under `data` (dispatcharr/consumers.py) — so fall back
   * rather than printing a blank.
   *
   * A message wrapped in the `'update'` envelope reports its *nested* type
   * instead: virtually every product event carries that literal at the top
   * level (see the class doc comment), so printing it verbatim would list
   * `[update, update, update]` for a timeout on, say,
   * `waitForMessage('m3u_refresh')` — exactly the diagnostic this method
   * exists to give, made useless by the very envelope `waitForMessage` was
   * fixed to see through.
   */
  private describeReceived(): string {
    return this.received.length === 0
      ? '; no messages were received'
      : `; received: [${this.received
          .map((m) =>
            m?.type === UPDATE_ENVELOPE_TYPE
              ? (m?.data?.type ?? UPDATE_ENVELOPE_TYPE)
              : (m?.type ?? m?.data?.type ?? '(untyped)')
          )
          .join(', ')}]`;
  }

  /** Record a terminal failure and hand it to everyone currently waiting. */
  private fail(message: string): void {
    this.connectionError = new Error(message);
    const pending = this.waiters.splice(0, this.waiters.length);
    for (const waiter of pending) waiter.reject(this.connectionError);
  }

  /**
   * Resolves with the first received message whose top-level `type`, or
   * whose `data.type`, equals `type` — see the class doc comment for why
   * both forms exist and which one a real call needs.
   */
  waitForMessage(type: string, timeoutMs = 30_000): Promise<any> {
    const already = this.received.find((m) => messageMatches(m, type));
    if (already) return Promise.resolve(already);
    if (this.connectionError) return Promise.reject(this.connectionError);

    return new Promise((resolve, reject) => {
      const timer = setTimeout(
        () =>
          reject(
            new Error(
              `timed out after ${timeoutMs}ms waiting for ws message ` +
                `'${type}' on ${this.sanitizedUrl}${this.describeReceived()}`
            )
          ),
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
    this.closedByUs = true;
    this.socket.close();
  }
}
