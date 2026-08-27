import { describe, it, expect } from 'vitest';
import { ScenarioLog, MAX_ENTRIES } from '../src/log.js';

describe('ScenarioLog', () => {
  it('keeps entries per scenario, oldest first', () => {
    const log = new ScenarioLog();
    log.record('a', { kind: 'request', method: 'GET', path: '/one', status: 200 });
    log.record('a', { kind: 'request', method: 'GET', path: '/two', status: 404 });
    log.record('b', { kind: 'request', method: 'GET', path: '/other', status: 200 });

    expect(log.entries('a').map((e) => e.path)).toEqual(['/one', '/two']);
    expect(log.entries('b')).toHaveLength(1);
  });

  it('stamps every entry with an ISO timestamp', () => {
    const log = new ScenarioLog();
    log.record('a', { kind: 'open', channelId: 1 });

    expect(log.entries('a')[0].at).toMatch(/^\d{4}-\d{2}-\d{2}T/);
  });

  it('records the HTTP method, so a HEAD probe is distinguishable from a client', () => {
    // validate_stream_url probes with HEAD before every redirect-profile
    // stream. A log that did not record the method would show two
    // indistinguishable hits and make the probe look like a real viewer.
    const log = new ScenarioLog();
    log.record('a', { kind: 'request', method: 'HEAD', path: '/s/a/stream/1.ts', status: 200 });

    expect(log.entries('a')[0].method).toBe('HEAD');
  });

  it('caps the history so a long streaming test cannot exhaust memory', () => {
    const log = new ScenarioLog();
    for (let n = 0; n < MAX_ENTRIES + 50; n += 1) {
      log.record('a', { kind: 'request', path: `/${n}` });
    }

    expect(log.entries('a')).toHaveLength(MAX_ENTRIES);
    expect(log.entries('a')[0].path).toBe('/50');
  });

  it('returns an empty list for a scenario that has done nothing', () => {
    expect(new ScenarioLog().entries('unknown')).toEqual([]);
  });
});
