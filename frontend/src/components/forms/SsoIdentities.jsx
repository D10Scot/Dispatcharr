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
      await load();
    } catch (error) {
      setMessage(adminErrorLines(error).join(' '));
    }
  };

  const link = async (slug) => {
    setMessage('');
    try {
      const { authorize_url: url } = await API.startSsoLink(slug, '/users');
      if (typeof url === 'string' && url) window.location.assign(url);
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
              <Button
                size="xs"
                variant="default"
                color="red"
                onClick={() => unlink(identity)}
                data-testid={`sso-unlink-${identity.id}`}
              >
                Unlink
              </Button>
            </Group>
          ))
        ))}
      {isSelf &&
        providers.map((provider) => (
          <Button
            key={provider.slug}
            size="xs"
            variant="default"
            onClick={() => link(provider.slug)}
            data-testid={`sso-link-${provider.slug}`}
          >
            {`Link SSO account (${provider.display_name})`}
          </Button>
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
