import WebSocket from 'ws';

/**
 * Subscription to the single `updates` group on /ws/.
 *
 * Auth is a `token` query parameter carrying the access JWT
 * (dispatcharr/jwt_ws_auth.py); an unauthenticated socket is refused at the
 * handshake. Use this only for state the REST API does not expose — the
 * message vocabulary is unregistered string literals at
 * `send_websocket_update()` call sites, and will drift.
 *
 * The token is passed in rather than read from `playwright/.auth/tokens.json`
 * here: a query-parameter token is fixed at connect time and this class has
 * no way to refresh it, so it must be handed one that is known live. The `ws`
 * fixture gets that from `api.freshAccessToken()`.
 *
 * ---------------------------------------------------------------------------
 * Two message shapes
 * ---------------------------------------------------------------------------
 * Both are matched by `waitForMessage`:
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
 *    matches *every* product event indiscriminately.
 *
 * ---------------------------------------------------------------------------
 * READ THIS BEFORE WAITING ON A TYPE — /ws/ is a broadcast
 * ---------------------------------------------------------------------------
 * `consumers.py` puts every socket in one group, `updates`, and every event
 * the whole instance produces is sent to all of them. The `seeded` project
 * runs `workers: 4` against one shared container, so **your socket receives
 * the other three workers' events too, interleaved with your own.**
 *
 * A bare `waitForMessage('playlist_created')` therefore resolves on
 * *whoever's* playlist was created. If a test running in parallel can trigger
 * the same event type, a bare type match will sometimes resolve on their
 * event, your own work will not have happened yet, and the assertion after it
 * either flakes or — worse — passes on their data.
 *
 * Correlate with a predicate whenever the type is not exclusively yours:
 *
 * ```ts
 * const account = await seed.m3uAccount();
 * const message = await ws.waitForMessage('playlist_created', {
 *   where: (data) => data.playlist_id === account.id,
 * });
 * ```
 *
 * The predicate is handed the payload (`message.data`), which is where every
 * product event carries its entity ids. A bare type match is safe only for
 * something nothing else can produce — `connection_established`, which is per
 * socket, is the honest example.
 *
 * ---------------------------------------------------------------------------
 * Queue semantics
 * ---------------------------------------------------------------------------
 * Messages and waiters are matched FIFO and **consumed**:
 *  - a message that satisfies a waiter is taken by it and can satisfy no other;
 *  - a message that arrives with no waiter interested in it is queued, and the
 *    next matching wait consumes it — once, and once only;
 *  - a waiter that times out is removed, so it can never consume a message
 *    afterwards.
 * So two sequential waits for the same type return two *different* messages,
 * which is what a test waiting on two successive events needs, and a wait that
 * timed out cannot swallow the event a later wait is waiting for.
 */

/**
 * The wire-level `type` every product event is sent under — see the class
 * doc comment. Named so `describeReceived()` doesn't repeat the bare literal.
 */
const UPDATE_ENVELOPE_TYPE = 'update';

/**
 * How many message types `describeReceived()` will list. A socket on a live
 * instance sees `channel_stats` roughly once a second, so an unbounded list
 * turns a streaming test's timeout message into hundreds of entries and
 * buries the ones that matter.
 */
const DESCRIBE_LIMIT = 40;

/**
 * The payload half of a message: `message.data`.
 *
 * Its keys are deliberately `unknown` rather than a union of the product's
 * event shapes. There is no registry to derive one from: an event name is a
 * bare string literal at whichever `send_websocket_update()` call site emits
 * it (`'playlist_created'` is `apps/m3u/api_views.py:132`), spread across a
 * dozen modules, each carrying its own set of ids and none of them
 * schema'd — so a type enumerating them would be a claim this harness has
 * not verified and could not keep current. `unknown` values still compare
 * (`data.playlist_id === account.id` typechecks), which is what a `where`
 * predicate does with them.
 *
 * `type` is called out because `waitForMessage` matches on it: virtually every
 * product event arrives as `{type: 'update', data: {type: '<real event>'}}`.
 */
export type WsPayload = Record<string, unknown> & { type?: string };

/**
 * A message as it comes off the socket.
 *
 * Both halves are optional, and both really are: `consumers.py` pushes the
 * cached-IP result as `{'data': {'type': 'ip_lookup_complete', ...}}` with no
 * top-level `type` at all, and `update()` forwards whatever
 * `send_websocket_update()` handed it — which `user_may_receive_update` reads
 * with `event.get("data")`, so a `data`-less event is a shape the product
 * admits. Reach for `message.data?.x`, not `message.data.x`.
 */
export type WsMessage = { type?: string; data?: WsPayload };

/**
 * Correlates a message to the test that caused it. Receives the payload
 * (`message.data`, or `{}` when the message carries none) and, for the rare
 * case that needs it, the whole message.
 */
export type MessagePredicate = (data: WsPayload, message: WsMessage) => boolean;

export type WaitForMessageOptions = {
  /**
   * Narrows the match beyond the type. **Required for any type a parallel
   * test could also trigger** — see the class doc comment.
   */
  where?: MessagePredicate;
  /** Default 30s. */
  timeoutMs?: number;
};

/** True when `message` carries `type` at the top level or nested under `data`. */
function messageMatches(message: WsMessage, type: string): boolean {
  return message?.type === type || message?.data?.type === type;
}

/** The payload a predicate is handed: never null, never throws on access. */
function payloadOf(message: WsMessage): WsPayload {
  return message?.data ?? {};
}

type Waiter = {
  type: string;
  where: MessagePredicate | undefined;
  /** For error messages: `'playlist_created'` or `'playlist_created' (where: …)`. */
  description: string;
  resolve: (message: WsMessage) => void;
  reject: (error: Error) => void;
};

export class WsListener {
  private socket: WebSocket;
  /**
   * Messages that have arrived and not yet been consumed by a wait, oldest
   * first. Distinct from `log`: this one is consuming, so nothing here can
   * satisfy two waits.
   */
  private queue: WsMessage[] = [];
  /**
   * Every message ever received, for diagnostics only — never matched
   * against, so consuming from `queue` cannot degrade a timeout message.
   * Bounded; see DESCRIBE_LIMIT.
   */
  private log: WsMessage[] = [];
  private droppedFromLog = 0;
  /** Live waiters, oldest first. A timed-out or rejected waiter is removed. */
  private waiters: Waiter[] = [];
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
      const message: WsMessage = JSON.parse(raw.toString());
      this.remember(message);
      // Hand it to the oldest interested waiter, which consumes it; queue it
      // for a future wait if nobody is interested yet.
      const waiter = this.takeWaiterFor(message);
      if (waiter) waiter.resolve(message);
      else this.queue.push(message);
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
   *
   * Reads `log`, not `queue`: a consumed message is still evidence of what
   * this socket saw, and dropping it from the diagnostic would make a
   * "second wait timed out" failure report an empty socket.
   */
  private describeReceived(): string {
    if (this.log.length === 0 && this.droppedFromLog === 0) {
      return '; no messages were received';
    }
    const types = this.log.map((m) =>
      m?.type === UPDATE_ENVELOPE_TYPE
        ? (m?.data?.type ?? UPDATE_ENVELOPE_TYPE)
        : (m?.type ?? m?.data?.type ?? '(untyped)')
    );
    const elided =
      this.droppedFromLog > 0
        ? `${this.droppedFromLog} earlier message(s) elided, `
        : '';
    return `; received (${elided}${this.queue.length} still unconsumed): [${types.join(', ')}]`;
  }

  /** Append to the diagnostic log, keeping it bounded. */
  private remember(message: WsMessage): void {
    this.log.push(message);
    if (this.log.length > DESCRIBE_LIMIT) {
      this.log.shift();
      this.droppedFromLog++;
    }
  }

  /**
   * Remove and return the oldest waiter this message satisfies, or undefined.
   *
   * Removal is the point: a waiter that takes a message is gone, so the
   * message cannot also be handed to the next one, and a waiter that already
   * timed out is not in this list to take anything.
   */
  private takeWaiterFor(message: WsMessage): Waiter | undefined {
    for (let i = 0; i < this.waiters.length; i++) {
      const waiter = this.waiters[i];
      if (!messageMatches(message, waiter.type)) continue;
      let matched: boolean;
      try {
        matched = waiter.where ? waiter.where(payloadOf(message), message) : true;
      } catch (error) {
        // A throwing predicate is a bug in the test, not a missed match.
        // Fail that one waiter loudly rather than swallowing it — and take
        // it out of the list, since it will throw on every message.
        this.waiters.splice(i, 1);
        waiter.reject(
          new Error(
            `the 'where' predicate passed to waitForMessage(${waiter.description}) ` +
              `threw while evaluating a message: ${(error as Error)?.message ?? error}`
          )
        );
        i--;
        continue;
      }
      if (!matched) continue;
      this.waiters.splice(i, 1);
      return waiter;
    }
    return undefined;
  }

  /**
   * Remove and return the oldest queued message satisfying this waiter, so a
   * wait registered after the event still sees it — exactly once.
   */
  private takeQueuedFor(
    type: string,
    where: MessagePredicate | undefined
  ): WsMessage | undefined {
    for (let i = 0; i < this.queue.length; i++) {
      const message = this.queue[i];
      if (!messageMatches(message, type)) continue;
      if (where && !where(payloadOf(message), message)) continue;
      return this.queue.splice(i, 1)[0];
    }
    return undefined;
  }

  /** Record a terminal failure and hand it to everyone currently waiting. */
  private fail(message: string): void {
    this.connectionError = new Error(message);
    const pending = this.waiters.splice(0, this.waiters.length);
    for (const waiter of pending) waiter.reject(this.connectionError);
  }

  /**
   * Resolves with the next message whose top-level `type`, or whose
   * `data.type`, equals `type` — and, when `options.where` is given, whose
   * payload also satisfies that predicate.
   *
   * The message is **consumed**: a second wait for the same type resolves on
   * the *next* such message, never the one already returned. A message that
   * arrived before this call is taken from the queue, oldest first.
   *
   * On a shared instance with parallel workers a bare type match resolves on
   * any worker's event — pass `where` to wait for your own. See the class
   * doc comment.
   *
   * `where` is evaluated against each message as it arrives, and once against
   * everything already queued — never re-run afterwards. So a predicate that
   * closes over a value the test does not have yet (the classic "register the
   * wait, then POST, then correlate on the id the POST returned") declines the
   * message and then waits for one that will never come. Get the id first and
   * then wait, or wait on the type alone.
   */
  waitForMessage(
    type: string,
    options: WaitForMessageOptions = {}
  ): Promise<WsMessage> {
    const { where, timeoutMs = 30_000 } = options;
    const description = where ? `'${type}' (where: …)` : `'${type}'`;

    let already: WsMessage | undefined;
    try {
      already = this.takeQueuedFor(type, where);
    } catch (error) {
      return Promise.reject(
        new Error(
          `the 'where' predicate passed to waitForMessage(${description}) threw ` +
            `while evaluating an already-received message: ${(error as Error)?.message ?? error}`
        )
      );
    }
    if (already !== undefined) return Promise.resolve(already);
    if (this.connectionError) return Promise.reject(this.connectionError);

    return new Promise<WsMessage>((resolve, reject) => {
      const waiter: Waiter = {
        type,
        where,
        description,
        resolve: (message) => {
          clearTimeout(timer);
          resolve(message);
        },
        reject: (error) => {
          clearTimeout(timer);
          reject(error);
        },
      };
      const timer = setTimeout(() => {
        // Deregister before rejecting. A waiter left in the list after its
        // promise is settled would still be handed the next matching
        // message, and resolving a settled promise is a silent no-op — the
        // message would be consumed and discarded, and the test's next wait
        // for that type would hang waiting for an event that already came.
        const index = this.waiters.indexOf(waiter);
        if (index >= 0) this.waiters.splice(index, 1);
        reject(
          new Error(
            `timed out after ${timeoutMs}ms waiting for ws message ` +
              `${description} on ${this.sanitizedUrl}${this.describeReceived()}`
          )
        );
      }, timeoutMs);
      this.waiters.push(waiter);
    });
  }

  close(): void {
    this.closedByUs = true;
    this.socket.close();
  }
}
