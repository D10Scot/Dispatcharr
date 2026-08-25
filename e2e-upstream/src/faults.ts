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
    if (typeof body.depth !== 'number' || !Number.isInteger(body.depth) || body.depth < 0) {
      throw new BadRequestError("'depth' must be a non-negative integer");
    }
    request.depth = body.depth;
  }

  return request;
}

/**
 * Per-scenario fault state, keyed by fault name so at most one configuration
 * of each fault is active at a time. `apply` both records the configuration
 * (for `isActive`/`configOf`, consulted by request-time checks in
 * `server.ts`) and, for the three faults that can reach an already-open
 * socket, drives the live connections directly.
 *
 * `appliedTo` counts only connections a fault actually reached. Five of the
 * eight faults (`not-found`, `auth-failure`, `connection-limit`,
 * `redirect-chain`, `non-ts-bytes`) can only affect the *next* request,
 * because a live response has already sent its headers — for those,
 * `appliedTo: 0` is correct and expected, not a sign nothing happened.
 * "Arm not-found so the next reconnect fails" is a normal test.
 */
export class FaultStore {
  private byScenario = new Map<string, Map<FaultName, FaultRequest>>();

  apply(scenarioId: string, request: FaultRequest, connections: ConnectionRegistry): FaultResult {
    const faults = this.byScenario.get(scenarioId) ?? new Map<FaultName, FaultRequest>();
    this.byScenario.set(scenarioId, faults);

    if (request.active) faults.set(request.fault, request);
    else faults.delete(request.fault);

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

  isActive(scenarioId: string, fault: FaultName, channelId?: number): boolean {
    const stored = this.byScenario.get(scenarioId)?.get(fault);
    if (stored === undefined) return false;
    if (stored.channel === undefined) return true;
    return stored.channel === channelId;
  }

  configOf(scenarioId: string, fault: FaultName): FaultRequest | undefined {
    return this.byScenario.get(scenarioId)?.get(fault);
  }

  clearAll(scenarioId: string): void {
    this.byScenario.delete(scenarioId);
  }
}
