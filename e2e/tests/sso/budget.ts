/**
 * The `oidc` throttle budget of each SSO project, declared and counted.
 *
 * Mino's `oidc` throttle (`OIDCRateThrottle`, the `oidc` rate in
 * `dispatcharr/settings.py`) allows 20 requests a minute per client IP across `start`,
 * `link/start`, `callback` and `exchange`. Every SSO project shares one stack's client
 * IP, so a project's whole run has to fit inside one window. `OIDC_BUDGET` is what each
 * project declares it spends; `e2e/README.md` and each spec header state the same number,
 * which `tests/guards/sso-budget.spec.ts` checks, with the headroom below.
 *
 * Counted at run time, not estimated: `tests/sso/fixtures.ts` overrides the `context`
 * fixture so every request the browser makes to a throttled route is recorded in a
 * per-project ledger, and after each test fails it if the run so far has spent more
 * than the project declared. The ledger belongs to one Playwright invocation (keyed by
 * the runner's pid, the parent of every worker), so it survives a worker restart and
 * starts again on the next run. What it cannot see, a request made outside the browser,
 * `tests/guards/sso-budget.spec.ts` refuses statically: no throttled route appears as a
 * string under `tests/sso/`.
 *
 * Pure apart from `OidcLedger`'s file, so the path classifier is pinned in the guards
 * project with no browser.
 */
import fs from 'node:fs';
import path from 'node:path';

/** Requests a minute the `oidc` throttle allows per client IP (`dispatcharr/settings.py`). */
export const OIDC_THROTTLE_PER_MINUTE = 20;

/**
 * Left unspent by every project, so one stray request (a person's curl at the stack, a
 * browser re-request) does not throttle a green run.
 */
export const OIDC_HEADROOM = 3;

/** What each SSO spec project spends in one full run. Stated again in the README and spec headers. */
export const OIDC_BUDGET = {
  sso: 8,
  'sso-faults': 17,
} as const;

export type SsoSpecProject = keyof typeof OIDC_BUDGET;

/** Whether a path on the Mino origin is one the `oidc` throttle counts. */
export function isThrottledOidcPath(pathname: string): boolean {
  return /^\/api\/accounts\/oidc\/(?:exchange|[^/]+\/(?:start|link\/start|callback))\/$/.test(pathname);
}

interface LedgerFile {
  runner: number;
  requests: string[];
}

/** The throttled requests one project's run has made so far, in a file shared by its workers. */
export class OidcLedger {
  readonly project: SsoSpecProject;
  readonly budget: number;
  private readonly file: string;

  constructor(projectName: string, dir: string) {
    if (!(projectName in OIDC_BUDGET)) {
      throw new Error(
        `project '${projectName}' declares no oidc budget: add it to OIDC_BUDGET in tests/sso/budget.ts`
      );
    }
    this.project = projectName as SsoSpecProject;
    this.budget = OIDC_BUDGET[this.project];
    this.file = path.join(dir, `oidc-ledger.${projectName}.json`);
  }

  private read(): LedgerFile {
    // The runner forks every worker, so a worker's parent pid names the invocation.
    const runner = process.ppid;
    try {
      const stored = JSON.parse(fs.readFileSync(this.file, 'utf8')) as LedgerFile;
      if (stored.runner === runner && Array.isArray(stored.requests)) return stored;
    } catch {
      // Absent or unreadable: a fresh run.
    }
    return { runner, requests: [] };
  }

  /** Record one browser request, if it is to a throttled route. */
  observe(url: string, label: string): void {
    const { pathname } = new URL(url);
    if (!isThrottledOidcPath(pathname)) return;
    const ledger = this.read();
    ledger.requests.push(`${label}: ${pathname}`);
    fs.mkdirSync(path.dirname(this.file), { recursive: true });
    fs.writeFileSync(this.file, JSON.stringify(ledger, null, 2));
  }

  /** The run's requests so far. */
  spent(): string[] {
    return this.read().requests;
  }

  /** Throws, listing every request, once the run has spent more than the project declared. */
  assertWithinBudget(): void {
    const spent = this.spent();
    if (spent.length > this.budget) {
      throw new Error(
        `the ${this.project} project has spent ${spent.length} oidc requests this run, over its ` +
          `declared budget of ${this.budget} (OIDC_BUDGET in tests/sso/budget.ts; Mino allows ` +
          `${OIDC_THROTTLE_PER_MINUTE} a minute per client IP). Raise the budget and the numbers ` +
          'the README and spec headers state, within the headroom, or move the spec to a project ' +
          'of its own (e2e/README.md, "The sso project"):\n  ' +
          spent.join('\n  ')
      );
    }
  }
}
