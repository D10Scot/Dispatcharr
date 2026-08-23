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
 * the guard in `bootstrap.setup.ts` around superuser creation.
 */
export const ADMIN = {
  username: 'e2e-admin',
  password: 'Correct-Horse-Battery-Staple-42!',
  email: 'e2e-admin@example.com',
};
