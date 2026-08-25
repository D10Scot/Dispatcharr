import type { Scenario } from './scenario.js';

export interface LiveConnection {
  readonly scenarioId: string;
  readonly channelId: number;
  setDeadAir(active: boolean): void;
  /** null = follow the scenario's own rate. */
  setRate(rate: number | null): void;
  /**
   * `afterBytes` is a total-bytes-written threshold, not a packet count: the
   * cut is byte-exact and may land mid-TS-packet. That's deliberate, not a
   * rounding bug — it's exactly what a real provider does when it dies
   * mid-write, and it's how a realignment fault is tested. A caller that
   * wants a clean 188-byte boundary must round `afterBytes` to a multiple of
   * `TS_PACKET_SIZE` itself.
   */
  disconnect(options: { clean: boolean; afterBytes?: number }): void;
}

export class ConnectionRegistry {
  private live = new Map<string, Set<LiveConnection>>();

  /**
   * Admits the connection unless the scenario's limit is already reached.
   * `maxConnections` null means unlimited; 0 means reject everything.
   *
   * Must be called, and must succeed, before any byte of the response is
   * written — a rejection that arrives after `streamLoop` has already sent a
   * 200 is a rejection the client never sees.
   */
  tryAcquire(scenario: Scenario, connection: LiveConnection): boolean {
    const set = this.live.get(scenario.id) ?? new Set<LiveConnection>();

    if (scenario.maxConnections !== null && set.size >= scenario.maxConnections) {
      return false;
    }

    set.add(connection);
    this.live.set(scenario.id, set);
    return true;
  }

  release(connection: LiveConnection): void {
    this.live.get(connection.scenarioId)?.delete(connection);
  }

  count(scenarioId: string): number {
    return this.live.get(scenarioId)?.size ?? 0;
  }

  /** Live connections for a scenario, optionally narrowed to one channel. */
  matching(scenarioId: string, channelId?: number): LiveConnection[] {
    const all = [...(this.live.get(scenarioId) ?? [])];
    return channelId === undefined ? all : all.filter((c) => c.channelId === channelId);
  }
}
