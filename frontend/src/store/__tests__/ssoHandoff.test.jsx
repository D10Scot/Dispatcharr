import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import useAuthStore from '../auth';

vi.mock('@mantine/notifications', () => ({
  notifications: { show: vi.fn() },
}));

const jwt = (exp) => `h.${btoa(JSON.stringify({ exp }))}.s`;
const FUTURE = Math.floor(Date.now() / 1000) + 3600;
const ACCESS = jwt(FUTURE);

const json = (body, status = 200) =>
  Promise.resolve(
    new Response(JSON.stringify(body), {
      status,
      headers: { 'Content-Type': 'application/json' },
    })
  );

const resetStore = () =>
  useAuthStore.setState({
    isAuthenticated: false,
    isInitialized: false,
    isInitializing: false,
    accessToken: null,
    refreshToken: null,
    tokenExpiration: null,
    user: null,
  });

describe('SSO handoff', () => {
  let fetchMock;
  const landOn = (hash) =>
    window.history.pushState({}, '', `/login/sso${hash}`);

  beforeEach(() => {
    localStorage.clear();
    resetStore();
    fetchMock = vi.fn(() =>
      json({ access: ACCESS, refresh: 'R', next: '/guide', intent: 'login' })
    );
    vi.stubGlobal('fetch', fetchMock);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
    window.history.pushState({}, '', '/');
  });

  it('completeSsoHandoff strips the fragment before the exchange request', async () => {
    landOn('#code=the-code');
    let hashAtRequest = null;
    fetchMock.mockImplementation((url) => {
      if (String(url).includes('/oidc/exchange/')) {
        hashAtRequest = window.location.hash;
      }
      return json({
        access: ACCESS,
        refresh: 'R',
        next: '/guide',
        intent: 'login',
      });
    });

    const result = await useAuthStore.getState().completeSsoHandoff();

    expect(result.ok).toBe(true);
    expect(hashAtRequest).toBe('');
    expect(window.location.pathname).toBe('/login/sso');
    const [url, options] = fetchMock.mock.calls[0];
    expect(String(url)).toBe('/api/accounts/oidc/exchange/');
    expect(options.method).toBe('POST');
    expect(JSON.parse(options.body)).toEqual({ code: 'the-code' });
  });

  it('stores the pair as a password login does and returns the validated destination', async () => {
    landOn('#code=c');
    const result = await useAuthStore.getState().completeSsoHandoff();

    expect(result).toEqual({ ok: true, intent: 'login', next: '/guide' });
    expect(localStorage.getItem('accessToken')).toBe(ACCESS);
    expect(localStorage.getItem('refreshToken')).toBe('R');
    expect(localStorage.getItem('tokenExpiration')).toBe(String(FUTURE));
    expect(useAuthStore.getState().accessToken).toBe(ACCESS);
  });

  it('never trusts an off-origin or looping destination from the response', async () => {
    for (const next of [
      '//evil.example',
      'https://evil.example',
      '/\\evil',
      '/login',
      '/login/sso',
    ]) {
      landOn('#code=c');
      fetchMock.mockImplementation(() =>
        json({ access: ACCESS, refresh: 'R', next, intent: 'login' })
      );
      const result = await useAuthStore.getState().completeSsoHandoff();
      expect(result.next).toBe('/channels');
    }
  });

  it('maps a failed exchange to sso_error and clears the stored pair', async () => {
    localStorage.setItem('accessToken', 'old');
    localStorage.setItem('refreshToken', 'old');
    landOn('#code=c');
    fetchMock.mockImplementation(() => json({ code: 'handoff_invalid' }, 400));

    const result = await useAuthStore.getState().completeSsoHandoff();

    expect(result).toEqual({ ok: false, ssoError: 'exchange_failed' });
    expect(localStorage.getItem('accessToken')).toBeNull();
    expect(localStorage.getItem('refreshToken')).toBeNull();
  });

  it('makes no request when the fragment carries no code', async () => {
    landOn('');
    const result = await useAuthStore.getState().completeSsoHandoff();
    expect(result).toEqual({ ok: false, ssoError: 'exchange_failed' });
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it('is unauthenticated through the real wrapper even with a stale pair', async () => {
    localStorage.setItem('accessToken', jwt(1));
    localStorage.setItem('tokenExpiration', '1');
    localStorage.setItem('refreshToken', 'stale-refresh');
    landOn('#code=c');
    const hrefSetter = vi.fn();
    const realLocation = window.location;
    vi.stubGlobal('location', {
      get pathname() {
        return realLocation.pathname;
      },
      get search() {
        return realLocation.search;
      },
      get hash() {
        return realLocation.hash;
      },
      get origin() {
        return realLocation.origin;
      },
      get href() {
        return realLocation.href;
      },
      set href(v) {
        hrefSetter(v);
      },
    });

    await useAuthStore.getState().completeSsoHandoff();

    const first = fetchMock.mock.calls[0];
    expect(String(first[0])).toBe('/api/accounts/oidc/exchange/');
    expect(first[1].headers?.Authorization).toBeUndefined();
    expect(
      fetchMock.mock.calls.some(([u]) => String(u).includes('token/refresh'))
    ).toBe(false);
    expect(hrefSetter).not.toHaveBeenCalled();
  });

  it('an authenticated link replaces the pair and resets the initialisation flags', async () => {
    useAuthStore.setState({
      isAuthenticated: true,
      isInitialized: true,
      accessToken: 'old-a',
      refreshToken: 'old-r',
    });
    landOn('#code=c');
    fetchMock.mockImplementation(() =>
      json({ access: ACCESS, refresh: 'R2', next: '/', intent: 'link' })
    );

    const result = await useAuthStore.getState().completeSsoHandoff();

    expect(result).toEqual({ ok: true, intent: 'link', next: '/users' });
    const state = useAuthStore.getState();
    expect(state.accessToken).toBe(ACCESS);
    expect(state.refreshToken).toBe('R2');
    expect(state.isInitialized).toBe(false);
  });

  it('loginWithTokens writes the same three localStorage keys login() writes', () => {
    useAuthStore.getState().loginWithTokens({ access: ACCESS, refresh: 'R' });
    expect(localStorage.getItem('accessToken')).toBe(ACCESS);
    expect(localStorage.getItem('refreshToken')).toBe('R');
    expect(localStorage.getItem('tokenExpiration')).toBe(String(FUTURE));
  });
});
