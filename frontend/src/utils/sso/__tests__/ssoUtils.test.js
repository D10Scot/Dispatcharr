import { describe, it, expect } from 'vitest';
import {
  adminErrorLines,
  buildProviderPayload,
  computeRedirectUri,
  emptyProviderValues,
  lockoutGuardMessages,
  providerEditPayload,
  providerToValues,
  rebaseProviderValues,
  postLoginDestination,
  safeNextPath,
  ssoErrorMessage,
  ssoStartUrl,
  testProblemMessage,
} from '../ssoUtils';
import { credentialReducer, initialCredentialState } from '../credentialEdits';

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

  // The credential keys come from the credential state (credentialEdits.js).
  const withEdits = (...actions) => ({
    ...base,
    credentialState: actions.reduce(
      credentialReducer,
      initialCredentialState(null)
    ),
  });

  it('omits client_secret when untouched and includes it when typed', () => {
    expect(
      Object.hasOwn(
        buildProviderPayload(
          withEdits({ type: 'credential', value: 'secret' })
        ),
        'client_secret'
      )
    ).toBe(false);
    expect(
      buildProviderPayload(
        withEdits(
          { type: 'credential', value: 'secret' },
          { type: 'secret', value: 's' }
        )
      ).client_secret
    ).toBe('s');
  });
  it('the certificate choice sends no client_auth_method, and still sends a typed secret', () => {
    const payload = buildProviderPayload(
      withEdits(
        { type: 'credential', value: 'secret' },
        { type: 'secret', value: 'typed' },
        { type: 'credential', value: 'certificate' }
      )
    );
    expect(payload.client_secret).toBe('typed');
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

describe('round 1 additions', () => {
  it('ssoStartUrl drops an off-origin next', () => {
    expect(ssoStartUrl('entra', '//evil.example')).toBe(
      '/api/accounts/oidc/entra/start/'
    );
  });
  it('a Streamer sign-in has the same copy the password login shows', () => {
    expect(ssoErrorMessage('ui_access_denied')).toMatch(
      /Streamer account and cannot log into the web UI/
    );
  });
  it('provider_unavailable does not claim the provider is down', () => {
    const copy = ssoErrorMessage('provider_unavailable');
    expect(copy).not.toMatch(
      /could not be reached|unreachable|is down|not reachable/i
    );
    expect(copy).toMatch(/could not be completed/i);
  });
  it('mapping values are trimmed', () => {
    const values = {
      ...emptyProviderValues('generic'),
      mappings: [{ value: ' Mino.Admin ', user_level: '10' }],
    };
    const payload = buildProviderPayload({
      values,
      provider: null,
      credential: 'certificate',
      secret: '',
      authMethod: 'client_secret_basic',
      secretExpiry: '',
    });
    expect(payload.mappings).toEqual([{ value: 'Mino.Admin', user_level: 10 }]);
  });
});

describe('providerEditPayload and rebaseProviderValues', () => {
  const server = {
    id: 1,
    display_name: 'X',
    slug: 'x',
    kind: 'generic',
    enabled: false,
    issuer: 'https://i',
    client_id: 'c',
    scopes: 'openid',
    claim_path: 'roles',
    mappings: [{ value: 'a', user_level: 10 }],
  };

  it('sends everything for a new provider', () => {
    const values = providerToValues(server);
    const payload = providerEditPayload({
      values,
      baseline: null,
      provider: null,
      credentialState: null,
    });
    expect(payload.enabled).toBe(false);
    expect(payload.kind).toBe('generic');
  });

  it('sends only changed fields for an edit', () => {
    const baseline = providerToValues(server);
    const values = { ...baseline, client_id: 'c2' };
    expect(
      providerEditPayload({
        values,
        baseline,
        provider: server,
        credentialState: null,
      })
    ).toEqual({ client_id: 'c2' });
  });

  it('does not re-send an unchanged client_auth_method', () => {
    // A form opened while the provider used a secret: an unrelated save must
    // not re-send the method, or it would switch back a certificate another
    // administrator activated meanwhile.
    const loaded = { ...server, client_auth_method: 'client_secret_post' };
    const baseline = providerToValues(loaded);
    const values = { ...baseline, display_name: 'Y' };
    expect(
      providerEditPayload({
        values,
        baseline,
        provider: loaded,
        credentialState: initialCredentialState(loaded),
      }),
      'an unchanged client_auth_method was re-sent'
    ).toEqual({ display_name: 'Y' });
  });

  it('sends client_auth_method when the administrator switches it', () => {
    const loaded = { ...server, client_auth_method: 'private_key_jwt' };
    const baseline = providerToValues(loaded);
    const state = credentialReducer(initialCredentialState(loaded), {
      type: 'credential',
      value: 'secret',
    });
    expect(
      providerEditPayload({
        values: baseline,
        baseline,
        provider: loaded,
        credentialState: state,
      })
    ).toEqual({ client_auth_method: 'client_secret_basic' });
  });

  it('rebases untouched fields and keeps edited ones', () => {
    const baseline = providerToValues(server);
    const values = { ...baseline, client_id: 'mine' };
    const fresh = { ...server, enabled: true, client_id: 'theirs' };
    const rebased = rebaseProviderValues(values, baseline, fresh);
    expect(rebased.enabled).toBe(true);
    expect(rebased.client_id).toBe('mine');
  });
});
