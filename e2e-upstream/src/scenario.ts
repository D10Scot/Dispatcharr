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
    // A non-negative integer, matching `parseFaultRequest`'s `channel`. A
    // fractional or negative id renders a playlist URL like
    // `.../stream/1.5.ts`, which can never match the stream route's
    // `(\d+)\.ts` — Dispatcharr gets a 404 that fires *before* the scenario
    // is resolved, so it is not even written to the scenario log.
    isNonNegativeInteger(v.id) &&
    typeof v.name === 'string' &&
    typeof v.tvgId === 'string' &&
    (typeof v.logo === 'string' || v.logo === null)
  );
}

// C0 controls plus DEL. These are the characters that corrupt the
// *structure* of the M3U (a "\n" turns one channel entry into an injected
// second one) or the XMLTV (a NUL makes the document not well-formed). They
// are rejected here, at the door, rather than escaped at render time,
// because `playlist.ts` and `xmltv.ts` must stay free to emit otherwise
// ugly-but-legal content (e.g. an unescaped double quote) for tests that
// want an awkward-but-realistic upstream. A test that wants a deliberately
// malformed document needs an explicit mechanism for it, not one smuggled in
// through a channel name.
const CONTROL_CHARS = /[\x00-\x1F\x7F]/;

function assertNoControlChars(value: string, field: string): void {
  if (CONTROL_CHARS.test(value)) {
    throw new BadRequestError(
      `'channels' entry '${field}' must not contain control characters (e.g. newlines or NUL)`,
    );
  }
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
          "'channels' array entries must each have a non-negative integer id, string name, string tvgId, and a logo that is a string or null",
        );
      }
      // Duplicate ids emit two #EXTINF entries pointing at one stream URL,
      // and a later `channel: n` fault then applies to both — so the
      // scenario cannot express "fault one channel, leave its sibling
      // alone", which is what every failover test needs.
      const ids = new Set<number>();
      for (const channel of body.channels) {
        if (ids.has(channel.id)) {
          throw new BadRequestError(
            `'channels' contains more than one entry with id ${channel.id}; ids must be unique`,
          );
        }
        ids.add(channel.id);
        assertNoControlChars(channel.name, 'name');
        assertNoControlChars(channel.tvgId, 'tvgId');
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

  // `credentialQuery` returns '' when username is undefined, so a password
  // on its own would silently produce an unauthenticated scenario — and a
  // test asserting "wrong credentials are rejected" would pass against a
  // provider that never checks any.
  if (request.password !== undefined && request.username === undefined) {
    throw new BadRequestError("'password' requires 'username'; a password alone is never used");
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
