import { describe, it, expect } from 'vitest';
import {
  adminErrorLines,
  buildProviderPayload,
  computeRedirectUri,
  emptyProviderValues,
  lockoutGuardMessages,
  postLoginDestination,
  safeNextPath,
  ssoErrorMessage,
  ssoStartUrl,
  testProblemMessage,
} from '../ssoUtils';

describe('safeNextPath', () => {
  it.each(['/', '/guide', '/settings#single-sign-on', '/a?b=c'])(
    'accepts %s',
    (v) => {
      expect(safeNextPath(v)).toBe(v);
    }
  );
  it.each([
    '//evil.example',
    '/\\evil',
    'https://evil.example',
    'javascript:alert(1)',
    'guide',
    '',
    '/a\\b',
    '/a\u0000b',
    '/a\nb',
    '/' + 'x'.repeat(512),
    null,
    undefined,
    42,
  ])('rejects %j', (v) => {
    expect(safeNextPath(v)).toBeNull();
  });
});

describe('postLoginDestination', () => {
  it('falls back for the login pages and the root', () => {
    expect(postLoginDestination('/login')).toBe('/channels');
    expect(postLoginDestination('/login/sso')).toBe('/channels');
    expect(postLoginDestination('/')).toBe('/channels');
    expect(postLoginDestination('//x')).toBe('/channels');
    expect(postLoginDestination('/guide')).toBe('/guide');
  });
});

describe('ssoStartUrl', () => {
  it('is origin-relative and encodes both parts', () => {
    expect(ssoStartUrl('entra', '/a b')).toBe(
      '/api/accounts/oidc/entra/start/?next=%2Fa%20b'
    );
    expect(ssoStartUrl('a/b', null)).toBe('/api/accounts/oidc/a%2Fb/start/');
  });
});

describe('computeRedirectUri', () => {
  it('matches the server format and tolerates a trailing slash', () => {
    expect(computeRedirectUri('https://h.example/', 'entra')).toBe(
      'https://h.example/api/accounts/oidc/entra/callback/'
    );
    expect(computeRedirectUri('', 'entra')).toBe('');
    expect(computeRedirectUri('https://h.example', '')).toBe('');
  });
});

describe('fixed copy', () => {
  it('maps known codes and falls back for anything else', () => {
    expect(ssoErrorMessage('no_mapping')).toMatch(/not assigned a role/);
    expect(ssoErrorMessage('constructor')).toMatch(/could not complete/);
    expect(ssoErrorMessage('__proto__')).toMatch(/could not complete/);
    expect(ssoErrorMessage(undefined)).toMatch(/could not complete/);
  });
  it('lockout reasons map one-to-one; unknown ones get one generic line', () => {
    expect(
      lockoutGuardMessages(['not_sso_session', 'last_enabled_provider'])
    ).toHaveLength(2);
    expect(lockoutGuardMessages(['nope'])).toHaveLength(1);
    expect(lockoutGuardMessages(undefined)).toHaveLength(1);
  });
  it('covers the discovery codes S2 added', () => {
    for (const code of [
      'jwks_private_key',
      'discovery_endpoint_invalid',
      'discovery_endpoint_insecure',
    ]) {
      expect(testProblemMessage(code)).not.toMatch(
        /does not recognise|not recognise/
      );
    }
    expect(testProblemMessage('whatever')).toMatch(/not recognise/);
  });
  it('coded admin errors never surface server text', () => {
    expect(
      adminErrorLines({ body: { code: 'something_new', detail: '<img>' } })
    ).toEqual(['The server refused this change.']);
    expect(adminErrorLines({})).toEqual(['The change could not be saved.']);
    expect(
      adminErrorLines({ body: { client_id: ['This field is required.'] } })
    ).toEqual(['client_id: This field is required.']);
  });
});

describe('buildProviderPayload', () => {
  const base = {
    values: {
      ...emptyProviderValues('generic'),
      display_name: 'X',
      slug: 'x',
      issuer: 'https://i',
      client_id: 'c',
    },
    provider: null,
    credential: 'secret',
    secret: '',
    authMethod: 'client_secret_basic',
    secretExpiry: '',
  };

  it('omits client_secret when untouched and includes it when typed', () => {
    expect(Object.hasOwn(buildProviderPayload(base), 'client_secret')).toBe(
      false
    );
    expect(buildProviderPayload({ ...base, secret: 's' }).client_secret).toBe(
      's'
    );
  });
  it('sends no credential fields for the certificate choice', () => {
    const payload = buildProviderPayload({
      ...base,
      credential: 'certificate',
      secret: 'ignored',
    });
    expect(Object.hasOwn(payload, 'client_secret')).toBe(false);
    expect(Object.hasOwn(payload, 'client_auth_method')).toBe(false);
  });
  it('sends only the fields of the chosen kind', () => {
    const entra = buildProviderPayload({
      ...base,
      values: { ...emptyProviderValues('entra'), entra_tenant_id: 't' },
    });
    expect(entra.entra_tenant_id).toBe('t');
    expect(Object.hasOwn(entra, 'issuer')).toBe(false);
    expect(Object.hasOwn(entra, 'allow_private_network')).toBe(false);
  });
  it('drops blank mapping rows and numbers the level', () => {
    const values = {
      ...base.values,
      mappings: [
        { value: 'a', user_level: '10' },
        { value: ' ', user_level: '1' },
      ],
    };
    expect(buildProviderPayload({ ...base, values }).mappings).toEqual([
      { value: 'a', user_level: 10 },
    ]);
  });
});
