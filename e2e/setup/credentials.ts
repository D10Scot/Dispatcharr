/**
 * The admin principal the whole suite runs as.
 *
 * Its own module, not an export of `bootstrap.setup.ts`, because importing
 * that file registers its `setup(...)` call as a test in whichever spec
 * imports it — the pristine project would run bootstrap, and bootstrap is
 * exactly what pristine must not have run.
 *
 * NOT A SECRET. This password is committed to a public repository. It is
 * fine for a throwaway local or CI container and is fine nowhere else; see
 * `superuser-guard.ts`, which both creation paths consult before using it.
 *
 * Deliberately fixed rather than generated per run: this same pair is already
 * written to `playwright/.auth/tokens.json` alongside live admin JWTs, so a
 * random password stored beside them would protect nobody who can read that
 * directory, while a password the container remembers and the checkout has
 * forgotten is an unrecoverable-without-a-reset failure that the fixed
 * constant cannot have.
 */
export const ADMIN = {
  username: 'e2e-admin',
  password: 'Correct-Horse-Battery-Staple-42!',
  email: 'e2e-admin@example.com',
};
