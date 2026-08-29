/**
 * The render check's evidence, and the one place the noise allowlist lives.
 *
 * Three channels, because the product routes failures to all three and no one
 * of them is sufficient:
 *
 *  - `pageerror`      — an uncaught exception, and (in Chromium) an unhandled
 *                       promise rejection, which is what an awaited `api.js`
 *                       call that throws inside a React handler produces.
 *  - `console.error`  — React's own warnings and the app's explicit
 *                       `console.error` calls. Filtered to `type() === 'error'`
 *                       on purpose: `Connect.jsx` and `Stats.jsx` both carry a
 *                       plain `console.log`, and neither is a defect.
 *  - responses >= 400 — the only channel that sees a rejected write reliably.
 *                       `api.js`'s `errorNotification` catches, toasts and
 *                       rethrows, so whether the rejection reaches `pageerror`
 *                       depends on the call site's error handling. The response
 *                       does not.
 *
 * THE ALLOWLIST RULE. `EXPECTED_PAGE_NOISE` starts empty and grows only under
 * review. Each entry names an exact URL path or an exact message prefix —
 * never a bare substring like `/api/` — and carries a `reason` that says why
 * the noise is not a defect. **"This is a known product bug" is not an
 * admissible reason.** Roadmap rule 5 applies: assert the correct behaviour,
 * mark the test `test.fail()` naming the defect, and file it with
 * `gh issue create --repo D10Scot/Dispatcharr`. An allowlist that absorbs bugs
 * stops being a check and becomes a comment.
 */
import { expect } from '@playwright/test';
import type { Page } from '@playwright/test';

export type PageNoiseEntry = {
  /** Exact URL path (for `response`) or exact message prefix (for `console`). */
  match: string;
  kind: 'console' | 'response';
  /** Why this is not a defect. Reviewed individually. */
  reason: string;
};

/**
 * Deliberately empty. Task 5 runs the render checks against a real container
 * and fills this in from what it actually observes, justifying each entry.
 * Nothing goes in here speculatively.
 */
export const EXPECTED_PAGE_NOISE: readonly PageNoiseEntry[] = [];

function isAllowed(kind: PageNoiseEntry['kind'], value: string): boolean {
  return EXPECTED_PAGE_NOISE.some(
    (entry) => entry.kind === kind && value.startsWith(entry.match)
  );
}

export class PageErrorCollector {
  readonly consoleErrors: string[] = [];
  readonly pageErrors: string[] = [];
  readonly failedResponses: { url: string; status: number; failureText?: string }[] = [];

  private readonly page: Page;

  /**
   * Set by {@link waiveAutomaticCheck}. `fixtures/index.ts`'s `pageErrors`
   * fixture calls `expectClean()` for every test at teardown unless this is
   * set — see that fixture for why the check is opt-out, not opt-in.
   */
  private waivedReason: string | null = null;

  constructor(page: Page) {
    this.page = page;
    page.on('console', (message) => {
      if (message.type() === 'error') this.consoleErrors.push(message.text());
    });
    page.on('pageerror', (error) => {
      this.pageErrors.push(`${error.name}: ${error.message}`);
    });
    page.on('response', (response) => {
      if (response.status() >= 400) {
        this.failedResponses.push({
          url: new URL(response.url()).pathname,
          status: response.status(),
        });
      }
    });
    // `response` only fires for a request that got an HTTP response at all.
    // A network-level failure — connection refused, DNS failure, blocked by
    // the page — never does, so without this handler those are structurally
    // invisible to `expectClean()`.
    page.on('requestfailed', (request) => {
      const failure = request.failure();
      // `net::ERR_ABORTED` fires for any in-flight request cancelled by a
      // navigation (including this fixture's own goto()s) or by the page
      // closing. That is a normal browser artifact, not a product signal —
      // every other reason (refused connection, DNS failure, blocked
      // request) is real and gets recorded.
      if (failure?.errorText === 'net::ERR_ABORTED') return;
      this.failedResponses.push({
        url: new URL(request.url()).pathname,
        status: 0,
        failureText: failure?.errorText,
      });
    });
  }

  /**
   * Opt out of the automatic `expectClean()` teardown check that
   * `fixtures/index.ts`'s `pageErrors` fixture runs for every test. For a
   * test that deliberately provokes an error to exercise the product's own
   * handling of it (a defect this fixture would otherwise fail on before the
   * test gets to make its own assertion). `reason` is mandatory and sits at
   * the call site, so a reader scanning the spec sees which tests waive the
   * check and why — never a bare boolean that reads as "trust me."
   */
  waiveAutomaticCheck(reason: string): void {
    this.waivedReason = reason;
  }

  /** Read by the `pageErrors` fixture's teardown. Not for spec use. */
  get isWaived(): boolean {
    return this.waivedReason !== null;
  }

  /**
   * Fail naming every offender, not counting them. A render check that says
   * "expected 0, got 3" costs the reader a re-run with `--debug`.
   *
   * `console`, `pageerror` and `response`/`requestfailed` are delivered over
   * CDP asynchronously, so an error triggered by the test's last action may
   * not have reached these listeners yet at the instant this is called — the
   * `setTimeout`-deferred throw in this fixture's own scaffold test needed
   * `expect.poll` for exactly that reason. Awaiting a matching macrotask
   * round-trip through the page below flushes anything already queued ahead
   * of it, including a same-tick `setTimeout(fn, 0)`. It cannot wait for an
   * error that has not happened yet — e.g. one raised by a network request
   * the caller never awaited. Call this after the page has reached the state
   * the test is actually asserting (its own `toBeVisible()` etc.), not
   * immediately after firing an action, and it needs nothing further.
   */
  async expectClean(): Promise<void> {
    await this.page
      .evaluate(() => new Promise((resolve) => setTimeout(resolve, 0)))
      .catch(() => {
        // The page navigated away or closed between the caller's last
        // action and this call — nothing left to flush, and the arrays
        // already hold everything that was observed before that happened.
      });

    const offenders = [
      ...this.pageErrors.map((e) => `pageerror: ${e}`),
      ...this.consoleErrors
        .filter((e) => !isAllowed('console', e))
        .map((e) => `console.error: ${e}`),
      ...this.failedResponses
        .filter((r) => !isAllowed('response', r.url))
        .map((r) =>
          r.status === 0
            ? `network failure: ${r.url}${r.failureText ? ` (${r.failureText})` : ''}`
            : `HTTP ${r.status} ${r.url}`
        ),
    ];
    expect(
      offenders,
      'the page produced errors not covered by EXPECTED_PAGE_NOISE. ' +
        'Read the allowlist rule at the top of fixtures/page-errors.ts before ' +
        'adding an entry: a product defect is filed, not allowlisted.'
    ).toEqual([]);
  }
}
