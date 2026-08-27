import type { ConnectionRegistry } from './connections.js';
import { BadRequestError } from './errors.js';

export type FaultName =
  | 'dead-air'
  | 'slow-trickle'
  | 'disconnect'
  | 'not-found'
  | 'auth-failure'
  | 'connection-limit'
  | 'redirect-chain'
  | 'non-ts-bytes';

export const FAULT_NAMES: readonly FaultName[] = [
  'dead-air',
  'slow-trickle',
  'disconnect',
  'not-found',
  'auth-failure',
  'connection-limit',
  'redirect-chain',
  'non-ts-bytes',
];

function isFaultName(value: unknown): value is FaultName {
  return typeof value === 'string' && (FAULT_NAMES as readonly string[]).includes(value);
}

export interface FaultRequest {
  fault: FaultName;
  active: boolean;
  channel?: number;
  /** slow-trickle, default 0.1. */
  rate?: number;
  /** disconnect, default false (abrupt). */
  clean?: boolean;
  /** disconnect. */
  afterBytes?: number;
  /** redirect-chain, default DEFAULT_REDIRECT_DEPTH. */
  depth?: number;
}

export interface FaultResult {
  fault: FaultName;
  active: boolean;
  appliedTo: number;
}

const DEFAULT_TRICKLE_RATE = 0.1;
export const DEFAULT_REDIRECT_DEPTH = 2;
// Far more than any real provider chain (G5's tests use 2-3); bounding it
// turns a typo'd `depth: 10000` into an immediate, readable 400 instead of a
// legitimate-but-enormous redirect chain that just hangs a test.
const MAX_REDIRECT_DEPTH = 20;

/**
 * Validates a parsed JSON body into a `FaultRequest` before it ever reaches
 * `FaultStore.apply`, the same validate-then-use pattern `parseScenarioRequest`
 * uses. An unrecognised `fault` names the valid set in the error rather than
 * failing silently — without this, `{ "fault": "dead-ait" }` would never
 * match any `isActive` check and the test author would spend their time
 * suspecting Dispatcharr instead of their own typo.
 */
export function parseFaultRequest(body: Record<string, unknown>): FaultRequest {
  if (!isFaultName(body.fault)) {
    throw new BadRequestError(
      `'fault' must be one of ${FAULT_NAMES.join(', ')}; got ${JSON.stringify(body.fault)}`,
    );
  }

  if (typeof body.active !== 'boolean') {
    throw new BadRequestError("'active' must be a boolean");
  }

  const request: FaultRequest = { fault: body.fault, active: body.active };

  if (body.channel !== undefined) {
    if (typeof body.channel !== 'number' || !Number.isInteger(body.channel)) {
      throw new BadRequestError("'channel' must be an integer");
    }
    request.channel = body.channel;
  }

  if (body.rate !== undefined) {
    if (typeof body.rate !== 'number' || !(body.rate > 0)) {
      throw new BadRequestError("'rate' must be a number greater than 0");
    }
    request.rate = body.rate;
  }

  if (body.clean !== undefined) {
    if (typeof body.clean !== 'boolean') {
      throw new BadRequestError("'clean' must be a boolean");
    }
    request.clean = body.clean;
  }

  if (body.afterBytes !== undefined) {
    if (typeof body.afterBytes !== 'number' || !Number.isInteger(body.afterBytes) || body.afterBytes < 0) {
      throw new BadRequestError("'afterBytes' must be a non-negative integer");
    }
    request.afterBytes = body.afterBytes;
  }

  if (body.depth !== undefined) {
    if (
      typeof body.depth !== 'number' ||
      !Number.isInteger(body.depth) ||
      body.depth < 0 ||
      body.depth > MAX_REDIRECT_DEPTH
    ) {
      throw new BadRequestError(
        `'depth' must be an integer between 0 and ${MAX_REDIRECT_DEPTH}`,
      );
    }
    request.depth = body.depth;
  }

  return request;
}

// A fault's stored configuration is scoped independently per channel, or to
// the whole scenario under the '*' key when no channel was given. Two scopes
// of the *same* fault must not share a slot: arming `dead-air` scenario-wide
// and then narrowing/clearing it for one channel must leave every other
// channel's stored state untouched, and the reverse (a channel-specific arm
// alongside a scenario-wide one) must not overwrite the wildcard either.
// Channel ids are always non-negative integers (see parseFaultRequest), so
// '*' can never collide with a real one.
type Scope = number | '*';
const scopeOf = (channel: number | undefined): Scope => channel ?? '*';

/**
 * Per-scenario fault state, keyed by `(fault, scope)` so a channel-specific
 * entry and a scenario-wide entry for the same fault never clobber each
 * other. `apply` both records the configuration (for `isActive`/`configOf`,
 * consulted by request-time checks in `server.ts`, and by
 * `initialStateFor` for a brand-new connection) and, for the three faults
 * that can reach an already-open socket, drives the live connections
 * directly.
 *
 * Entries are stored whether `active` is true or false — never deleted —
 * so an explicit `{ active: false, channel: 2 }` while the fault is still
 * armed scenario-wide is itself a real, persisted fact ("channel 2 is
 * explicitly clear"), not merely the absence of one. Deleting on `false`
 * was the original bug: with one slot per fault (not per scope), narrowing
 * or clearing one channel's fault deleted the *only* stored entry outright,
 * corrupting every other channel's state along with it.
 *
 * `isActive`/`configOf` resolve a channel-scoped query by specificity, not
 * recency: an entry stored under that exact channel always wins over one
 * stored under '*', regardless of which was armed more recently. This is
 * what makes "arm scenario-wide, then narrow one channel" and "arm
 * scenario-wide, then arm one channel differently" both behave as
 * independent per-scope state rather than one clobbering the other.
 *
 * `appliedTo` counts only connections a fault actually reached. Five of the
 * eight faults (`not-found`, `auth-failure`, `connection-limit`,
 * `redirect-chain`, `non-ts-bytes`) can only affect the *next* request,
 * because a live response has already sent its headers — for those,
 * `appliedTo: 0` is correct and expected, not a sign nothing happened.
 * "Arm not-found so the next reconnect fails" is a normal test.
 */
export class FaultStore {
  private byScenario = new Map<string, Map<FaultName, Map<Scope, FaultRequest>>>();

  apply(scenarioId: string, request: FaultRequest, connections: ConnectionRegistry): FaultResult {
    const byFault = this.byScenario.get(scenarioId) ?? new Map<FaultName, Map<Scope, FaultRequest>>();
    this.byScenario.set(scenarioId, byFault);

    const byScope = byFault.get(request.fault) ?? new Map<Scope, FaultRequest>();
    byFault.set(request.fault, byScope);

    byScope.set(scopeOf(request.channel), request);

    const targets = connections.matching(scenarioId, request.channel);
    let appliedTo = 0;

    for (const connection of targets) {
      switch (request.fault) {
        case 'dead-air':
          connection.setDeadAir(request.active);
          appliedTo += 1;
          break;
        case 'slow-trickle':
          // null on clear, so the connection returns to following the
          // scenario's own rate rather than being pinned to 1 — a test may
          // have deliberately set that rate to something other than 1, and
          // clearing the fault must not silently override it.
          connection.setRate(request.active ? (request.rate ?? DEFAULT_TRICKLE_RATE) : null);
          appliedTo += 1;
          break;
        case 'disconnect':
          if (request.active) {
            connection.disconnect({
              clean: request.clean ?? false,
              afterBytes: request.afterBytes,
            });
            appliedTo += 1;
          }
          break;
        default:
          // not-found, auth-failure, connection-limit, redirect-chain,
          // non-ts-bytes: headers are already sent on a live response, so
          // these can only affect the next request. appliedTo stays 0.
          break;
      }
    }

    return { fault: request.fault, active: request.active, appliedTo };
  }

  /**
   * A channel-scoped entry wins over a scenario-wide one for that same
   * channel — see the class comment for why both can legitimately exist at
   * once and why specificity, not recency, has to be the tiebreaker.
   */
  isActive(scenarioId: string, fault: FaultName, channelId?: number): boolean {
    return this.mostSpecific(scenarioId, fault, channelId)?.active ?? false;
  }

  configOf(scenarioId: string, fault: FaultName, channelId?: number): FaultRequest | undefined {
    return this.mostSpecific(scenarioId, fault, channelId);
  }

  private mostSpecific(
    scenarioId: string,
    fault: FaultName,
    channelId: number | undefined,
  ): FaultRequest | undefined {
    const byScope = this.byScenario.get(scenarioId)?.get(fault);
    if (!byScope) return undefined;

    const specific = channelId !== undefined ? byScope.get(channelId) : undefined;
    return specific ?? byScope.get('*');
  }

  /**
   * The dead-air/rate state a brand-new connection should start in, given
   * whatever `dead-air`/`slow-trickle` faults are already armed for this
   * scenario (and this channel, or scenario-wide) at the moment it connects.
   *
   * Both faults are documented as applying to "live + new" connections —
   * `apply` above only reaches *live* ones, by walking the connections that
   * exist at that instant. Without this second entry point, a connection
   * opened *after* the fault is armed streams perfectly healthily: for
   * `dead-air`, a G4 test asserting Dispatcharr keeps failing over would see
   * the reconnected socket recover instead, and misread that as product
   * behaviour rather than a provider limitation. For `slow-trickle`, arm-then-
   * connect is the *only* supported use — ffmpeg's `speed=` is cumulative
   * from process start, so the fault has to be in effect before the process
   * starts — so this path is load-bearing, not a nice-to-have.
   *
   * `appliedTo` on `apply` is unaffected: it still counts only connections
   * reached at apply time, so pre-arming still legitimately reports 0.
   */
  initialStateFor(scenarioId: string, channelId: number): { deadAir: boolean; rate: number | null } {
    const deadAir = this.isActive(scenarioId, 'dead-air', channelId);

    // Passing channelId here matters, not just to isActive below: without
    // it, a channel-specific slow-trickle rate that overrides a different
    // scenario-wide one would read the wrong config even while isActive
    // correctly reports the fault as armed for this channel.
    const trickle = this.configOf(scenarioId, 'slow-trickle', channelId);
    const rate =
      trickle && this.isActive(scenarioId, 'slow-trickle', channelId)
        ? trickle.rate ?? DEFAULT_TRICKLE_RATE
        : null;

    return { deadAir, rate };
  }

  clearAll(scenarioId: string): void {
    this.byScenario.delete(scenarioId);
  }
}
