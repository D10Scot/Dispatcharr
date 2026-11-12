import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import App from '../App';
import useAuthStore from '../store/auth';
import API from '../api';
import { showNotification } from '../utils/notificationUtils';

const stub = vi.hoisted(() => (name) => ({
  default: () => <div data-testid={name} />,
}));
vi.mock('../components/Sidebar', () => stub('sidebar'));
vi.mock('../pages/Login', () => stub('login-page'));
vi.mock('../pages/Channels', () => stub('channels-page'));
vi.mock('../pages/ContentSources', () => stub('x1'));
vi.mock('../pages/Guide', () => stub('x2'));
vi.mock('../pages/Stats', () => stub('x3'));
vi.mock('../pages/DVR', () => stub('x4'));
vi.mock('../pages/Settings', () => stub('x5'));
vi.mock('../pages/Plugins', () => stub('x6'));
vi.mock('../pages/PluginBrowse', () => stub('x7'));
vi.mock('../pages/Connect', () => stub('x8'));
vi.mock('../pages/Users', () => stub('users-page'));
vi.mock('../pages/Logos', () => stub('x10'));
vi.mock('../pages/VODs', () => stub('x11'));
vi.mock('../components/FloatingVideo', () => stub('x12'));
vi.mock('../components/M3URefreshNotification', () => stub('x13'));
vi.mock('../WebSocket', () => ({
  WebsocketProvider: ({ children }) => <>{children}</>,
}));
vi.mock('../utils/notificationUtils', () => ({ showNotification: vi.fn() }));
vi.mock('../api', () => ({
  default: {
    fetchSuperUser: vi.fn(),
    exchangeSsoCode: vi.fn(),
    refreshToken: vi.fn(),
    logout: vi.fn(),
  },
}));

const jwt = () =>
  `h.${btoa(JSON.stringify({ exp: Math.floor(Date.now() / 1000) + 3600 }))}.s`;

describe('App SSO handoff', () => {
  let initData;

  beforeEach(() => {
    localStorage.clear();
    vi.clearAllMocks();
    API.fetchSuperUser.mockResolvedValue({ superuser_exists: true });
    API.logout.mockResolvedValue({});
    // A stale password pair whose refresh the server answers 401.
    localStorage.setItem('refreshToken', 'stale-refresh');
    localStorage.setItem('accessToken', 'stale-access');
    localStorage.setItem('tokenExpiration', '1');
    API.refreshToken.mockImplementation(async (refresh) => {
      if (refresh === 'stale-refresh') {
        throw Object.assign(new Error('401'), { status: 401 });
      }
      return { access: jwt() };
    });
    initData = vi.fn().mockResolvedValue();
    useAuthStore.setState({
      isAuthenticated: false,
      isInitialized: false,
      isInitializing: false,
      accessToken: 'stale-access',
      refreshToken: 'stale-refresh',
      tokenExpiration: '1',
      initData: vi.fn(async () => {
        await initData();
        useAuthStore.setState({ isAuthenticated: true, isInitialized: true });
      }),
    });
    window.history.pushState({}, '', '/login/sso#code=x');
  });

  afterEach(() => {
    window.history.pushState({}, '', '/');
  });

  it('handoff runs before refresh with a stale pair', async () => {
    const access = jwt();
    API.exchangeSsoCode.mockResolvedValue({
      access,
      refresh: 'new-refresh',
      next: '/',
      intent: 'login',
    });

    render(<App />);

    await waitFor(() =>
      expect(screen.getByTestId('channels-page')).toBeInTheDocument()
    );
    expect(API.exchangeSsoCode).toHaveBeenCalledWith('x');
    const exchangeOrder = API.exchangeSsoCode.mock.invocationCallOrder[0];
    for (const order of API.refreshToken.mock.invocationCallOrder) {
      expect(
        exchangeOrder,
        'exchangeSsoCode must run before any refreshToken'
      ).toBeLessThan(order);
    }
    // Never the stale token, never the login page.
    expect(API.refreshToken).not.toHaveBeenCalledWith('stale-refresh');
    expect(screen.queryByTestId('login-page')).not.toBeInTheDocument();
    expect(window.location.pathname).toBe('/channels');
    expect(window.location.hash).toBe('');
    expect(localStorage.getItem('refreshToken')).toBe('new-refresh');
    expect(initData).toHaveBeenCalled();
  });

  it('goes to the login page with an sso_error when the exchange fails', async () => {
    API.exchangeSsoCode.mockRejectedValue(
      Object.assign(new Error('400'), {
        status: 400,
        body: { code: 'handoff_invalid' },
      })
    );

    render(<App />);

    await waitFor(() => expect(window.location.pathname).toBe('/login'));
    expect(window.location.search).toBe('?sso_error=exchange_failed');
    expect(localStorage.getItem('refreshToken')).toBeNull();
    expect(API.refreshToken).not.toHaveBeenCalled();
  });

  it('a link handoff lands on the users page', async () => {
    API.exchangeSsoCode.mockResolvedValue({
      access: jwt(),
      refresh: 'new-refresh',
      next: '/',
      intent: 'link',
    });

    render(<App />);

    await waitFor(() =>
      expect(screen.getByTestId('users-page')).toBeInTheDocument()
    );
  });

  it.each([
    ['a Streamer', 'Unauthorized', 'ui_access_denied'],
    ['a bootstrap failure', 'boom', 'exchange_failed'],
  ])(
    'ends on the login page, not the loader, for %s after a good exchange',
    async (_n, message, code) => {
      API.exchangeSsoCode.mockResolvedValue({
        access: jwt(),
        refresh: 'new-refresh',
        next: '/',
        intent: 'login',
      });
      initData.mockRejectedValue(new Error(message));

      render(<App />);

      await waitFor(() => expect(window.location.pathname).toBe('/login'));
      expect(window.location.search).toBe(`?sso_error=${code}`);
      expect(screen.getByTestId('login-page')).toBeInTheDocument();
      expect(
        screen.queryByTestId('sso-handoff-loader')
      ).not.toBeInTheDocument();
      expect(localStorage.getItem('refreshToken')).toBeNull();
    }
  );
});

describe('App refused link attempt', () => {
  let initData;

  beforeEach(() => {
    localStorage.clear();
    vi.clearAllMocks();
    API.fetchSuperUser.mockResolvedValue({ superuser_exists: true });
    localStorage.setItem('refreshToken', 'good-refresh');
    API.refreshToken.mockResolvedValue({ access: jwt() });
    initData = vi.fn().mockResolvedValue();
    useAuthStore.setState({
      isAuthenticated: false,
      isInitialized: false,
      isInitializing: false,
      initData: vi.fn(async () => {
        await initData();
        useAuthStore.setState({ isAuthenticated: true, isInitialized: true });
      }),
    });
  });

  afterEach(() => {
    window.history.pushState({}, '', '/');
  });

  it('shows the fixed copy for a known code, strips it and lands on the app', async () => {
    window.history.pushState({}, '', '/login?sso_error=link_conflict');

    render(<App />);

    await waitFor(() =>
      expect(screen.getByTestId('channels-page')).toBeInTheDocument()
    );
    expect(showNotification).toHaveBeenCalledTimes(1);
    expect(showNotification.mock.calls[0][0].message).toMatch(
      /already linked to a different user/
    );
    expect(window.location.search).toBe('');
  });

  it('shows generic text for an unknown code, never the raw value', async () => {
    window.history.pushState({}, '', '/login?sso_error=%3Cb%3Eraw%3C%2Fb%3E');

    render(<App />);

    await waitFor(() =>
      expect(screen.getByTestId('channels-page')).toBeInTheDocument()
    );
    const { message } = showNotification.mock.calls[0][0];
    expect(message).toMatch(/could not complete/i);
    expect(message).not.toContain('raw');
    expect(window.location.search).toBe('');
  });

  it('shows nothing when there is no sso_error', async () => {
    window.history.pushState({}, '', '/login');
    render(<App />);
    await waitFor(() =>
      expect(screen.getByTestId('channels-page')).toBeInTheDocument()
    );
    expect(showNotification).not.toHaveBeenCalled();
  });
});
