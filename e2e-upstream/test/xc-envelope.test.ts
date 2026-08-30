import { describe, it, expect } from 'vitest';
import { ScenarioRegistry } from '../src/scenario.js';
import { renderAccountEnvelope } from '../src/xc/envelope.js';

const scenario = () =>
  new ScenarioRegistry().create({ xc: true, username: 'user', password: 'pass' });

describe('renderAccountEnvelope', () => {
  it('carries every user_info and server_info key get_account_info() copies', () => {
    const envelope = renderAccountEnvelope(scenario(), new Date('2026-08-29T12:00:00Z'), 'h:8080');
    const userInfo = envelope.user_info as Record<string, unknown>;
    const serverInfo = envelope.server_info as Record<string, unknown>;

    // core/xtream_codes.py, Client.get_account_info — this is the exact set it
    // copies into M3UAccountProfile.custom_properties. A key missing here is a
    // key Dispatcharr silently stores as null.
    for (const key of [
      'username', 'password', 'message', 'auth', 'status', 'exp_date', 'is_trial',
      'active_cons', 'created_at', 'max_connections', 'allowed_output_formats',
    ]) {
      expect(userInfo).toHaveProperty(key);
    }
    for (const key of [
      'url', 'port', 'https_port', 'server_protocol', 'rtmp_port', 'timezone',
      'timestamp_now', 'time_now',
    ]) {
      expect(serverInfo).toHaveProperty(key);
    }
  });

  it('declares timezone UTC so a catch-up timestamp is not converted', () => {
    // convert_timestamp_to_provider_tz returns its input unchanged for a falsy
    // value or exactly "UTC". Anything else makes every catch-up assertion
    // depend on the date the suite runs (DST).
    const envelope = renderAccountEnvelope(scenario(), new Date(), 'h:8080');
    expect((envelope.server_info as Record<string, unknown>).timezone).toBe('UTC');
  });

  it('emits exp_date as a numeric string in the future', () => {
    // M3UAccountProfile.save() re-parses this on every save via float(), then
    // datetime.fromisoformat(). A shape like "2026-12-31 00:00:00" parses as
    // neither and is dropped without a warning.
    const now = new Date('2026-08-29T12:00:00Z');
    const expDate = (renderAccountEnvelope(scenario(), now, 'h:8080').user_info as Record<string, unknown>)
      .exp_date;
    expect(typeof expDate).toBe('string');
    expect(Number(expDate)).toBeGreaterThan(now.getTime() / 1000);
  });

  it('echoes the scenario credentials and never emits a top-level error key', () => {
    // _make_request raises when a dict has no user_info AND an 'error' key;
    // emitting one on a success is how a provider accidentally fails auth.
    const envelope = renderAccountEnvelope(scenario(), new Date(), 'h:8080');
    expect((envelope.user_info as Record<string, unknown>).username).toBe('user');
    expect(envelope).not.toHaveProperty('error');
  });

  it('lets a scenario override any user_info or server_info field', () => {
    const registry = new ScenarioRegistry();
    const custom = registry.create({
      xc: true,
      username: 'u',
      account: { serverInfo: { timezone: 'Europe/Brussels' }, userInfo: { max_connections: '4' } },
    });
    const envelope = renderAccountEnvelope(custom, new Date(), 'h:8080');
    expect((envelope.server_info as Record<string, unknown>).timezone).toBe('Europe/Brussels');
    expect((envelope.user_info as Record<string, unknown>).max_connections).toBe('4');
  });
});
