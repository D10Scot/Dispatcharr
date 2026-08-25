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
