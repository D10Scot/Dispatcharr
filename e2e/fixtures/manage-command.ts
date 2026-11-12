/**
 * The one line that runs `manage.py` in the Mino container, as a pure builder.
 *
 * `fixtures/instance.ts`'s `manage()` runs it, and `docs/sso-recovery.md`
 * documents it for an operator. Both read from here so the page and the
 * fixture cannot drift apart: `tests/guards/sso-recovery-doc.spec.ts` checks
 * every documented command against this builder. Keeping it in a module of
 * its own, with no container capability, is what lets that guard import it.
 *
 * Why a login shell: the server reads `DJANGO_SECRET_KEY` from the
 * environment, PID 1 exports it from `/data/jwt`, and a `docker exec` process
 * does not inherit PID 1's exports. The entrypoint writes what a later shell
 * needs to the login profile, which only `su -` loads (SSO spec 5.6).
 */

/**
 * `docker/entrypoint.sh`: `POSTGRES_USER=${POSTGRES_USER:-dispatch}`, and every
 * `manage.py` invocation in that file runs as `su - "$POSTGRES_USER"`. The
 * login dash is not cosmetic — the same file notes that `su -` strips the
 * environment and that it publishes PATH through the login profile precisely
 * so this form works.
 */
export const APP_USER = "dispatch";

/**
 * `argv` is interpolated into a shell command, so it is restricted to plain
 * tokens. Nothing this suite needs is more than that, and accepting more would
 * make a fixture that shells into a container quietly able to run anything.
 */
export const PLAIN_TOKEN = /^[A-Za-z0-9._/=-]+$/;

export function assertPlainTokens(argv: string[]): void {
  for (const arg of argv) {
    if (!PLAIN_TOKEN.test(arg)) {
      throw new Error(
        `instance.manage() argument ${JSON.stringify(arg)} contains ` +
          "characters that are not plain tokens. This runs through a shell " +
          "inside the container; quote-free arguments only.",
      );
    }
  }
}

/** The command the login shell runs: `cd /app && python manage.py <argv>`. */
export function manageInner(argv: string[]): string {
  assertPlainTokens(argv);
  return `cd /app && python manage.py ${argv.join(" ")}`;
}

/** `docker` argv for `docker exec <container> su - dispatch -c '<inner>'`. */
export function manageExecArgs(container: string, argv: string[]): string[] {
  return ["exec", container, "su", "-", APP_USER, "-c", manageInner(argv)];
}
