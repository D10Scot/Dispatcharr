import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MantineProvider } from '@mantine/core';
import LoginForm from '../LoginForm';
import API from '../../../api';
import useAuthStore from '../../../store/auth';

vi.mock('react-router-dom', () => ({ useNavigate: () => vi.fn() }));
vi.mock('../../../api');
vi.mock('../../../store/auth', () => ({ default: vi.fn() }));
vi.mock('../../../store/settings', () => ({ default: vi.fn() }));
vi.mock('../../../assets/logo.png', () => ({ default: 'logo.png' }));
import useSettingsStore from '../../../store/settings';

const config = (over = {}) => ({
  providers: [{ slug: 'entra', display_name: 'Microsoft' }],
  password_login_enabled: true,
  ...over,
});

const renderLogin = () =>
  render(
    <MantineProvider>
      <LoginForm />
    </MantineProvider>
  );

describe('LoginForm single sign-on', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    useAuthStore.mockImplementation((sel) =>
      sel({
        login: vi.fn(),
        logout: vi.fn(),
        isAuthenticated: false,
        initData: vi.fn(),
      })
    );
    useSettingsStore.mockImplementation((sel) =>
      sel({ fetchVersion: vi.fn(), version: {} })
    );
  });

  afterEach(() => {
    window.history.pushState({}, '', '/');
  });

  it('renders provider buttons from getAuthConfig next to the password form', async () => {
    API.getAuthConfig.mockResolvedValue(config());
    renderLogin();

    expect(await screen.findByTestId('sso-login-entra')).toHaveTextContent(
      'Sign in with Microsoft'
    );
    expect(screen.getByLabelText(/username/i)).toBeInTheDocument();
  });

  it('hides the password form when it is disabled', async () => {
    API.getAuthConfig.mockResolvedValue(
      config({ password_login_enabled: false })
    );
    renderLogin();

    await screen.findByTestId('sso-login-entra');
    expect(screen.queryByLabelText(/username/i)).not.toBeInTheDocument();
  });

  it('keeps the password form when the configuration cannot be loaded', async () => {
    API.getAuthConfig.mockRejectedValue(new Error('down'));
    renderLogin();

    await waitFor(() => expect(API.getAuthConfig).toHaveBeenCalled());
    expect(screen.getByLabelText(/username/i)).toBeInTheDocument();
    expect(screen.queryByTestId('sso-signin')).not.toBeInTheDocument();
  });

  it.each([
    ['client_auth_failed', /rejected this application/i],
    ['last_admin', /last active administrator/i],
  ])('renders fixed copy for sso_error=%s', async (code, copy) => {
    window.history.pushState({}, '', `/login?sso_error=${code}`);
    API.getAuthConfig.mockResolvedValue(config());
    renderLogin();

    expect(await screen.findByTestId('sso-error')).toHaveTextContent(copy);
  });

  it('renders generic copy for an unknown code and never the code itself', async () => {
    window.history.pushState({}, '', '/login?sso_error=%3Cb%3Ehax%3C%2Fb%3E');
    API.getAuthConfig.mockResolvedValue(config());
    renderLogin();

    const error = await screen.findByTestId('sso-error');
    expect(error).toHaveTextContent(/could not complete/i);
    expect(error).not.toHaveTextContent('hax');
    expect(error.querySelector('b')).toBeNull();
  });

  it('a button starts the flow with a top-level navigation to the start URL', async () => {
    API.getAuthConfig.mockResolvedValue(config());
    window.history.pushState({}, '', '/login?next=%2Fguide');
    const assigned = vi.fn();
    const real = window.location;
    vi.stubGlobal('location', {
      get search() {
        return real.search;
      },
      get pathname() {
        return real.pathname;
      },
      get hash() {
        return real.hash;
      },
      set href(v) {
        assigned(v);
      },
    });
    renderLogin();

    await userEvent.click(await screen.findByTestId('sso-login-entra'));

    expect(assigned).toHaveBeenCalledWith(
      '/api/accounts/oidc/entra/start/?next=%2Fguide'
    );
    vi.unstubAllGlobals();
  });

  it('drops an off-origin next from the URL', async () => {
    API.getAuthConfig.mockResolvedValue(config());
    window.history.pushState({}, '', '/login?next=%2F%2Fevil.example');
    const assigned = vi.fn();
    const real = window.location;
    vi.stubGlobal('location', {
      get search() {
        return real.search;
      },
      get pathname() {
        return real.pathname;
      },
      get hash() {
        return real.hash;
      },
      set href(v) {
        assigned(v);
      },
    });
    renderLogin();

    await userEvent.click(await screen.findByTestId('sso-login-entra'));

    expect(assigned).toHaveBeenCalledWith('/api/accounts/oidc/entra/start/');
    vi.unstubAllGlobals();
  });
});
