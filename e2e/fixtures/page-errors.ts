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
  readonly failedResponses: { url: string; status: number }[] = [];

  constructor(page: Page) {
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
  }

  /**
   * Fail naming every offender, not counting them. A render check that says
   * "expected 0, got 3" costs the reader a re-run with `--debug`.
   */
  expectClean(): void {
    const offenders = [
      ...this.pageErrors.map((e) => `pageerror: ${e}`),
      ...this.consoleErrors
        .filter((e) => !isAllowed('console', e))
        .map((e) => `console.error: ${e}`),
      ...this.failedResponses
        .filter((r) => !isAllowed('response', r.url))
        .map((r) => `HTTP ${r.status} ${r.url}`),
    ];
    expect(
      offenders,
      'the page produced errors not covered by EXPECTED_PAGE_NOISE. ' +
        'Read the allowlist rule at the top of fixtures/page-errors.ts before ' +
        'adding an entry: a product defect is filed, not allowlisted.'
    ).toEqual([]);
  }
}
