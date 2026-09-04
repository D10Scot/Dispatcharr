import { test, expect } from '../../fixtures';

/**
 * The XC three-segment root form (`/<user>/<pass>/<channel_id>`) has no
 * distinguishing URL prefix (docs/superpowers/specs/2026-09-04-phase1-
 * process-split-design.md, "The three-segment regex trap", D7). Task 1 of
 * this PR narrows dispatcharr/urls.py's `channel_id` segment to the shape a
 * real Xtream client sends (digits, optionally with an extension), so a
 * same-shaped SPA deep link now falls through to the SPA catch-all instead
 * of stream_xc's 404. This test pins that outcome on the CURRENT
 * single-process shape, before PR 4 gives `/` its own nginx location — a
 * real regression guard, not a test written to match routing that does not
 * exist yet. `/settings/example/page` is three segments, no trailing
 * slash, and its last segment is not numeric, so it cannot collide with a
 * genuine Xtream channel id either before or after Task 1's fix.
 */
test(
  'a three-segment SPA-shaped route still serves the SPA shell, not a 404',
  { tag: '@contract' },
  async ({ request }) => {
    const response = await request.get('/settings/example/page');

    expect(response.status()).toBe(200);
    expect(response.headers()['content-type'] ?? '').toContain('text/html');

    const body = await response.text();
    expect(body).toContain('<div id="root">');
  }
);
