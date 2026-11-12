// Pure helpers for the single sign-on UI (spec 5.7). Nothing here touches the
// network, the DOM or storage, so every function is testable on its own.

export const OIDC_BASE = '/api/accounts/oidc';
export const SSO_LANDING_PATH = '/login/sso';
export const DEFAULT_ROUTE = '/channels';

const MAX_NEXT_LENGTH = 512;
// eslint-disable-next-line no-control-regex
const CONTROL_CHAR = /[\u0000-\u001f\u007f]/;

/**
 * A same-origin path, or null. Mirrors the server's rule (spec 3.2 step 2): one
 * leading "/", not "//" or "/\", no backslash, scheme or control character, at
 * most 512 characters. Used for every destination that came from outside the
 * code (a `next` query parameter, the exchange response).
 */
export const safeNextPath = (value) => {
  if (typeof value !== 'string') return null;
  if (value.length === 0 || value.length > MAX_NEXT_LENGTH) return null;
  if (!value.startsWith('/') || value.startsWith('//')) return null;
  if (value.includes('\\') || CONTROL_CHAR.test(value)) return null;
  // "/x:" style or an embedded scheme can only matter if the string is not a path.
  if (/^\/[^/?#]*:\/\//.test(value)) return null;
  return value;
};

// The pages that would loop or that only exist while signed out.
const NOT_A_DESTINATION = ['/login', SSO_LANDING_PATH];

/** Where to go after a sign-in: the validated `next`, else the default route. */
export const postLoginDestination = (next) => {
  const safe = safeNextPath(next);
  if (!safe) return DEFAULT_ROUTE;
  const path = safe.split(/[?#]/)[0];
  if (NOT_A_DESTINATION.includes(path)) return DEFAULT_ROUTE;
  if (path === '/') return DEFAULT_ROUTE;
  return safe;
};

/** Origin-relative start URL for the login button's top-level navigation. */
export const ssoStartUrl = (slug, next) => {
  const base = `${OIDC_BASE}/${encodeURIComponent(slug)}/start/`;
  const safe = safeNextPath(next);
  return safe ? `${base}?next=${encodeURIComponent(safe)}` : base;
};

/** The redirect URI the provider form shows, built exactly as the server builds it. */
export const computeRedirectUri = (publicBaseUrl, slug) => {
  const base = (publicBaseUrl || '').trim().replace(/\/+$/, '');
  if (!base || !slug) return '';
  return `${base}${OIDC_BASE}/${slug}/callback/`;
};

export const ENTRA_MAX_REDIRECT_URI = 256;

// ---------------------------------------------------------------------------
// Fixed copy. Error codes map to fixed messages; a code this build does not
// know falls back to a generic one. No provider-supplied string is ever shown
// through these maps.
// ---------------------------------------------------------------------------

const GENERIC_SIGN_IN_ERROR =
  'Single sign-on could not complete. Try again, or ask an administrator.';

export const SSO_ERROR_COPY = {
  client_auth_failed:
    'The identity provider rejected this application’s credential. It has probably expired or been replaced. An administrator needs to update it in Settings, Single sign-on.',
  last_admin:
    'This sign-in was refused because it would remove the last active administrator.',
  no_mapping:
    'Your account is not assigned a role that this application maps to a level. Ask an administrator to assign one.',
  inactive: 'Your account is disabled. Ask an administrator.',
  groups_overage:
    'Your identity provider sent too many groups to fit in the sign-in token. Ask an administrator to map roles instead of groups.',
  link_conflict:
    'That identity provider account is already linked to a different user.',
  idp_error: 'The identity provider reported an error and did not sign you in.',
  state_invalid:
    'The sign-in attempt expired or was already used. Start again.',
  binding_invalid:
    'The sign-in attempt did not start in this browser. Start again from this page.',
  provider_mismatch:
    'The sign-in response did not match the provider you started with. Start again.',
  issuer_mismatch:
    'The sign-in response came from an unexpected issuer. Start again.',
  token_exchange_failed:
    'The identity provider did not accept the sign-in. Try again, or ask an administrator.',
  id_token_invalid:
    'The identity provider’s sign-in token could not be verified. Ask an administrator.',
  provisioning_failed:
    'Your account could not be created or updated. Ask an administrator.',
  provider_unavailable:
    'The identity provider could not be reached. Try again shortly.',
  sso_unavailable:
    'Single sign-on is temporarily unavailable. Try again shortly.',
  sso_not_configured: 'Single sign-on is not configured on this server.',
  exchange_failed:
    'Sign-in could not be completed after the identity provider returned. Start again.',
};

/** Fixed message for an `sso_error` code, generic for anything unknown. */
export const ssoErrorMessage = (code) => {
  if (typeof code === 'string' && Object.hasOwn(SSO_ERROR_COPY, code)) {
    return SSO_ERROR_COPY[code];
  }
  return GENERIC_SIGN_IN_ERROR;
};

export const LOCKOUT_GUARD_COPY = {
  not_sso_session:
    'You are not signed in through single sign-on. Sign in with a provider first, so you are certain to get back in.',
  provider_not_enabled: 'The provider you signed in with is not enabled now.',
  not_admin_at_sign_in:
    'Your provider did not sign you in as an administrator. Only a sign-in that maps to Admin can switch passwords off.',
  last_enabled_provider:
    'Password sign-in is off, so the last enabled provider cannot be disabled or deleted.',
};

export const lockoutGuardMessages = (reasons) => {
  const list = Array.isArray(reasons) ? reasons : [];
  const known = list.filter(
    (r) => typeof r === 'string' && Object.hasOwn(LOCKOUT_GUARD_COPY, r)
  );
  return known.length > 0
    ? known.map((r) => LOCKOUT_GUARD_COPY[r])
    : ['This change was refused because it could lock everyone out.'];
};

export const TEST_PROBLEM_COPY = {
  credential_unreadable:
    'The stored credential cannot be read (the server key changed). Enter the secret again or generate a new certificate.',
  public_base_url_unset: 'Set the public base URL first.',
  redirect_uri_too_long:
    'The redirect URI is longer than the 256 characters Entra allows. Shorten the slug or the public base URL.',
  discovery_unreachable: 'The discovery document could not be fetched.',
  discovery_http_error: 'The discovery endpoint answered with an error.',
  discovery_invalid: 'The discovery document is not valid JSON.',
  discovery_too_large: 'The discovery document is too large.',
  discovery_redirect:
    'The discovery endpoint redirected, which is not allowed.',
  discovery_not_allowed:
    'The discovery address is not allowed (private or unsafe address).',
  discovery_issuer_mismatch:
    'The discovery document names a different issuer than the one configured.',
  discovery_endpoint_missing:
    'The discovery document is missing a required endpoint.',
  discovery_endpoint_invalid:
    'The discovery document has an endpoint that is not a valid URL.',
  discovery_endpoint_insecure:
    'The discovery document has an endpoint that is not https.',
  token_endpoint_not_allowed:
    'The token endpoint address is not allowed. On a private network, switch on the private-network option.',
  jwks_unreachable: 'The signing keys could not be fetched.',
  jwks_http_error: 'The signing-key endpoint answered with an error.',
  jwks_invalid: 'The signing keys are not valid.',
  jwks_too_large: 'The signing-key document is too large.',
  jwks_redirect: 'The signing-key endpoint redirected, which is not allowed.',
  jwks_uri_not_allowed: 'The signing-key address is not allowed.',
  jwks_private_key:
    'The signing-key document contains a private key, which is refused.',
};

export const testProblemMessage = (code) =>
  typeof code === 'string' && Object.hasOwn(TEST_PROBLEM_COPY, code)
    ? TEST_PROBLEM_COPY[code]
    : 'The test reported a problem this version does not recognise.';

/** Fixed copy for a coded admin-API error, or null when there is none. */
const ADMIN_ERROR_COPY = {
  password_toggle_unavailable:
    'Turning password sign-in off is not available in this version.',
  pending_certificate_changed:
    'Another administrator generated a newer certificate. The block has been reloaded: check the thumbprint and activate again.',
  public_base_url_insecure:
    'The public base URL must be https. Plain http is accepted only for localhost.',
  redirect_uri_too_long: TEST_PROBLEM_COPY.redirect_uri_too_long,
  credential_missing:
    'Add a credential (a client secret, or an activated certificate) before enabling the provider.',
  provider_has_identities:
    'This provider still has linked identities. Unlink them first.',
  requires_postgresql:
    'Single sign-on needs PostgreSQL; it cannot be configured on this database.',
  certificate_not_found: 'There is no certificate in that slot.',
  not_found: 'That provider no longer exists.',
};

/**
 * Lines to show for a failed admin-API call. Every line is fixed copy or a
 * field validation message from the server (DRF's own validation text for a
 * field the administrator typed); a coded error never shows server text.
 */
export const adminErrorLines = (error) => {
  const body = error?.body;
  if (body && typeof body === 'object' && typeof body.code === 'string') {
    if (body.code === 'lockout_guard')
      return lockoutGuardMessages(body.reasons);
    if (Object.hasOwn(ADMIN_ERROR_COPY, body.code)) {
      return [ADMIN_ERROR_COPY[body.code]];
    }
    return ['The server refused this change.'];
  }
  if (body && typeof body === 'object' && !Array.isArray(body)) {
    const lines = [];
    for (const [field, messages] of Object.entries(body)) {
      const list = Array.isArray(messages) ? messages : [messages];
      for (const m of list) {
        if (typeof m === 'string') lines.push(`${field}: ${m}`);
      }
    }
    if (lines.length > 0) return lines;
  }
  return ['The change could not be saved.'];
};

export const credentialWarningMessage = (warning) => {
  const slug = typeof warning?.slug === 'string' ? warning.slug : 'a provider';
  if (warning?.state === 'expired') {
    return `The credential for the single sign-on provider “${slug}” has expired. Nobody can sign in through it until it is replaced.`;
  }
  const days = Number.isInteger(warning?.days_left) ? warning.days_left : null;
  return days === null
    ? `The credential for the single sign-on provider “${slug}” is about to expire.`
    : `The credential for the single sign-on provider “${slug}” expires in ${days} day${days === 1 ? '' : 's'}.`;
};

export const ENTRA_SETUP_DOC_URL =
  'https://github.com/D10Scot/Dispatcharr/blob/main/docs/sso-entra-setup.md';

export const MAPPING_LEVELS = [
  { value: '0', label: 'Streamer' },
  { value: '1', label: 'Standard' },
  { value: '10', label: 'Admin' },
];

export const emptyProviderValues = (kind) => ({
  display_name: kind === 'entra' ? 'Microsoft' : '',
  slug: kind === 'entra' ? 'entra' : '',
  kind,
  enabled: false,
  issuer: '',
  entra_tenant_id: '',
  client_id: '',
  allow_private_network: false,
  scopes: 'openid profile email',
  id_token_alg: 'RS256',
  claim_path: kind === 'entra' ? 'roles' : '',
  prompt_select_account: false,
  mappings: [],
});

export const providerToValues = (provider) => ({
  display_name: provider.display_name,
  slug: provider.slug,
  kind: provider.kind,
  enabled: provider.enabled,
  issuer: provider.issuer ?? '',
  entra_tenant_id: provider.entra_tenant_id ?? '',
  client_id: provider.client_id ?? '',
  allow_private_network: !!provider.allow_private_network,
  scopes: provider.scopes ?? 'openid profile email',
  id_token_alg: provider.id_token_alg ?? 'RS256',
  claim_path: provider.claim_path ?? '',
  prompt_select_account: !!provider.prompt_select_account,
  mappings: (provider.mappings ?? []).map((m) => ({
    value: m.value,
    user_level: String(m.user_level),
  })),
});

/**
 * The body for POST/PATCH providers-admin. The client secret is write-only: it
 * is included ONLY when the administrator typed one; an untouched field never
 * sends `client_secret` (an empty string is refused by the server, and would
 * never mean "clear").
 */
export const buildProviderPayload = ({
  values,
  provider,
  credential,
  secret,
  authMethod,
  secretExpiry,
}) => {
  const payload = {
    display_name: values.display_name,
    slug: values.slug,
    enabled: values.enabled,
    client_id: values.client_id,
    scopes: values.scopes,
    claim_path: values.claim_path,
    prompt_select_account: values.prompt_select_account,
    mappings: values.mappings
      .filter((m) => m.value.trim() !== '')
      .map((m) => ({ value: m.value, user_level: Number(m.user_level) })),
  };
  if (!provider) payload.kind = values.kind;
  if (values.kind === 'entra') {
    payload.entra_tenant_id = values.entra_tenant_id;
  } else {
    payload.issuer = values.issuer;
    payload.allow_private_network = values.allow_private_network;
    payload.id_token_alg = values.id_token_alg;
  }
  if (credential === 'secret') {
    payload.client_auth_method = authMethod;
    if (secret !== '') payload.client_secret = secret;
    const before = provider?.client_secret_expires_at ?? '';
    if (secretExpiry !== (before || '') || secret !== '') {
      payload.client_secret_expires_at = secretExpiry || null;
    }
  }
  return payload;
};
