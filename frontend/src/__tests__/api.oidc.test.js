// @vitest-environment jsdom
// @vitest-environment-options {"url": "http://localhost:9191/login"}
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import API from '../api';

vi.mock('@mantine/notifications', () => ({
  notifications: { show: vi.fn() },
}));

const jwt = (exp) => `h.${btoa(JSON.stringify({ exp }))}.s`;

const json = (body, status = 200) =>
  Promise.resolve(
    new Response(JSON.stringify(body), {
      status,
      headers: { 'Content-Type': 'application/json' },
    })
  );

describe('OIDC browser endpoints', () => {
  let fetchMock;

  beforeEach(() => {
    fetchMock = vi.fn(() => json({}));
    vi.stubGlobal('fetch', fetchMock);
    localStorage.clear();
    // An expired access token and a refresh token: a wrapper that tried to
    // authenticate would call token/refresh/ first.
    localStorage.setItem('accessToken', jwt(1));
    localStorage.setItem('tokenExpiration', '1');
    localStorage.setItem('refreshToken', 'stale-refresh');
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
    localStorage.clear();
  });

  const resolved = (call) => new URL(call[0], window.location.href);

  it('OIDC endpoints are origin-relative in dev', async () => {
    expect(import.meta.env.DEV).toBe(true);
    expect(window.location.origin).toBe('http://localhost:9191');
    fetchMock.mockImplementation(() => json({ authorize_url: 'x' }));
    // startSsoLink is the one authenticated call: give it a live token so the
    // only requests made are the three under test.
    const future = Math.floor(Date.now() / 1000) + 3600;
    localStorage.setItem('accessToken', jwt(future));
    localStorage.setItem('tokenExpiration', String(future));

    await API.getAuthConfig();
    await API.exchangeSsoCode('c');
    await API.startSsoLink('entra', '/users');

    expect(fetchMock).toHaveBeenCalledTimes(3);
    for (const call of fetchMock.mock.calls) {
      const url = resolved(call);
      expect(url.origin).toBe('http://localhost:9191');
      expect(url.pathname.startsWith('/api/accounts/oidc/')).toBe(true);
      expect(call[1]?.credentials).not.toBe('omit');
    }
  });

  it('exchange is sent unauthenticated through the real wrapper', async () => {
    await API.exchangeSsoCode('the-code');

    const [url, options] = fetchMock.mock.calls[0];
    expect(
      resolved([url]).pathname,
      'the first request must be the exchange, not a token refresh'
    ).toBe('/api/accounts/oidc/exchange/');
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(options.method).toBe('POST');
    expect(options.headers?.Authorization).toBeUndefined();
    expect(JSON.parse(options.body)).toEqual({ code: 'the-code' });
    const refreshCalls = fetchMock.mock.calls.filter(([u]) =>
      String(u).includes('token/refresh')
    );
    expect(refreshCalls).toHaveLength(0);
  });

  it('login configuration is fetched unauthenticated through the real wrapper', async () => {
    await API.getAuthConfig();

    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [url, options] = fetchMock.mock.calls[0];
    expect(resolved([url]).pathname).toBe('/api/accounts/oidc/providers/');
    expect(options.headers?.Authorization).toBeUndefined();
  });
});
