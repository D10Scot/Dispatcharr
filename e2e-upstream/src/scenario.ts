import { randomUUID } from 'node:crypto';
import { BadRequestError } from './errors.js';

export interface ChannelSpec {
  id: number;
  name: string;
  tvgId: string;
  logo: string | null;
}

export interface ScenarioRequest {
  channels?: number | ChannelSpec[];
  username?: string;
  password?: string;
  maxConnections?: number;
  rate?: number;
}

export interface Scenario {
  id: string;
  channels: ChannelSpec[];
  username?: string;
  password?: string;
  /** null = unlimited. 0 is a real limit meaning reject everything. */
  maxConnections: number | null;
  rate: number;
}

function defaultChannels(count: number): ChannelSpec[] {
  return Array.from({ length: count }, (_unused, index) => {
    const n = index + 1;
    return {
      id: n,
      name: `Fake Channel ${n}`,
      tvgId: `fake-${n}.e2e`,
      // example.invalid is reserved by RFC 2606 and can never resolve, so a
      // logo URL cannot accidentally make a real network request.
      logo: `https://example.invalid/logo-${n}.png`,
    };
  });
}

function isNonNegativeInteger(value: unknown): value is number {
  return typeof value === 'number' && Number.isInteger(value) && value >= 0;
}

function isChannelSpec(value: unknown): value is ChannelSpec {
  if (typeof value !== 'object' || value === null) return false;
  const v = value as Record<string, unknown>;
  return (
    typeof v.id === 'number' &&
    typeof v.name === 'string' &&
    typeof v.tvgId === 'string' &&
    (typeof v.logo === 'string' || v.logo === null)
  );
}

/**
 * Validates a parsed JSON body field-by-field before it ever reaches
 * `ScenarioRegistry.create`, naming the offending field in the thrown
 * `BadRequestError`. Without this, `{ "channels": "x" }` would fall through
 * `Array.isArray` to `defaultChannels(NaN)` and silently produce zero
 * channels — the failure mode this goal exists to eliminate: a later test
 * author sees "expected 3 channels, got 0" and suspects Dispatcharr's
 * parser rather than their own typo in the scenario request.
 */
export function parseScenarioRequest(body: Record<string, unknown>): ScenarioRequest {
  const request: ScenarioRequest = {};

  if (body.channels !== undefined) {
    if (Array.isArray(body.channels)) {
      if (!body.channels.every(isChannelSpec)) {
        throw new BadRequestError(
          "'channels' array entries must each have a numeric id, string name, string tvgId, and a logo that is a string or null",
        );
      }
      request.channels = body.channels as ChannelSpec[];
    } else if (isNonNegativeInteger(body.channels)) {
      request.channels = body.channels;
    } else {
      throw new BadRequestError(
        "'channels' must be a non-negative integer or an array of channel specs",
      );
    }
  }

  if (body.maxConnections !== undefined) {
    if (!isNonNegativeInteger(body.maxConnections)) {
      throw new BadRequestError("'maxConnections' must be a non-negative integer");
    }
    request.maxConnections = body.maxConnections;
  }

  if (body.rate !== undefined) {
    if (typeof body.rate !== 'number' || !(body.rate > 0)) {
      throw new BadRequestError("'rate' must be a number greater than 0");
    }
    request.rate = body.rate;
  }

  if (body.username !== undefined) {
    if (typeof body.username !== 'string') {
      throw new BadRequestError("'username' must be a string");
    }
    request.username = body.username;
  }

  if (body.password !== undefined) {
    if (typeof body.password !== 'string') {
      throw new BadRequestError("'password' must be a string");
    }
    request.password = body.password;
  }

  return request;
}

export class ScenarioRegistry {
  private scenarios = new Map<string, Scenario>();

  create(request: ScenarioRequest): Scenario {
    const channels = Array.isArray(request.channels)
      ? request.channels
      : defaultChannels(request.channels ?? 1);

    const scenario: Scenario = {
      id: randomUUID(),
      channels,
      username: request.username,
      password: request.password,
      // `?? null`, never `|| null`: 0 is a real limit and must survive.
      maxConnections: request.maxConnections ?? null,
      rate: request.rate ?? 1,
    };

    this.scenarios.set(scenario.id, scenario);
    return scenario;
  }

  get(id: string): Scenario | undefined {
    return this.scenarios.get(id);
  }

  list(): Scenario[] {
    return [...this.scenarios.values()];
  }

  delete(id: string): boolean {
    return this.scenarios.delete(id);
  }
}
