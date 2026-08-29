import { describe, it, expect } from 'vitest';
import { FaultStore, parseFaultRequest } from '../src/faults.js';
import { ConnectionRegistry } from '../src/connections.js';
import type { LiveConnection } from '../src/connections.js';
import { ScenarioRegistry } from '../src/scenario.js';
import { BadRequestError } from '../src/errors.js';

function fakeConnection(scenarioId: string, channelId: number) {
  const calls: string[] = [];
  const connection: LiveConnection = {
    scenarioId,
    channelId,
    setDeadAir: (active) => calls.push(`deadAir:${active}`),
    setRate: (rate) => calls.push(`rate:${rate}`),
    disconnect: (options) => calls.push(`disconnect:${options.clean}`),
    refreshRate: () => calls.push('refreshRate'),
  };
  return { connection, calls };
}

describe('FaultStore', () => {
  it('reports appliedTo 0 for a fault that can only affect the next request', () => {
    // Arming not-found for a reconnect that has not happened yet is a normal
    // test. If this were an error, that test could not be written.
    const scenario = new ScenarioRegistry().create({});
    const result = new FaultStore().apply(
      scenario.id,
      { fault: 'not-found', active: true },
      new ConnectionRegistry()
    );

    expect(result).toEqual({ fault: 'not-found', active: true, appliedTo: 0 });
  });

  it('applies dead air to every live connection and counts them', () => {
    const scenario = new ScenarioRegistry().create({ channels: 2 });
    const connections = new ConnectionRegistry();
    const a = fakeConnection(scenario.id, 1);
    const b = fakeConnection(scenario.id, 2);
    connections.tryAcquire(scenario, a.connection);
    connections.tryAcquire(scenario, b.connection);

    const result = new FaultStore().apply(
      scenario.id,
      { fault: 'dead-air', active: true },
      connections
    );

    expect(result.appliedTo).toBe(2);
    expect(a.calls).toContain('deadAir:true');
    expect(b.calls).toContain('deadAir:true');
  });

  it('narrows to one channel when the request names one', () => {
    // Every failover trigger switches to the channel's *next* Stream row. A
    // scenario-wide fault takes both down, and the test cannot then tell
    // "switched" from "didn't".
    const scenario = new ScenarioRegistry().create({ channels: 2 });
    const connections = new ConnectionRegistry();
    const a = fakeConnection(scenario.id, 1);
    const b = fakeConnection(scenario.id, 2);
    connections.tryAcquire(scenario, a.connection);
    connections.tryAcquire(scenario, b.connection);

    const result = new FaultStore().apply(
      scenario.id,
      { fault: 'dead-air', active: true, channel: 1 },
      connections
    );

    expect(result.appliedTo).toBe(1);
    expect(a.calls).toContain('deadAir:true');
    expect(b.calls).toHaveLength(0);
  });

  it('defaults disconnect to abrupt', () => {
    const scenario = new ScenarioRegistry().create({});
    const connections = new ConnectionRegistry();
    const a = fakeConnection(scenario.id, 1);
    connections.tryAcquire(scenario, a.connection);

    new FaultStore().apply(scenario.id, { fault: 'disconnect', active: true }, connections);

    expect(a.calls).toContain('disconnect:false');
  });

  it('reports a fault as active only for the channel it was scoped to', () => {
    const store = new FaultStore();
    const scenario = new ScenarioRegistry().create({ channels: 2 });

    store.apply(scenario.id, { fault: 'not-found', active: true, channel: 1 }, new ConnectionRegistry());

    expect(store.isActive(scenario.id, 'not-found', 1)).toBe(true);
    expect(store.isActive(scenario.id, 'not-found', 2)).toBe(false);
  });

  it('clears a fault when active is false', () => {
    const store = new FaultStore();
    const scenario = new ScenarioRegistry().create({});
    const connections = new ConnectionRegistry();

    store.apply(scenario.id, { fault: 'not-found', active: true }, connections);
    const cleared = store.apply(scenario.id, { fault: 'not-found', active: false }, connections);

    expect(cleared.active).toBe(false);
    expect(store.isActive(scenario.id, 'not-found')).toBe(false);
  });

  it('restores the scenario rate when slow-trickle is cleared', () => {
    const scenario = new ScenarioRegistry().create({});
    const connections = new ConnectionRegistry();
    const a = fakeConnection(scenario.id, 1);
    connections.tryAcquire(scenario, a.connection);
    const store = new FaultStore();

    store.apply(scenario.id, { fault: 'slow-trickle', active: true, rate: 0.05 }, connections);
    store.apply(scenario.id, { fault: 'slow-trickle', active: false }, connections);

    // null, not 1: the connection must go back to following the scenario's
    // own rate, which a test may have set to something other than 1.
    expect(a.calls).toEqual(['rate:0.05', 'rate:null']);
  });

  it('leaves the rest of the scenario armed when the fault is narrowed to one channel', () => {
    // Regression for keying the store by fault name alone: narrowing or
    // clearing one channel's fault used to delete the *only* stored entry,
    // corrupting every other channel's state along with it.
    const store = new FaultStore();
    const scenario = new ScenarioRegistry().create({ channels: 2 });
    const connections = new ConnectionRegistry();
    const a = fakeConnection(scenario.id, 1);
    const b = fakeConnection(scenario.id, 2);
    connections.tryAcquire(scenario, a.connection);
    connections.tryAcquire(scenario, b.connection);

    const armed = store.apply(scenario.id, { fault: 'dead-air', active: true }, connections);
    expect(armed.appliedTo).toBe(2);

    const narrowed = store.apply(
      scenario.id,
      { fault: 'dead-air', active: false, channel: 2 },
      connections
    );
    expect(narrowed.appliedTo).toBe(1);
    expect(b.calls).toContain('deadAir:false');

    // Channel 1 must still read as armed — this is the assertion that fails
    // under fault-name-only keying, since the narrowing call above deletes
    // the whole stored config rather than just channel 2's slice of it.
    expect(store.isActive(scenario.id, 'dead-air', 1)).toBe(true);
    expect(store.isActive(scenario.id, 'dead-air', 2)).toBe(false);
  });

  it('does not let a channel-specific arm overwrite a scenario-wide arm of the same fault', () => {
    // The mirror of the above: arming a fault for one channel while it's
    // already armed scenario-wide must not silently narrow the stored
    // config for every other channel.
    const store = new FaultStore();
    const scenario = new ScenarioRegistry().create({ channels: 2 });
    const connections = new ConnectionRegistry();
    const a = fakeConnection(scenario.id, 1);
    const b = fakeConnection(scenario.id, 2);
    connections.tryAcquire(scenario, a.connection);
    connections.tryAcquire(scenario, b.connection);

    store.apply(scenario.id, { fault: 'dead-air', active: true }, connections);
    store.apply(scenario.id, { fault: 'dead-air', active: true, channel: 2 }, connections);

    expect(store.isActive(scenario.id, 'dead-air', 1)).toBe(true);
    expect(store.isActive(scenario.id, 'dead-air', 2)).toBe(true);
  });

  it('lets a channel-specific slow-trickle rate override a different scenario-wide one', () => {
    const store = new FaultStore();
    const scenario = new ScenarioRegistry().create({ channels: 2 });
    const connections = new ConnectionRegistry();

    store.apply(scenario.id, { fault: 'slow-trickle', active: true, rate: 0.2 }, connections);
    store.apply(
      scenario.id,
      { fault: 'slow-trickle', active: true, rate: 0.05, channel: 2 },
      connections
    );

    expect(store.configOf(scenario.id, 'slow-trickle', 1)?.rate).toBe(0.2);
    expect(store.configOf(scenario.id, 'slow-trickle', 2)?.rate).toBe(0.05);
  });

  it('resolves initialStateFor per channel, independent of a scenario-wide arm', () => {
    // This is the scenario the reviewer flagged as most damaging: after the
    // initialStateFor fix, the *stored* config is what a reconnecting
    // client inherits, so a divergence between the store and live state
    // produces exactly the "channel recovered on its own" confusion that
    // fix exists to eliminate.
    const store = new FaultStore();
    const scenario = new ScenarioRegistry().create({ channels: 2 });
    const connections = new ConnectionRegistry();

    store.apply(scenario.id, { fault: 'dead-air', active: true }, connections);
    store.apply(scenario.id, { fault: 'dead-air', active: false, channel: 2 }, connections);

    expect(store.initialStateFor(scenario.id, 1).deadAir).toBe(true);
    expect(store.initialStateFor(scenario.id, 2).deadAir).toBe(false);
  });
});

describe('parseFaultRequest', () => {
  it('rejects an unknown fault name, listing the valid ones', () => {
    expect(() => parseFaultRequest({ fault: 'dead-ait', active: true })).toThrow(BadRequestError);
    try {
      parseFaultRequest({ fault: 'dead-ait', active: true });
      expect.unreachable();
    } catch (error) {
      expect((error as Error).message).toContain('dead-air');
    }
  });

  it('rejects a missing or non-boolean active', () => {
    expect(() => parseFaultRequest({ fault: 'dead-air' })).toThrow(BadRequestError);
    expect(() => parseFaultRequest({ fault: 'dead-air', active: 'true' })).toThrow(BadRequestError);
  });

  it('accepts a fully-specified request verbatim', () => {
    const request = parseFaultRequest({
      fault: 'disconnect',
      active: true,
      channel: 2,
      clean: true,
      afterBytes: 4096,
    });

    expect(request).toEqual({
      fault: 'disconnect',
      active: true,
      channel: 2,
      clean: true,
      afterBytes: 4096,
    });
  });

  it('rejects a non-integer channel', () => {
    expect(() => parseFaultRequest({ fault: 'dead-air', active: true, channel: 1.5 })).toThrow(
      BadRequestError
    );
  });

  it('rejects a rate that is not a positive number', () => {
    expect(() =>
      parseFaultRequest({ fault: 'slow-trickle', active: true, rate: 0 })
    ).toThrow(BadRequestError);
    expect(() =>
      parseFaultRequest({ fault: 'slow-trickle', active: true, rate: 'slow' })
    ).toThrow(BadRequestError);
  });

  it('rejects a non-boolean clean', () => {
    expect(() =>
      parseFaultRequest({ fault: 'disconnect', active: true, clean: 'yes' })
    ).toThrow(BadRequestError);
  });

  it('rejects a negative or non-integer afterBytes', () => {
    expect(() =>
      parseFaultRequest({ fault: 'disconnect', active: true, afterBytes: -1 })
    ).toThrow(BadRequestError);
    expect(() =>
      parseFaultRequest({ fault: 'disconnect', active: true, afterBytes: 1.5 })
    ).toThrow(BadRequestError);
  });

  it('rejects a negative or non-integer depth', () => {
    expect(() =>
      parseFaultRequest({ fault: 'redirect-chain', active: true, depth: -1 })
    ).toThrow(BadRequestError);
    expect(() =>
      parseFaultRequest({ fault: 'redirect-chain', active: true, depth: 1.5 })
    ).toThrow(BadRequestError);
  });

  it('accepts depth at the cap and rejects one past it', () => {
    // A typo'd depth (e.g. a stray zero) should 400 immediately rather than
    // producing a legitimate-but-enormous redirect chain that just hangs a
    // test.
    expect(parseFaultRequest({ fault: 'redirect-chain', active: true, depth: 20 }).depth).toBe(20);
    expect(() =>
      parseFaultRequest({ fault: 'redirect-chain', active: true, depth: 21 })
    ).toThrow(BadRequestError);
  });
});

describe('the G8 faults', () => {
  it('accepts the four new names', () => {
    for (const fault of ['xc-auth-envelope', 'no-tv-archive', 'range-unsupported'] as const) {
      expect(parseFaultRequest({ fault, active: true }).fault).toBe(fault);
    }
    expect(parseFaultRequest({ fault: 'catchup-layout-404', active: true, layout: 'path' }).layout).toBe(
      'path'
    );
  });

  it('requires a layout on catchup-layout-404 when arming', () => {
    // Without a layout this is indistinguishable from `not-found`, and the
    // cascade — the part of catch-up most likely to be wrong — becomes
    // unobservable. Rejected at the door rather than defaulted.
    expect(() => parseFaultRequest({ fault: 'catchup-layout-404', active: true })).toThrow(/layout/);
    expect(() =>
      parseFaultRequest({ fault: 'catchup-layout-404', active: true, layout: 'both' })
    ).toThrow(/path.*query/);
  });

  it('does not require a layout on catchup-layout-404 when clearing', () => {
    // clearFault(scenario, 'catchup-layout-404') sends no `layout` — there is
    // nothing left to disambiguate once the fault is off, since `isActive`
    // alone decides. Requiring one here would make clearing impossible from
    // the same call shape every other fault clears with.
    expect(parseFaultRequest({ fault: 'catchup-layout-404', active: false })).toEqual({
      fault: 'catchup-layout-404',
      active: false,
    });
  });

  it('still rejects a garbage layout on clear', () => {
    expect(() =>
      parseFaultRequest({ fault: 'catchup-layout-404', active: false, layout: 'both' })
    ).toThrow(/path.*query/);
  });

  it('rejects layout on any fault other than catchup-layout-404', () => {
    expect(() => parseFaultRequest({ fault: 'not-found', active: true, layout: 'path' })).toThrow(
      /layout/
    );
  });

  it('rejects a channel on the two scenario-wide-only faults', () => {
    // Without this, `{ fault: 'range-unsupported', active: true, channel: 7 }`
    // would validate, store under scope 7, and the router — which calls
    // isActive/configOf for these two faults with no channel argument — would
    // never read that scope back. The response would be 200/appliedTo:0,
    // byte-identical to a correctly armed fault, and it would silently do
    // nothing. Fix-round-1 finding.
    expect(() =>
      parseFaultRequest({ fault: 'xc-auth-envelope', active: true, channel: 1 })
    ).toThrow(/channel.*scenario-wide/);
    expect(() =>
      parseFaultRequest({ fault: 'range-unsupported', active: true, channel: 1 })
    ).toThrow(/channel.*scenario-wide/);
  });

  it('still accepts a channel on no-tv-archive and catchup-layout-404', () => {
    // The other two G8 faults ARE channel-scopable — this is not a blanket
    // ban on `channel` for the new fault set, only the two that have no
    // channel to narrow to.
    expect(
      parseFaultRequest({ fault: 'no-tv-archive', active: true, channel: 2 }).channel
    ).toBe(2);
    expect(
      parseFaultRequest({ fault: 'catchup-layout-404', active: true, layout: 'path', channel: 2 })
        .channel
    ).toBe(2);
  });

  it('reports appliedTo 0 for all four, even with a live connection open', () => {
    // All four can only affect the next request: a live response has already
    // sent its headers. Zero is correct here, not a partial failure — proven
    // by opening a real connection first, so a bug that made one of these
    // faults reach a live connection would flip this test, not just leave it
    // vacuously true.
    const scenario = new ScenarioRegistry().create({ channels: 1 });
    const store = new FaultStore();
    const connections = new ConnectionRegistry();
    const { connection } = fakeConnection(scenario.id, 1);
    connections.tryAcquire(scenario, connection);

    for (const fault of ['xc-auth-envelope', 'no-tv-archive', 'range-unsupported'] as const) {
      expect(store.apply(scenario.id, { fault, active: true }, connections).appliedTo).toBe(0);
    }
    expect(
      store.apply(scenario.id, { fault: 'catchup-layout-404', active: true, layout: 'path' }, connections)
        .appliedTo
    ).toBe(0);
  });
});
