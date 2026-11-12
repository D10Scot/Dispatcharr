import React, { useState } from 'react';
import {
  Alert,
  Badge,
  Button,
  Group,
  PasswordInput,
  Radio,
  Select,
  Stack,
  Text,
  TextInput,
} from '@mantine/core';
import API from '../../../../api';
import { adminErrorLines } from '../../../../utils/sso/ssoUtils';

const fmtDate = (iso) => (iso ? String(iso).slice(0, 10) : 'unknown');

const CertificateRow = ({ title, cert, testId, children }) => (
  <Group justify="space-between" align="flex-start" data-testid={testId}>
    <Stack gap={0}>
      <Text size="sm" fw={600}>
        {title}
      </Text>
      {cert ? (
        <>
          <Text size="xs" c="dimmed" style={{ wordBreak: 'break-all' }}>
            {`SHA-256 thumbprint: ${cert.thumbprint_sha256}`}
          </Text>
          <Text
            size="xs"
            c="dimmed"
          >{`Expires ${fmtDate(cert.not_after)}`}</Text>
        </>
      ) : (
        <Text size="xs" c="dimmed">
          None
        </Text>
      )}
    </Stack>
    {children}
  </Group>
);

// The credential a provider uses to authenticate to its IdP (spec 5.2, 5.7).
// The secret is write-only: the input never receives the stored value, and an
// untouched input is reported to the parent as ''. Only a certificate is ever
// downloadable; there is no way to read a key.
const OidcCredentialBlock = ({
  provider, // null while the provider has not been saved yet
  kind,
  credential,
  onCredentialChange,
  secret,
  onSecretChange,
  authMethod,
  onAuthMethodChange,
  secretExpiry,
  onSecretExpiryChange,
  onReload,
}) => {
  const [busy, setBusy] = useState(false);
  const [lines, setLines] = useState([]);
  const [notice, setNotice] = useState(null);

  const pending = provider?.client_certificate?.pending ?? null;
  const active = provider?.client_certificate?.active ?? null;
  const isEntra = kind === 'entra';

  const run = async (fn) => {
    setBusy(true);
    setLines([]);
    setNotice(null);
    try {
      await fn();
    } catch (error) {
      setLines(adminErrorLines(error));
      if (error?.body?.code === 'pending_certificate_changed') {
        await onReload?.();
      }
    } finally {
      setBusy(false);
    }
  };

  const generate = () =>
    run(async () => {
      await API.generateOidcCertificate(provider.id);
      await onReload?.();
    });

  const download = (slot) =>
    run(async () => {
      const pem = await API.downloadOidcCertificate(provider.id, slot);
      const url = URL.createObjectURL(
        new Blob([pem], { type: 'application/x-pem-file' })
      );
      const a = document.createElement('a');
      a.href = url;
      a.download = `mino-oidc-${provider.slug}-${slot}.pem`;
      a.click();
      URL.revokeObjectURL(url);
    });

  const activate = () =>
    run(async () => {
      // The thumbprint of the pending certificate THIS form is showing.
      await API.activateOidcCertificate(provider.id, pending.thumbprint_sha256);
      setNotice('The certificate is active.');
      await onReload?.();
    });

  const methodOptions = isEntra
    ? [{ value: 'client_secret_post', label: 'Client secret (POST body)' }]
    : [
        { value: 'client_secret_basic', label: 'Client secret (HTTP Basic)' },
        { value: 'client_secret_post', label: 'Client secret (POST body)' },
      ];

  return (
    <Stack gap="sm" data-testid="sso-credential-block">
      <Radio.Group
        label="Credential"
        value={credential}
        onChange={onCredentialChange}
      >
        <Group mt="xs">
          <Radio
            value="certificate"
            label="Certificate (recommended)"
            data-testid="sso-credential-certificate"
          />
          <Radio
            value="secret"
            label="Client secret"
            data-testid="sso-credential-secret"
          />
        </Group>
      </Radio.Group>

      {credential === 'certificate' ? (
        <Stack gap="xs">
          {!provider ? (
            <Text size="sm" c="dimmed">
              Save the provider first, then generate a certificate here.
            </Text>
          ) : (
            <>
              <CertificateRow
                title="Active certificate"
                cert={active}
                testId="sso-cert-active"
              >
                <Button
                  size="xs"
                  variant="default"
                  onClick={() => download('active')}
                  disabled={busy || !active}
                >
                  Download certificate
                </Button>
              </CertificateRow>
              <CertificateRow
                title="Pending certificate"
                cert={pending}
                testId="sso-cert-pending"
              >
                <Group gap="xs">
                  <Button
                    size="xs"
                    variant="default"
                    onClick={() => download('pending')}
                    disabled={busy || !pending}
                  >
                    Download certificate
                  </Button>
                  <Button
                    size="xs"
                    onClick={activate}
                    disabled={busy || !pending}
                    data-testid="sso-cert-activate"
                  >
                    Activate
                  </Button>
                </Group>
              </CertificateRow>
              {!pending && (
                <Button
                  size="xs"
                  variant="default"
                  style={{ alignSelf: 'flex-start' }}
                  onClick={generate}
                  disabled={busy}
                  data-testid="sso-cert-generate"
                >
                  Generate certificate
                </Button>
              )}
              {pending && (
                <Button
                  size="xs"
                  variant="subtle"
                  style={{ alignSelf: 'flex-start' }}
                  onClick={generate}
                  disabled={busy}
                >
                  Replace pending certificate
                </Button>
              )}
              <Text size="xs" c="dimmed">
                Download the certificate, upload it to your identity provider,
                then press Activate. Activating switches this provider to
                certificate sign-in.
              </Text>
            </>
          )}
        </Stack>
      ) : (
        <Stack gap="xs">
          <Select
            label="Authentication method"
            data={methodOptions}
            value={authMethod}
            onChange={onAuthMethodChange}
            allowDeselect={false}
            data-testid="sso-auth-method"
          />
          <PasswordInput
            label="Client secret"
            description={
              provider?.client_secret_set
                ? 'A secret is stored. Leave this empty to keep it.'
                : 'Paste the secret value.'
            }
            value={secret}
            onChange={(e) => onSecretChange(e.currentTarget.value)}
            autoComplete="new-password"
            data-testid="sso-client-secret"
          />
          <TextInput
            type="date"
            label="Secret expires on"
            description="Shown as a warning before the secret stops working."
            value={secretExpiry}
            onChange={(e) => onSecretExpiryChange(e.currentTarget.value)}
            data-testid="sso-secret-expiry"
          />
        </Stack>
      )}

      {provider?.credential_unreadable && (
        <Alert color="red" variant="light">
          The stored credential cannot be read (the server key changed). Enter
          the secret again or generate a new certificate.
        </Alert>
      )}
      {lines.length > 0 && (
        <Alert color="red" variant="light" data-testid="sso-credential-error">
          {lines.map((l) => (
            <div key={l}>{l}</div>
          ))}
        </Alert>
      )}
      {notice && (
        <Badge color="green" variant="light">
          {notice}
        </Badge>
      )}
    </Stack>
  );
};

export default OidcCredentialBlock;
