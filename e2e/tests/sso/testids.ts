/**
 * The frontend testIds the `sso` project drives, as data with no imports, so
 * `tests/guards/testid.spec.ts` can check them against `frontend/src/` without loading a
 * fixture (docs/adr/0003: a testId is a contract between the frontend and this suite).
 *
 * `SSO_TESTIDS` are used verbatim. `SSO_TESTID_PREFIXES` are completed at run time with a
 * provider's slug (`SsoSignIn.jsx` renders `sso-login-${provider.slug}`), so the guard
 * looks for the prefix in a template literal rather than for a whole attribute.
 */
export const SSO_TESTIDS = {
  signIn: 'sso-signin',
  error: 'sso-error',
} as const;

export const SSO_TESTID_PREFIXES = {
  loginButton: 'sso-login-',
} as const;

export function ssoLoginButton(slug: string): string {
  return `${SSO_TESTID_PREFIXES.loginButton}${slug}`;
}
