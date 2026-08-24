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
 * Deliberately fixed rather than generated per run. Randomising would be a
 * real gain against a *network* reader — a committed password is permanently
 * world-known, where the JWTs beside it expire in 30 minutes — but the local
 * container is published on 127.0.0.1 only and CI's is on an ephemeral
 * runner, so no network reader remains. What is left is a reader of this
 * checkout, and a generated password would have to be persisted next to
 * `playwright/.auth/tokens.json`, which already holds live admin tokens: no
 * gain there either. Against that, a password the container remembers and the
 * checkout has forgotten is a hard failure recoverable only by destroying the
 * container, which the fixed constant cannot have.
 */
export const ADMIN = {
  username: 'e2e-admin',
  password: 'Correct-Horse-Battery-Staple-42!',
  email: 'e2e-admin@example.com',
};
