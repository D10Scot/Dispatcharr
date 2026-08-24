/**
 * The one gate on creating a superuser, shared by both paths that create one.
 *
 * Two code paths in this harness can turn an instance that has never been set
 * up into one with a permanent admin whose password is committed to this
 * repository in plain text:
 *
 *   - `bootstrap.setup.ts`, over the API, as a dependency of every project
 *     except `pristine`;
 *   - `tests/pristine/first-run-setup-and-login.spec.ts`, by driving the
 *     first-run form in a browser.
 *
 * Both must consult this module. A guard that lives in only one of them is
 * not a guard — the second path is simply the way around it.
 */

/** Env var that opts a run in to superuser creation on any target. */
export const SETUP_OPT_IN = 'E2E_ALLOW_REMOTE_SUPERUSER';

/** The exact value that opts in. Nothing else does — see `mayCreateSuperuser`. */
const OPT_IN_VALUE = '1';

/** 127.0.0.0/8, anchored at both ends — see the note in `isLoopbackHost`. */
const IPV4_LOOPBACK = /^127\.\d{1,3}\.\d{1,3}\.\d{1,3}$/;

/**
 * Whether `hostname` names this machine.
 *
 * IPv6 literals arrive from `URL.hostname` still wrapped in brackets, and an
 * IPv4-mapped v6 address is a loopback address written the long way. `URL`
 * normalises the readable form to hex — `http://[::ffff:127.0.0.1]/` parses
 * to a hostname of `[::ffff:7f00:1]` — so both spellings are matched, the
 * hex one being the only one that actually arrives from a parsed URL.
 *
 * The dotted-quad test is anchored at *both* ends, and that is the whole
 * point of it being a named constant. An unanchored `/^127\./` — which is
 * what this check used to be — matches the hostname `127.0.0.1.nip.io`,
 * which is a public DNS name anybody can point anywhere. Confirmed by
 * pointing `E2E_BASE_URL` at it: the guard admitted it and the run created a
 * superuser. A prefix test on a string that may be a *name* rather than an
 * address is not an address test.
 *
 * `0.0.0.0` is deliberately absent: as a *destination* it means this machine
 * on most stacks, but it is also what a misconfigured base URL looks like,
 * and refusing it costs nothing.
 */
export function isLoopbackHost(hostname: string): boolean {
  const host = hostname.replace(/^\[|\]$/g, '').toLowerCase();
  return (
    host === 'localhost' ||
    host.endsWith('.localhost') ||
    host === '::1' ||
    IPV4_LOOPBACK.test(host) ||
    (host.startsWith('::ffff:') &&
      IPV4_LOOPBACK.test(host.slice('::ffff:'.length))) ||
    // ::ffff:7f00:0 – ::ffff:7fff:ffff is 127.0.0.0/8 mapped into v6.
    /^::ffff:7f[0-9a-f]{2}:[0-9a-f]{1,4}$/.test(host)
  );
}

/**
 * Whether this run may create a superuser on the instance at `baseURL`.
 *
 * Default-deny, with exactly two ways through, in this order:
 *
 * 1. `E2E_ALLOW_REMOTE_SUPERUSER=1` — an *exact* string comparison, not a
 *    truthiness test. `=0` and `=false` are the values somebody reaches for
 *    to turn a switch off; a truthy check reads both as "yes", which is the
 *    opposite of what the operator asked for.
 * 2. The target is loopback. This exemption is deliberate and it is not
 *    free — see the note below — but it is what keeps the opt-in meaningful.
 *
 * ## Why loopback is exempt
 *
 * The exemption is not a claim that loopback is safe. `localhost:9191` can be
 * an SSH tunnel to a real box, or a real deployment on this machine that
 * nobody has finished setting up. Both would be handed the committed
 * password.
 *
 * It is exempt because the alternative is worse. CI and every local run
 * target loopback, so default-denying it means the documented, everyday
 * invocation fails until the operator sets the opt-in — and an opt-in that
 * must be set on every ordinary run ends up exported in a shell profile,
 * where it also silently disarms the guard for the remote targets it exists
 * to protect. A bypass everyone has is not a guard.
 *
 * The residual risk is bounded by the fact that creation is only ever reached
 * when the instance reports no superuser: an instance in use has one already
 * and never reaches this function. What is left is a deployed-but-never-set-up
 * instance that somebody deliberately pointed a test suite at. If that is
 * you, `E2E_BASE_URL` is the thing to check, and there is no automated
 * substitute for checking it.
 */
export function mayCreateSuperuser(baseURL: string): boolean {
  if (process.env[SETUP_OPT_IN] === OPT_IN_VALUE) return true;

  let hostname: string;
  try {
    hostname = new URL(baseURL).hostname;
  } catch {
    // Fail closed. An unparseable base URL is a configuration bug, and this
    // is not the place to guess what was meant.
    return false;
  }
  return isLoopbackHost(hostname);
}

/** `mayCreateSuperuser`, as an assertion with an actionable message. */
export function assertMayCreateSuperuser(baseURL: string): void {
  if (mayCreateSuperuser(baseURL)) return;

  const optIn = process.env[SETUP_OPT_IN];
  const nearMiss =
    optIn === undefined || optIn === ''
      ? ''
      : ` ${SETUP_OPT_IN} is currently ${JSON.stringify(optIn)}, which is not ` +
        `the literal "${OPT_IN_VALUE}" and does not opt in.`;

  throw new Error(
    `refusing to create a superuser on ${baseURL}: that instance reports no ` +
      'superuser yet, and this suite would create one whose password is ' +
      'committed to this repository in plain text, as a permanent admin on a ' +
      `host that is not this machine. Point E2E_BASE_URL at a throwaway ` +
      `instance, or set ${SETUP_OPT_IN}=${OPT_IN_VALUE} if that really is ` +
      `what you want.${nearMiss} Running against an instance that is ` +
      '*already* set up needs neither.'
  );
}
