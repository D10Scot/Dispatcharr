import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MantineProvider } from '@mantine/core';
import SsoIdentities from '../SsoIdentities';
import API from '../../../api';

vi.mock('../../../api');

const wrap = (props) =>
  render(
    <MantineProvider>
      <SsoIdentities {...props} />
    </MantineProvider>
  );

describe('SsoIdentities', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    API.getOidcIdentities.mockResolvedValue([
      {
        id: 5,
        provider_slug: 'entra',
        display_name: '<i>Dana</i>',
        email_at_last_login: '',
        subject: 's',
      },
    ]);
    API.getAuthConfig.mockResolvedValue({
      providers: [{ slug: 'entra', display_name: 'Microsoft' }],
      password_login_enabled: true,
    });
  });

  it('lists identities as text and unlinks one', async () => {
    API.deleteOidcIdentity.mockResolvedValue('');
    wrap({ userId: 3, isAdmin: true, isSelf: false });

    expect(await screen.findByText('entra: <i>Dana</i>')).toBeInTheDocument();
    await userEvent.click(screen.getByTestId('sso-unlink-5'));
    expect(API.deleteOidcIdentity).not.toHaveBeenCalled();
    await userEvent.click(screen.getByTestId('sso-unlink-confirm-5'));
    expect(API.deleteOidcIdentity).toHaveBeenCalledWith(5);
    expect(API.getAuthConfig).not.toHaveBeenCalled();
  });

  it('offers linking only on the own profile and starts it with a POST', async () => {
    API.startSsoLink.mockResolvedValue({
      authorize_url: 'https://idp.example/authorize?x=1',
    });
    const assign = vi.fn();
    const real = window.location;
    vi.stubGlobal('location', {
      assign,
      get href() {
        return real.href;
      },
    });
    wrap({ userId: 3, isAdmin: false, isSelf: true });

    await userEvent.click(await screen.findByTestId('sso-link-entra'));
    // The demotion warning is shown first and nothing has started yet.
    expect(screen.getByTestId('sso-link-warning')).toHaveTextContent(
      /demoted/i
    );
    expect(API.startSsoLink).not.toHaveBeenCalled();
    expect(assign).not.toHaveBeenCalled();
    await userEvent.click(screen.getByTestId('sso-link-confirm'));

    await waitFor(() =>
      expect(assign).toHaveBeenCalledWith('https://idp.example/authorize?x=1')
    );
    expect(API.startSsoLink).toHaveBeenCalledWith('entra', '/users');
    expect(API.getOidcIdentities).not.toHaveBeenCalled();
    vi.unstubAllGlobals();
  });

  it('does not navigate to a non-http(s) authorize_url', async () => {
    API.startSsoLink.mockResolvedValue({
      authorize_url: 'javascript:alert(1)',
    });
    const assign = vi.fn();
    const real = window.location;
    vi.stubGlobal('location', {
      assign,
      get href() {
        return real.href;
      },
    });
    wrap({ userId: 3, isAdmin: false, isSelf: true });

    await userEvent.click(await screen.findByTestId('sso-link-entra'));
    await userEvent.click(screen.getByTestId('sso-link-confirm'));

    await waitFor(() => expect(API.startSsoLink).toHaveBeenCalled());
    expect(assign).not.toHaveBeenCalled();
    vi.unstubAllGlobals();
  });

  it('says so when the authorize_url is refused', async () => {
    API.startSsoLink.mockResolvedValue({
      authorize_url: 'javascript:alert(1)',
    });
    const assign = vi.fn();
    const real = window.location;
    vi.stubGlobal('location', {
      assign,
      get href() {
        return real.href;
      },
    });
    wrap({ userId: 3, isAdmin: false, isSelf: true });

    await userEvent.click(await screen.findByTestId('sso-link-entra'));
    await userEvent.click(screen.getByTestId('sso-link-confirm'));

    expect(
      await screen.findByText(/linking could not be started/i),
      'a refused authorize_url must not fail silently'
    ).toBeInTheDocument();
    expect(assign).not.toHaveBeenCalled();
    vi.unstubAllGlobals();
  });
});
