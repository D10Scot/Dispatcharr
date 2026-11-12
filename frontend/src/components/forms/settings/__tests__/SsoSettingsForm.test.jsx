import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MantineProvider } from '@mantine/core';
import SsoSettingsForm from '../SsoSettingsForm';
import API from '../../../../api';

vi.mock('../../../../api');
vi.mock('../../../../utils', () => ({ copyToClipboard: vi.fn() }));

const wrap = (ui) => render(<MantineProvider>{ui}</MantineProvider>);

const provider = (over = {}) => ({
  id: 7,
  slug: 'entra',
  display_name: 'Microsoft',
  kind: 'entra',
  enabled: true,
  issuer: 'https://login.microsoftonline.com/t/v2.0',
  entra_tenant_id: '11111111-2222-3333-4444-555555555555',
  client_id: 'cid',
  allow_private_network: false,
  client_auth_method: 'client_secret_post',
  client_secret_set: true,
  client_secret_expires_at: null,
  client_certificate: { active: null, pending: null },
  credential_expiry: { expires_at: null, state: 'unknown', days_left: null },
  credential_unreadable: false,
  scopes: 'openid profile email',
  id_token_alg: 'RS256',
  claim_path: 'roles',
  mappings: [{ value: 'Mino.Admin', user_level: 10 }],
  prompt_select_account: false,
  redirect_uri: null,
  version: 1,
  ...over,
});

const open = async (p) => {
  API.getOidcProviders.mockResolvedValue([p]);
  wrap(<SsoSettingsForm />);
  await userEvent.click(await screen.findByText('Edit'));
  await screen.findByTestId('sso-provider-form');
};

beforeEach(() => {
  vi.clearAllMocks();
  // jsdom lacks it; Mantine's Select calls it when opening.
  Element.prototype.scrollIntoView = vi.fn();
  API.getAuthSettings.mockResolvedValue({
    public_base_url: 'https://mino.example.com',
    password_login_enabled: true,
    credential_warnings: [],
  });
  API.getOidcProviders.mockResolvedValue([]);
});

describe('SsoSettingsForm', () => {
  it('untouched secret is not sent', async () => {
    API.updateOidcProvider.mockResolvedValue(provider());
    await open(provider());

    await userEvent.click(screen.getByTestId('sso-provider-save'));

    await waitFor(() => expect(API.updateOidcProvider).toHaveBeenCalled());
    const [id, payload] = API.updateOidcProvider.mock.calls[0];
    expect(id).toBe(7);
    expect(
      Object.hasOwn(payload, 'client_secret'),
      'an untouched secret field must not send client_secret'
    ).toBe(false);
  });

  it('sends the secret only when one was typed, and never echoes the stored one', async () => {
    API.updateOidcProvider.mockResolvedValue(provider());
    await open(provider());

    const field = screen.getByTestId('sso-client-secret');
    expect(field).toHaveValue('');
    await userEvent.type(field, 'typed-value');
    await userEvent.click(screen.getByTestId('sso-provider-save'));

    await waitFor(() => expect(API.updateOidcProvider).toHaveBeenCalled());
    expect(API.updateOidcProvider.mock.calls[0][1].client_secret).toBe(
      'typed-value'
    );
  });

  it.each([
    ['not_sso_session', /not signed in through single sign-on/i],
    ['provider_not_enabled', /not enabled now/i],
    ['not_admin_at_sign_in', /did not sign you in as an administrator/i],
    ['last_enabled_provider', /last enabled provider/i],
  ])(
    'renders the lockout_guard reason %s as its own fixed copy',
    async (reason, copy) => {
      API.updateOidcProvider.mockRejectedValue(
        Object.assign(new Error('409'), {
          status: 409,
          body: {
            code: 'lockout_guard',
            reasons: [reason],
            detail: '<b>server text</b>',
          },
        })
      );
      await open(provider());

      await userEvent.click(screen.getByTestId('sso-provider-save'));

      const box = await screen.findByTestId('sso-provider-error');
      expect(within(box).getByText(copy)).toBeInTheDocument();
      expect(box).not.toHaveTextContent('server text');
    }
  );

  it('Activate is disabled with no pending certificate', async () => {
    await open(provider({ client_auth_method: 'private_key_jwt' }));
    expect(screen.getByTestId('sso-cert-activate')).toBeDisabled();
  });

  it('Activate sends the thumbprint of the pending certificate being shown', async () => {
    const pending = {
      thumbprint_sha256: 'ab'.repeat(32),
      not_after: '2027-01-01T00:00:00+00:00',
    };
    await open(
      provider({
        client_auth_method: 'private_key_jwt',
        client_certificate: { active: null, pending },
      })
    );
    API.activateOidcCertificate.mockResolvedValue(provider());

    await userEvent.click(screen.getByTestId('sso-cert-activate'));

    await waitFor(() =>
      expect(API.activateOidcCertificate).toHaveBeenCalledWith(
        7,
        pending.thumbprint_sha256
      )
    );
  });

  it('reloads the block with fixed copy on pending_certificate_changed', async () => {
    const pending = {
      thumbprint_sha256: 'cd'.repeat(32),
      not_after: '2027-01-01T00:00:00+00:00',
    };
    await open(
      provider({
        client_auth_method: 'private_key_jwt',
        client_certificate: { active: null, pending },
      })
    );
    API.activateOidcCertificate.mockRejectedValue(
      Object.assign(new Error('409'), {
        status: 409,
        body: { code: 'pending_certificate_changed' },
      })
    );
    const newer = {
      thumbprint_sha256: 'ef'.repeat(32),
      not_after: '2027-02-01T00:00:00+00:00',
    };
    API.getOidcProviders.mockResolvedValue([
      provider({
        client_auth_method: 'private_key_jwt',
        client_certificate: { active: null, pending: newer },
      }),
    ]);

    await userEvent.click(screen.getByTestId('sso-cert-activate'));

    expect(
      await screen.findByText(
        /another administrator generated a newer certificate/i
      )
    ).toBeInTheDocument();
    expect(
      await screen.findByText(new RegExp(newer.thumbprint_sha256))
    ).toBeInTheDocument();
  });

  it('the Entra variant offers no Basic method and no private-network switch', async () => {
    await open(provider());
    await userEvent.click(screen.getByTestId('sso-credential-secret'));

    expect(screen.queryByTestId('sso-private-network')).not.toBeInTheDocument();
    await userEvent.click(screen.getByTestId('sso-auth-method'));
    expect(screen.queryByText(/HTTP Basic/)).not.toBeInTheDocument();
  });

  it('the generic variant offers both', async () => {
    await open(
      provider({
        kind: 'generic',
        client_auth_method: 'client_secret_basic',
        entra_tenant_id: '',
        slug: 'okta',
        issuer: 'https://idp.example.com',
      })
    );
    expect(screen.getByTestId('sso-private-network')).toBeInTheDocument();
    await userEvent.click(screen.getByTestId('sso-auth-method'));
    expect(await screen.findByText(/HTTP Basic/)).toBeInTheDocument();
  });

  it('renders a banner for a provider whose credential is expiring', async () => {
    API.getOidcProviders.mockResolvedValue([
      provider({
        credential_expiry: {
          expires_at: '2026-12-01',
          state: 'expiring',
          days_left: 9,
        },
      }),
    ]);
    wrap(<SsoSettingsForm />);
    const banner = await screen.findByTestId('sso-credential-banner-entra');
    expect(banner).toHaveTextContent('expires in 9 days');
  });

  it('shows no banner for a healthy credential', async () => {
    API.getOidcProviders.mockResolvedValue([
      provider({
        credential_expiry: {
          expires_at: '2030-01-01',
          state: 'ok',
          days_left: 900,
        },
      }),
    ]);
    wrap(<SsoSettingsForm />);
    await screen.findByTestId('sso-provider-table');
    expect(
      screen.queryByTestId('sso-credential-banner-entra')
    ).not.toBeInTheDocument();
  });

  it('the Entra form computes and shows the redirect URI from public_base_url and the slug', async () => {
    wrap(<SsoSettingsForm />);
    await userEvent.click(await screen.findByTestId('sso-add-entra'));

    const uri = await screen.findByTestId('sso-redirect-uri');
    expect(uri).toHaveValue(
      'https://mino.example.com/api/accounts/oidc/entra/callback/'
    );
    const slug = screen.getByTestId('sso-slug');
    await userEvent.clear(slug);
    await userEvent.type(slug, 'work');
    expect(uri).toHaveValue(
      'https://mino.example.com/api/accounts/oidc/work/callback/'
    );
  });

  it('shows the password toggle state but offers no working off', async () => {
    wrap(<SsoSettingsForm />);
    const toggle = await screen.findByTestId('sso-password-toggle');
    expect(toggle).toBeDisabled();
    expect(toggle).toBeChecked();
    expect(API.updateAuthSettings).not.toHaveBeenCalled();
  });

  it('shows fixed copy for a refused public base URL, never the server text', async () => {
    API.updateAuthSettings.mockRejectedValue(
      Object.assign(new Error('400'), {
        status: 400,
        body: { code: 'public_base_url_insecure', detail: 'x' },
      })
    );
    wrap(<SsoSettingsForm />);
    await userEvent.click(await screen.findByTestId('sso-save-base-url'));
    expect(await screen.findByTestId('sso-base-url-error')).toHaveTextContent(
      /must be https/i
    );
  });

  it('typing a new secret does not re-send the old expiry date', async () => {
    API.updateOidcProvider.mockResolvedValue(provider());
    await open(provider({ client_secret_expires_at: '2026-12-01' }));
    expect(screen.getByTestId('sso-secret-expiry')).toHaveValue('2026-12-01');

    await userEvent.type(
      screen.getByTestId('sso-client-secret'),
      'fresh-secret'
    );
    await userEvent.click(screen.getByTestId('sso-provider-save'));

    await waitFor(() => expect(API.updateOidcProvider).toHaveBeenCalled());
    const payload = API.updateOidcProvider.mock.calls[0][1];
    expect(payload.client_secret).toBe('fresh-secret');
    expect(
      payload.client_secret_expires_at,
      'a new secret must not carry the old expiry date'
    ).toBeNull();
  });

  it('sends the expiry the administrator sets for a new secret', async () => {
    API.updateOidcProvider.mockResolvedValue(provider());
    await open(provider({ client_secret_expires_at: '2026-12-01' }));

    await userEvent.type(
      screen.getByTestId('sso-client-secret'),
      'fresh-secret'
    );
    await userEvent.clear(screen.getByTestId('sso-secret-expiry'));
    await userEvent.type(screen.getByTestId('sso-secret-expiry'), '2027-06-30');
    await userEvent.click(screen.getByTestId('sso-provider-save'));

    await waitFor(() => expect(API.updateOidcProvider).toHaveBeenCalled());
    expect(
      API.updateOidcProvider.mock.calls[0][1].client_secret_expires_at
    ).toBe('2027-06-30');
  });

  it('clears the secret field after a save, so a second save sends none', async () => {
    API.updateOidcProvider.mockResolvedValue(provider());
    await open(provider());

    await userEvent.type(
      screen.getByTestId('sso-client-secret'),
      'typed-value'
    );
    await userEvent.click(screen.getByTestId('sso-provider-save'));
    await waitFor(() =>
      expect(API.updateOidcProvider).toHaveBeenCalledTimes(1)
    );

    await waitFor(() =>
      expect(
        screen.getByTestId('sso-client-secret'),
        'the secret field must be emptied after a save'
      ).toHaveValue('')
    );
    await userEvent.click(screen.getByTestId('sso-provider-save'));
    await waitFor(() =>
      expect(API.updateOidcProvider).toHaveBeenCalledTimes(2)
    );
    expect(
      Object.hasOwn(API.updateOidcProvider.mock.calls[1][1], 'client_secret')
    ).toBe(false);
  });

  it('the secret field is a password input', async () => {
    await open(provider());
    expect(screen.getByTestId('sso-client-secret')).toHaveAttribute(
      'type',
      'password'
    );
  });

  it('deleting a provider needs a second click', async () => {
    API.getOidcProviders.mockResolvedValue([provider()]);
    API.deleteOidcProvider.mockResolvedValue('');
    wrap(<SsoSettingsForm />);

    await userEvent.click(await screen.findByTestId('sso-delete-entra'));
    expect(API.deleteOidcProvider).not.toHaveBeenCalled();
    await userEvent.click(screen.getByTestId('sso-delete-confirm-entra'));
    expect(API.deleteOidcProvider).toHaveBeenCalledWith(7);
  });
});
