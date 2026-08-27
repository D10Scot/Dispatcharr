export interface LogEntry {
  at: string;
  kind: 'request' | 'open' | 'close' | 'fault';
  method?: string;
  path?: string;
  status?: number;
  channelId?: number;
  bytes?: number;
  durationMs?: number;
  fault?: string;
  detail?: string;
}

/**
 * Bounded because a streaming test can hold a connection for five minutes and
 * a scenario is never evicted. Old entries are dropped, not new ones: the
 * interesting end of a failure is the recent end.
 */
export const MAX_ENTRIES = 2000;

/**
 * Per-scenario request/connection/fault history, read back via
 * `GET /s/<id>/log` so a failing G4 test can be diagnosed from the attached
 * JSON artifact rather than reproduced live. See `server.ts` for the four
 * points that call `record`.
 */
export class ScenarioLog {
  private byScenario = new Map<string, LogEntry[]>();

  record(scenarioId: string, entry: Omit<LogEntry, 'at'>): void {
    const entries = this.byScenario.get(scenarioId) ?? [];
    entries.push({ at: new Date().toISOString(), ...entry });
    if (entries.length > MAX_ENTRIES) entries.splice(0, entries.length - MAX_ENTRIES);
    this.byScenario.set(scenarioId, entries);
  }

  entries(scenarioId: string): LogEntry[] {
    return this.byScenario.get(scenarioId) ?? [];
  }

  clear(scenarioId: string): void {
    this.byScenario.delete(scenarioId);
  }
}
