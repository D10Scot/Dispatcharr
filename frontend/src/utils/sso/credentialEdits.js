/**
 * The provider form's credential state (spec 5.2), as a pure model.
 *
 * The form holds two things: the provider exactly as the server last returned
 * it, and the administrator's explicit edits since then. Everything shown on
 * screen and everything sent in a PATCH is derived from those two by the pure
 * functions below; no edit ever overwrites another field's value. That is the
 * point: the "a new secret never inherits the old date" rule is applied where
 * the display and the payload are derived, never by mutating the date when a
 * key is pressed, so the order of edits cannot destroy data.
 *
 * Edits:
 * - `secret`: what is in the secret field ('' means none typed).
 * - `secretSince`: the step at which the field last went from empty to
 *   non-empty, so a date can be judged to have been set before or after the
 *   current secret was typed.
 * - `date`: the expiry date the administrator entered (undefined: untouched;
 *   '': explicitly cleared), and `dateAt`, the step at which it was entered.
 * - `credential`: the Credential radio the administrator chose (undefined:
 *   untouched, show the method in use).
 * - `authMethod`: the secret method the administrator chose (undefined:
 *   untouched).
 *
 * After a successful save the edits are dropped and the provider replaced
 * with the server's answer, so the form shows exactly what is stored. A
 * reload (after a certificate action) replaces the provider and keeps the
 * edits: they are unsaved, and still on screen.
 */

export const NO_EDITS = Object.freeze({
  step: 0,
  secret: '',
  secretSince: null,
  date: undefined,
  dateAt: null,
  credential: undefined,
  authMethod: undefined,
});

export const initialCredentialState = (provider) => ({
  provider: provider ?? null,
  edits: NO_EDITS,
});

export const storedSecretDate = (provider) =>
  provider?.client_secret_expires_at ?? '';

// The radio a provider opens with: the credential its client_auth_method uses.
// A provider not saved yet starts on the certificate, the recommended choice.
export const storedCredential = (provider) =>
  !provider || provider.client_auth_method === 'private_key_jwt'
    ? 'certificate'
    : 'secret';

export const storedAuthMethod = (provider, kind) =>
  provider && provider.client_auth_method !== 'private_key_jwt'
    ? provider.client_auth_method
    : kind === 'entra'
      ? 'client_secret_post'
      : 'client_secret_basic';

/**
 * The reducer the form runs. Actions:
 *   { type: 'secret', value }        the secret field changed
 *   { type: 'date', value }          the expiry field changed ('' = cleared)
 *   { type: 'credential', value }    the radio changed
 *   { type: 'authMethod', value }    the secret method changed
 *   { type: 'saved', provider }      a save succeeded; provider is the answer
 *   { type: 'reloaded', provider }   the provider was fetched again
 */
export const credentialReducer = (state, action) => {
  const { edits } = state;
  const step = edits.step + 1;
  switch (action.type) {
    case 'secret': {
      const secret = action.value ?? '';
      let secretSince = edits.secretSince;
      if (secret === '') secretSince = null;
      else if (edits.secret === '') secretSince = step;
      return { ...state, edits: { ...edits, step, secret, secretSince } };
    }
    case 'date':
      return {
        ...state,
        edits: { ...edits, step, date: action.value ?? '', dateAt: step },
      };
    case 'credential':
      return { ...state, edits: { ...edits, step, credential: action.value } };
    case 'authMethod':
      return { ...state, edits: { ...edits, step, authMethod: action.value } };
    case 'saved':
      return initialCredentialState(action.provider);
    case 'reloaded':
      return { ...state, provider: action.provider ?? state.provider };
    default:
      return state;
  }
};

/**
 * What the next save says about client_secret_expires_at: undefined means the
 * key is left out (the stored date is kept), null clears it, a string sets it.
 *
 * - With a new secret the key is always sent: the administrator's date if they
 *   entered one for it, otherwise null, because a new secret never inherits the
 *   old one's date. A date equal to the stored one that was entered BEFORE the
 *   secret was typed is the old date, not a date for the new secret.
 * - Without a new secret the key is sent only when the administrator changed
 *   the date to something other than what is stored (set or cleared).
 */
export const secretDateToSend = (provider, edits) => {
  const stored = storedSecretDate(provider);
  const newSecret = edits.secret !== '';
  const differs = edits.date !== undefined && edits.date !== stored;
  if (newSecret) {
    const forThisSecret =
      edits.date !== undefined && (differs || edits.dateAt > edits.secretSince);
    return forThisSecret ? edits.date || null : null;
  }
  return differs ? edits.date || null : undefined;
};

/**
 * Everything the credential block shows, derived from the state alone.
 * `pendingSecret` / `pendingDate`: the next save will write a new secret / a
 * new expiry date. The certificate view shows them, so a secret is never sent
 * while the screen hides it.
 */
export const credentialView = (state, kind) => {
  const { provider, edits } = state;
  const toSend = secretDateToSend(provider, edits);
  return {
    credential: edits.credential ?? storedCredential(provider),
    authMethod: edits.authMethod ?? storedAuthMethod(provider, kind),
    secret: edits.secret,
    secretExpiry:
      toSend === undefined ? storedSecretDate(provider) : (toSend ?? ''),
    pendingSecret: edits.secret !== '',
    pendingDate: toSend !== undefined,
  };
};

/**
 * The credential keys of a provider PATCH or POST.
 * - `client_auth_method` only while the radio is on "Client secret": saving
 *   there selects the secret method (switching a certificate provider back is
 *   this one PATCH, spec 5.2). The certificate method is set only by Activate.
 * - `client_secret` and `client_secret_expires_at` whatever the radio says:
 *   the server stores a secret beside a certificate, and a typed secret is not
 *   dropped because the administrator looked at the certificate view.
 */
export const credentialPayload = (state, kind) => {
  const view = credentialView(state, kind);
  const payload = {};
  if (view.credential === 'secret')
    payload.client_auth_method = view.authMethod;
  if (state.edits.secret !== '') payload.client_secret = state.edits.secret;
  const date = secretDateToSend(state.provider, state.edits);
  if (date !== undefined) payload.client_secret_expires_at = date;
  return payload;
};
