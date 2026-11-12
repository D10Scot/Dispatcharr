import React, { useCallback, useEffect, useState } from 'react';
import {
  Alert,
  Badge,
  Button,
  Group,
  Loader,
  Stack,
  Switch,
  Table,
  Text,
  TextInput,
} from '@mantine/core';
import API from '../../../api';
import OidcProviderForm from './sso/OidcProviderForm';
import {
  adminErrorLines,
  credentialWarningMessage,
} from '../../../utils/sso/ssoUtils';

const ErrorLines = ({ lines, testId }) =>
  lines.length > 0 ? (
    <Alert color="red" variant="light" data-testid={testId}>
      {lines.map((l) => (
        <div key={l}>{l}</div>
      ))}
    </Alert>
  ) : null;

const SsoSettingsForm = () => {
  const [settings, setSettings] = useState(null);
  const [providers, setProviders] = useState([]);
  const [loading, setLoading] = useState(true);
  const [loadFailed, setLoadFailed] = useState(false);
  const [baseUrl, setBaseUrl] = useState('');
  const [baseLines, setBaseLines] = useState([]);
  const [baseSaved, setBaseSaved] = useState(false);
  const [listLines, setListLines] = useState([]);
  // null: list view. { provider, kind }: the editor.
  const [editing, setEditing] = useState(null);

  const load = useCallback(async () => {
    try {
      const [s, p] = await Promise.all([
        API.getAuthSettings(),
        API.getOidcProviders(),
      ]);
      setSettings(s);
      setBaseUrl(s?.public_base_url ?? '');
      setProviders(Array.isArray(p) ? p : []);
      setLoadFailed(false);
    } catch {
      setLoadFailed(true);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const saveBaseUrl = async () => {
    setBaseLines([]);
    setBaseSaved(false);
    try {
      const updated = await API.updateAuthSettings({
        public_base_url: baseUrl,
      });
      setSettings(updated);
      setBaseUrl(updated?.public_base_url ?? baseUrl);
      setBaseSaved(true);
    } catch (error) {
      setBaseLines(adminErrorLines(error));
    }
  };

  const removeProvider = async (provider) => {
    setListLines([]);
    try {
      await API.deleteOidcProvider(provider.id);
      await load();
    } catch (error) {
      setListLines(adminErrorLines(error));
    }
  };

  const toggleEnabled = async (provider) => {
    setListLines([]);
    try {
      await API.updateOidcProvider(provider.id, { enabled: !provider.enabled });
      await load();
    } catch (error) {
      setListLines(adminErrorLines(error));
    }
  };

  if (loading) return <Loader />;
  if (loadFailed) {
    return (
      <Alert color="red" variant="light">
        Single sign-on settings could not be loaded.
      </Alert>
    );
  }

  if (editing) {
    return (
      <OidcProviderForm
        provider={editing.provider}
        kind={editing.kind}
        publicBaseUrl={settings?.public_base_url ?? ''}
        onSaved={load}
        onCancel={() => {
          setEditing(null);
          load();
        }}
      />
    );
  }

  const warnings = providers
    .filter(
      (p) =>
        p.enabled &&
        ['expiring', 'expired'].includes(p.credential_expiry?.state)
    )
    .map((p) => ({
      slug: p.slug,
      state: p.credential_expiry.state,
      days_left: p.credential_expiry.days_left,
    }));

  const passwordEnabled = settings?.password_login_enabled !== false;

  return (
    <Stack gap="md" data-testid="sso-settings">
      {warnings.map((w) => (
        <Alert
          key={w.slug}
          color={w.state === 'expired' ? 'red' : 'yellow'}
          variant="light"
          data-testid={`sso-credential-banner-${w.slug}`}
        >
          {credentialWarningMessage(w)}
        </Alert>
      ))}

      <Stack gap="xs">
        <TextInput
          label="Public base URL"
          description="The address people reach this server at, for example https://mino.example.com. It must be https (http only for localhost)."
          value={baseUrl}
          onChange={(e) => {
            setBaseUrl(e.currentTarget.value);
            setBaseSaved(false);
          }}
          data-testid="sso-public-base-url"
        />
        <Group>
          <Button
            size="xs"
            onClick={saveBaseUrl}
            data-testid="sso-save-base-url"
          >
            Save URL
          </Button>
          {baseSaved && (
            <Badge color="green" variant="light">
              Saved
            </Badge>
          )}
        </Group>
        <ErrorLines lines={baseLines} testId="sso-base-url-error" />
      </Stack>

      <Stack gap="xs">
        <Group justify="space-between">
          <Text fw={600}>Providers</Text>
          <Group gap="xs">
            <Button
              size="xs"
              variant="default"
              onClick={() => setEditing({ provider: null, kind: 'entra' })}
              data-testid="sso-add-entra"
            >
              Add Microsoft Entra ID
            </Button>
            <Button
              size="xs"
              variant="default"
              onClick={() => setEditing({ provider: null, kind: 'generic' })}
              data-testid="sso-add-generic"
            >
              Add generic OIDC
            </Button>
          </Group>
        </Group>
        {providers.length === 0 ? (
          <Text size="sm" c="dimmed">
            No providers yet.
          </Text>
        ) : (
          <Table data-testid="sso-provider-table">
            <Table.Tbody>
              {providers.map((p) => (
                <Table.Tr key={p.id} data-testid={`sso-provider-row-${p.slug}`}>
                  <Table.Td>
                    <Text size="sm">{p.display_name}</Text>
                    <Text size="xs" c="dimmed">{`${p.kind} / ${p.slug}`}</Text>
                  </Table.Td>
                  <Table.Td>
                    <Switch
                      checked={p.enabled}
                      onChange={() => toggleEnabled(p)}
                      aria-label={`Enable ${p.display_name}`}
                    />
                  </Table.Td>
                  <Table.Td>
                    <Group gap="xs" justify="flex-end">
                      <Button
                        size="xs"
                        variant="default"
                        onClick={() =>
                          setEditing({ provider: p, kind: p.kind })
                        }
                      >
                        Edit
                      </Button>
                      <Button
                        size="xs"
                        variant="default"
                        color="red"
                        onClick={() => removeProvider(p)}
                      >
                        Delete
                      </Button>
                    </Group>
                  </Table.Td>
                </Table.Tr>
              ))}
            </Table.Tbody>
          </Table>
        )}
        <ErrorLines lines={listLines} testId="sso-list-error" />
      </Stack>

      <Stack gap="xs">
        {/* Display only. The working "off" arrives with the lockout guard and
            break-glass (spec S4); until then the server refuses it, so the UI
            does not offer it. */}
        <Switch
          label="Password sign-in"
          checked={passwordEnabled}
          disabled
          readOnly
          data-testid="sso-password-toggle"
        />
        <Text size="xs" c="dimmed">
          Password sign-in cannot be turned off in this version. While it is off
          in a later version, a wrong provider edit can lock everyone out.
        </Text>
      </Stack>
    </Stack>
  );
};

export default SsoSettingsForm;
