import React, { useState } from 'react';
import {
  ActionIcon,
  Alert,
  Anchor,
  Button,
  Group,
  Select,
  Stack,
  Switch,
  Text,
  TextInput,
} from '@mantine/core';
import { Copy, Plus, Trash2 } from 'lucide-react';
import API from '../../../../api';
import { copyToClipboard } from '../../../../utils';
import OidcCredentialBlock from './OidcCredentialBlock';
import {
  ENTRA_MAX_REDIRECT_URI,
  ENTRA_SETUP_DOC_URL,
  MAPPING_LEVELS,
  adminErrorLines,
  buildProviderPayload,
  computeRedirectUri,
  emptyProviderValues,
  providerToValues,
  testProblemMessage,
} from '../../../../utils/sso/ssoUtils';

const OidcProviderForm = ({
  provider: initialProvider = null,
  kind: newKind = 'generic',
  publicBaseUrl,
  onSaved,
  onCancel,
}) => {
  const [provider, setProvider] = useState(initialProvider);
  const [values, setValues] = useState(
    initialProvider
      ? providerToValues(initialProvider)
      : emptyProviderValues(newKind)
  );
  const [credential, setCredential] = useState(
    initialProvider?.client_auth_method === 'private_key_jwt'
      ? 'certificate'
      : initialProvider
        ? 'secret'
        : 'certificate'
  );
  const [secret, setSecret] = useState('');
  const [authMethod, setAuthMethod] = useState(
    initialProvider && initialProvider.client_auth_method !== 'private_key_jwt'
      ? initialProvider.client_auth_method
      : newKind === 'entra'
        ? 'client_secret_post'
        : 'client_secret_basic'
  );
  const [secretExpiry, setSecretExpiry] = useState(
    initialProvider?.client_secret_expires_at ?? ''
  );
  const [saving, setSaving] = useState(false);
  const [lines, setLines] = useState([]);
  const [testResult, setTestResult] = useState(null);

  const isEntra = values.kind === 'entra';
  const set = (name) => (value) => setValues((v) => ({ ...v, [name]: value }));
  const setText = (name) => (e) => set(name)(e.currentTarget.value);

  const redirectUri = computeRedirectUri(publicBaseUrl, values.slug);
  const tooLong = isEntra && redirectUri.length > ENTRA_MAX_REDIRECT_URI;

  const reload = async () => {
    const all = await API.getOidcProviders();
    const fresh = Array.isArray(all)
      ? all.find((p) => p.id === provider?.id)
      : null;
    if (fresh) setProvider(fresh);
  };

  const save = async (e) => {
    e?.preventDefault?.();
    setSaving(true);
    setLines([]);
    try {
      const payload = buildProviderPayload({
        values,
        provider,
        credential,
        secret,
        authMethod,
        secretExpiry,
      });
      const saved = provider
        ? await API.updateOidcProvider(provider.id, payload)
        : await API.createOidcProvider(payload);
      setSecret('');
      setProvider(saved);
      onSaved?.(saved);
    } catch (error) {
      setLines(adminErrorLines(error));
    } finally {
      setSaving(false);
    }
  };

  const runTest = async () => {
    setTestResult(null);
    try {
      setTestResult(await API.testOidcProvider(provider.id));
    } catch (error) {
      setTestResult({ ok: false, problems: [], error: adminErrorLines(error) });
    }
  };

  const setMapping = (index, patch) =>
    set('mappings')(
      values.mappings.map((m, i) => (i === index ? { ...m, ...patch } : m))
    );

  return (
    <form onSubmit={save} data-testid="sso-provider-form">
      <Stack gap="sm">
        <Text fw={600}>
          {provider
            ? `Edit ${provider.display_name}`
            : isEntra
              ? 'Add Microsoft Entra ID provider'
              : 'Add generic OIDC provider'}
        </Text>

        {isEntra && (
          <Text size="sm" c="dimmed">
            Entra ID (single tenant). Sovereign-cloud and External ID tenants
            use the generic provider instead.{' '}
            <Anchor
              href={ENTRA_SETUP_DOC_URL}
              target="_blank"
              rel="noreferrer noopener"
              data-testid="sso-entra-doc-link"
            >
              Entra setup guide
            </Anchor>
          </Text>
        )}

        <TextInput
          label="Display name"
          description="Shown on the sign-in button."
          value={values.display_name}
          onChange={setText('display_name')}
          required
          data-testid="sso-display-name"
        />
        <TextInput
          label="Slug"
          description="Part of the redirect URI. Lowercase letters, digits and hyphens."
          value={values.slug}
          onChange={setText('slug')}
          required
          data-testid="sso-slug"
        />

        <div data-testid="sso-redirect-block">
          <TextInput
            label="Redirect URI"
            description="Register exactly this address with your identity provider."
            value={redirectUri}
            readOnly
            placeholder="Set the public base URL first"
            data-testid="sso-redirect-uri"
            rightSection={
              <ActionIcon
                variant="subtle"
                aria-label="Copy redirect URI"
                disabled={!redirectUri}
                onClick={() =>
                  copyToClipboard(redirectUri, {
                    successTitle: 'Redirect URI copied',
                  })
                }
              >
                <Copy size={16} />
              </ActionIcon>
            }
          />
          {tooLong && (
            <Text size="xs" c="red">
              {`Entra allows redirect URIs of at most ${ENTRA_MAX_REDIRECT_URI} characters; this one is ${redirectUri.length}.`}
            </Text>
          )}
        </div>

        {isEntra ? (
          <TextInput
            label="Directory (tenant) ID"
            description="A GUID. Not a domain name, and not common or organizations."
            value={values.entra_tenant_id}
            onChange={setText('entra_tenant_id')}
            required
            data-testid="sso-tenant-id"
          />
        ) : (
          <TextInput
            label="Issuer"
            description="The https address whose /.well-known/openid-configuration describes the provider."
            value={values.issuer}
            onChange={setText('issuer')}
            required
            data-testid="sso-issuer"
          />
        )}
        <TextInput
          label="Application (client) ID"
          value={values.client_id}
          onChange={setText('client_id')}
          required
          data-testid="sso-client-id"
        />

        <OidcCredentialBlock
          provider={provider}
          kind={values.kind}
          credential={credential}
          onCredentialChange={setCredential}
          secret={secret}
          onSecretChange={setSecret}
          authMethod={authMethod}
          onAuthMethodChange={setAuthMethod}
          secretExpiry={secretExpiry}
          onSecretExpiryChange={setSecretExpiry}
          onReload={reload}
        />

        {!isEntra && (
          <Switch
            label="Identity provider is on a private network"
            description="Allow discovery and token requests to private addresses."
            checked={values.allow_private_network}
            onChange={(e) =>
              set('allow_private_network')(e.currentTarget.checked)
            }
            data-testid="sso-private-network"
          />
        )}

        <TextInput
          label="Scopes"
          value={values.scopes}
          onChange={setText('scopes')}
        />
        <TextInput
          label="Claim to map"
          description={
            isEntra
              ? 'roles (app roles) is recommended; groups can overflow.'
              : 'Dotted path of the ID-token claim holding roles or groups.'
          }
          value={values.claim_path}
          onChange={setText('claim_path')}
          data-testid="sso-claim-path"
        />

        <Stack gap="xs" data-testid="sso-mappings">
          <Text size="sm" fw={500}>
            Claim value to level
          </Text>
          {values.mappings.map((m, i) => (
            <Group key={i} gap="xs" wrap="nowrap">
              <TextInput
                placeholder="Claim value"
                aria-label={`Claim value ${i + 1}`}
                value={m.value}
                onChange={(e) =>
                  setMapping(i, { value: e.currentTarget.value })
                }
                style={{ flex: 1 }}
              />
              <Select
                aria-label={`Level ${i + 1}`}
                data={MAPPING_LEVELS}
                value={m.user_level}
                onChange={(v) => setMapping(i, { user_level: v ?? '1' })}
                allowDeselect={false}
                w={140}
              />
              <ActionIcon
                variant="subtle"
                color="red"
                aria-label={`Remove mapping ${i + 1}`}
                onClick={() =>
                  set('mappings')(values.mappings.filter((_, j) => j !== i))
                }
              >
                <Trash2 size={16} />
              </ActionIcon>
            </Group>
          ))}
          <Button
            size="xs"
            variant="default"
            leftSection={<Plus size={14} />}
            style={{ alignSelf: 'flex-start' }}
            onClick={() =>
              set('mappings')([
                ...values.mappings,
                { value: '', user_level: '1' },
              ])
            }
            data-testid="sso-add-mapping"
          >
            Add mapping
          </Button>
        </Stack>

        <Switch
          label="Ask which account to use each time"
          checked={values.prompt_select_account}
          onChange={(e) =>
            set('prompt_select_account')(e.currentTarget.checked)
          }
        />
        <Switch
          label="Enabled"
          description="Shows the sign-in button."
          checked={values.enabled}
          onChange={(e) => set('enabled')(e.currentTarget.checked)}
          data-testid="sso-enabled"
        />

        {lines.length > 0 && (
          <Alert color="red" variant="light" data-testid="sso-provider-error">
            {lines.map((l) => (
              <div key={l}>{l}</div>
            ))}
          </Alert>
        )}

        {testResult && (
          <Alert
            color={testResult.ok ? 'green' : 'red'}
            variant="light"
            data-testid="sso-test-result"
          >
            {testResult.ok
              ? 'Discovery and signing keys are fine.'
              : [
                  ...(testResult.error ?? []),
                  ...(testResult.problems ?? []).map(testProblemMessage),
                ].map((l) => <div key={l}>{l}</div>)}
          </Alert>
        )}

        <Group justify="space-between">
          <Button
            variant="default"
            onClick={runTest}
            disabled={!provider}
            data-testid="sso-test-provider"
          >
            Test
          </Button>
          <Group>
            <Button variant="subtle" color="gray" onClick={onCancel}>
              Back
            </Button>
            <Button
              type="submit"
              loading={saving}
              data-testid="sso-provider-save"
            >
              Save
            </Button>
          </Group>
        </Group>
      </Stack>
    </form>
  );
};

export default OidcProviderForm;
