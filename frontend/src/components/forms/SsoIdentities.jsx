import React, { useCallback, useEffect, useState } from 'react';
import { Button, Group, Stack, Text } from '@mantine/core';
import API from '../../api';
import { adminErrorLines } from '../../utils/sso/ssoUtils';

// A user's linked single sign-on identities. An admin sees them with Unlink; the
// user themself gets "Link SSO account" for each enabled provider. Provider-
// and IdP-supplied strings (display names, e-mail) are rendered as text only.
const SsoIdentities = ({ userId, isAdmin, isSelf }) => {
  const [identities, setIdentities] = useState([]);
  const [providers, setProviders] = useState([]);
  const [message, setMessage] = useState('');
  // The identity or provider slug awaiting a second click.
  const [confirmUnlink, setConfirmUnlink] = useState(null);
  const [confirmLink, setConfirmLink] = useState(null);

  const load = useCallback(async () => {
    if (isAdmin) {
      try {
        const list = await API.getOidcIdentities(userId);
        setIdentities(Array.isArray(list) ? list : []);
      } catch {
        setIdentities([]);
      }
    }
    if (isSelf) {
      try {
        const config = await API.getAuthConfig();
        setProviders(Array.isArray(config?.providers) ? config.providers : []);
      } catch {
        setProviders([]);
      }
    }
  }, [userId, isAdmin, isSelf]);

  useEffect(() => {
    load();
  }, [load]);

  const unlink = async (identity) => {
    setMessage('');
    try {
      await API.deleteOidcIdentity(identity.id);
      setConfirmUnlink(null);
      await load();
    } catch (error) {
      setMessage(adminErrorLines(error).join(' '));
    }
  };

  const link = async (slug) => {
    setMessage('');
    try {
      const { authorize_url: url } = await API.startSsoLink(slug, '/users');
      if (typeof url === 'string' && /^https?:\/\//i.test(url)) {
        window.location.assign(url);
      }
    } catch (error) {
      setMessage(
        error?.body?.code === 'sso_not_configured'
          ? 'Single sign-on is not configured on this server.'
          : 'Linking could not be started. Try again shortly.'
      );
    }
  };

  return (
    <Stack gap="sm" data-testid="sso-identities">
      {isAdmin &&
        (identities.length === 0 ? (
          <Text size="sm" c="dimmed">
            No linked single sign-on accounts.
          </Text>
        ) : (
          identities.map((identity) => (
            <Group key={identity.id} justify="space-between">
              <Text size="sm">
                {`${identity.provider_slug}: ${
                  identity.display_name ||
                  identity.email_at_last_login ||
                  identity.subject
                }`}
              </Text>
              {confirmUnlink === identity.id ? (
                <Group gap="xs">
                  <Text size="xs" c="dimmed">
                    This person's next single sign-on sign-in will create a new
                    account with no history.
                  </Text>
                  <Button
                    size="xs"
                    color="red"
                    onClick={() => unlink(identity)}
                    data-testid={`sso-unlink-confirm-${identity.id}`}
                  >
                    Confirm unlink
                  </Button>
                  <Button
                    size="xs"
                    variant="subtle"
                    onClick={() => setConfirmUnlink(null)}
                  >
                    Cancel
                  </Button>
                </Group>
              ) : (
                <Button
                  size="xs"
                  variant="default"
                  color="red"
                  onClick={() => setConfirmUnlink(identity.id)}
                  data-testid={`sso-unlink-${identity.id}`}
                >
                  Unlink
                </Button>
              )}
            </Group>
          ))
        ))}
      {isSelf &&
        providers.map((provider) => (
          <Stack key={provider.slug} gap="xs">
            <Button
              size="xs"
              variant="default"
              onClick={() => setConfirmLink(provider.slug)}
              data-testid={`sso-link-${provider.slug}`}
            >
              {`Link SSO account (${provider.display_name})`}
            </Button>
            {confirmLink === provider.slug && (
              <Stack gap="xs" data-testid="sso-link-warning">
                <Text size="sm">
                  After linking, this provider's role mapping sets your level on
                  every sign-in through it. If it maps you to a lower level than
                  you have now (for example, an administrator mapped to
                  Standard), you will be demoted.
                </Text>
                <Group gap="xs">
                  <Button
                    size="xs"
                    onClick={() => link(provider.slug)}
                    data-testid="sso-link-confirm"
                  >
                    Continue to the provider
                  </Button>
                  <Button
                    size="xs"
                    variant="subtle"
                    onClick={() => setConfirmLink(null)}
                  >
                    Cancel
                  </Button>
                </Group>
              </Stack>
            )}
          </Stack>
        ))}
      {message && (
        <Text size="sm" c="red" role="alert">
          {message}
        </Text>
      )}
    </Stack>
  );
};

export default SsoIdentities;
