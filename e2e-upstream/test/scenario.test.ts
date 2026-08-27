import { describe, it, expect } from 'vitest';
import { ScenarioRegistry, parseScenarioRequest } from '../src/scenario.js';
import { BadRequestError } from '../src/errors.js';

describe('ScenarioRegistry', () => {
  it('generates the requested number of channels with distinct ids and tvg-ids', () => {
    const registry = new ScenarioRegistry();
    const scenario = registry.create({ channels: 3 });

    expect(scenario.channels).toHaveLength(3);
    expect(new Set(scenario.channels.map((c) => c.id)).size).toBe(3);
    expect(new Set(scenario.channels.map((c) => c.tvgId)).size).toBe(3);
  });

  it('defaults to unlimited connections, rate 1, and one channel', () => {
    const registry = new ScenarioRegistry();
    const scenario = registry.create({});

    expect(scenario.maxConnections).toBeNull();
    expect(scenario.rate).toBe(1);
    expect(scenario.channels).toHaveLength(1);
  });

  it('treats maxConnections 0 as reject-all, not as unlimited', () => {
    const registry = new ScenarioRegistry();
    // The distinction D10 rests on: null is unlimited, 0 is a real limit of
    // zero. `request.maxConnections || null` would silently collapse them and
    // disable every connection-limit test without failing anything.
    expect(registry.create({ maxConnections: 0 }).maxConnections).toBe(0);
  });

  it('accepts explicit channel specs verbatim', () => {
    const registry = new ScenarioRegistry();
    const scenario = registry.create({
      channels: [{ id: 7, name: 'Explicit', tvgId: 'explicit.tv', logo: null }],
    });

    expect(scenario.channels).toEqual([
      { id: 7, name: 'Explicit', tvgId: 'explicit.tv', logo: null },
    ]);
  });

  it('gives every scenario a distinct id and does not evict', () => {
    const registry = new ScenarioRegistry();
    const a = registry.create({});
    const b = registry.create({});

    expect(a.id).not.toBe(b.id);
    expect(registry.list()).toHaveLength(2);
    expect(registry.get(a.id)).toBe(a);
  });

  it('deletes on request and reports whether anything was deleted', () => {
    const registry = new ScenarioRegistry();
    const scenario = registry.create({});

    expect(registry.delete(scenario.id)).toBe(true);
    expect(registry.delete(scenario.id)).toBe(false);
    expect(registry.get(scenario.id)).toBeUndefined();
  });
});

describe('parseScenarioRequest', () => {
  it('rejects a non-numeric channels field, naming it, rather than silently producing zero channels', () => {
    expect(() => parseScenarioRequest({ channels: 'x' })).toThrow(BadRequestError);
    expect(() => parseScenarioRequest({ channels: 'x' })).toThrow(/channels/);
  });

  it('rejects a channel spec object missing required fields, naming the field', () => {
    expect(() => parseScenarioRequest({ channels: [{}] })).toThrow(BadRequestError);
    expect(() => parseScenarioRequest({ channels: [{}] })).toThrow(/channels/);
  });

  it('rejects a newline in a channel name, naming the field', () => {
    // A "\n" in `name` would inject an extra line into the rendered M3U,
    // which Dispatcharr would parse as an additional, attacker-controlled
    // channel entry.
    const request = { channels: [{ id: 1, name: 'x\n#EXTINF:-1,Injected', tvgId: 'x.e2e', logo: null }] };
    expect(() => parseScenarioRequest(request)).toThrow(BadRequestError);
    expect(() => parseScenarioRequest(request)).toThrow(/name/);
  });

  it('rejects a NUL byte in a channel tvgId, naming the field', () => {
    // A NUL would make the rendered XMLTV not well-formed.
    const request = { channels: [{ id: 1, name: 'x', tvgId: 'x\x00.e2e', logo: null }] };
    expect(() => parseScenarioRequest(request)).toThrow(BadRequestError);
    expect(() => parseScenarioRequest(request)).toThrow(/tvgId/);
  });

  it('rejects a negative maxConnections, naming the field', () => {
    expect(() => parseScenarioRequest({ maxConnections: -1 })).toThrow(BadRequestError);
    expect(() => parseScenarioRequest({ maxConnections: -1 })).toThrow(/maxConnections/);
  });

  it('rejects a zero or negative rate, naming the field', () => {
    expect(() => parseScenarioRequest({ rate: 0 })).toThrow(BadRequestError);
    expect(() => parseScenarioRequest({ rate: 0 })).toThrow(/rate/);
  });

  it('rejects a non-string username, naming the field', () => {
    expect(() => parseScenarioRequest({ username: 5 })).toThrow(BadRequestError);
    expect(() => parseScenarioRequest({ username: 5 })).toThrow(/username/);
  });

  it('accepts the boundary values a careless validator breaks: maxConnections 0 and rate 0.5', () => {
    expect(parseScenarioRequest({ maxConnections: 0 }).maxConnections).toBe(0);
    expect(parseScenarioRequest({ rate: 0.5 }).rate).toBe(0.5);
  });
});

describe('parseScenarioRequest — channel id and credential validation', () => {
  const spec = (over = {}) => ({ id: 1, name: 'A', tvgId: 'a.e2e', logo: null, ...over });

  it('rejects a fractional channel id', () => {
    // `.../stream/1.5.ts` can never match the stream route's (\d+)\.ts, so
    // Dispatcharr 404s before the scenario is even resolved — the request
    // never reaches the scenario log, which makes it invisible to debug.
    expect(() => parseScenarioRequest({ channels: [spec({ id: 1.5 })] })).toThrow(
      /non-negative integer id/,
    );
  });

  it('rejects a negative channel id', () => {
    expect(() => parseScenarioRequest({ channels: [spec({ id: -1 })] })).toThrow(
      /non-negative integer id/,
    );
  });

  it('rejects duplicate channel ids, naming the offending id', () => {
    expect(() =>
      parseScenarioRequest({ channels: [spec({ id: 2 }), spec({ id: 2, name: 'B' })] }),
    ).toThrow(/more than one entry with id 2/);
  });

  it('accepts id 0 and distinct ids', () => {
    // 0 is a legitimate id and must survive: the same ?? vs || trap that
    // maxConnections has.
    const parsed = parseScenarioRequest({
      channels: [spec({ id: 0 }), spec({ id: 1, name: 'B', tvgId: 'b.e2e' })],
    });
    expect((parsed.channels as { id: number }[]).map((c) => c.id)).toEqual([0, 1]);
  });

  it('rejects a password with no username', () => {
    // credentialQuery returns '' without a username, so this would silently
    // create an unauthenticated scenario — and a test asserting that wrong
    // credentials are rejected would pass against a provider checking none.
    expect(() => parseScenarioRequest({ password: 'p' })).toThrow(/requires 'username'/);
  });

  it('accepts a username with no password', () => {
    // The mirror case is legitimate: an empty password is a real provider
    // configuration, and credentialQuery already emits password=''.
    expect(parseScenarioRequest({ username: 'u' }).username).toBe('u');
  });
});
