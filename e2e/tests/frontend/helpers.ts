/**
 * The nine surfaces G6 covers, and the one way to reach them.
 *
 * `route` is what a test navigates to. Two of them are hash routes rather than
 * router routes: `Settings.jsx` reads `useLocation().hash`, looks the id up in
 * `SETTINGS_GROUPS` (`frontend/src/config/settingsNav.js`) and renders that
 * section inside `<Suspense>`. So `/settings#backups` renders `BackupManager`
 * directly, with no sidebar click — and the Backups "surface" is a Settings
 * section, not a route of its own.
 *
 * `testId` is the container PR A added. It is what a test waits on, and
 * nothing here selects by text: text selectors couple the suite to UI copy.
 */
import { expect } from '@playwright/test';
import type { Page } from '@playwright/test';

export type Surface = {
  /** Matches the `Frontend | …` row in `e2e/COVERAGE.md`. */
  name: string;
  route: string;
  testId: string;
};

export const SURFACES: readonly Surface[] = [
  { name: 'Guide', route: '/guide', testId: 'guide-page' },
  { name: 'DVR', route: '/dvr', testId: 'dvr-page' },
  { name: 'Users', route: '/users', testId: 'users-page' },
  // The bare `/settings` route renders "Select a setting from the sidebar" and
  // reads nothing from the server. The User-Agents section is a real read
  // through a real DRF ModelViewSet, which is what makes it a wiring check.
  { name: 'Settings', route: '/settings#user-agents', testId: 'settings-page' },
  { name: 'Plugins', route: '/plugins', testId: 'plugins-page' },
  { name: 'Stats', route: '/stats', testId: 'stats-page' },
  { name: 'Connect', route: '/connect', testId: 'connect-page' },
  { name: 'Logos', route: '/logos', testId: 'logos-page' },
  // `backups-panel` deliberately breaks the `<surface>-page` naming pattern:
  // Backups is a panel inside Settings, not a route of its own (see the
  // module doc comment above) — don't "fix" this to `backups-page`.
  { name: 'Backups', route: '/settings#backups', testId: 'backups-panel' },
];

// Sidebar link accessible names (`Sidebar.jsx` NavItem → `<Link>`, role
// `link`) for the surfaces reachable by one direct click from `/channels`.
// Keyed by `Surface.name`; falls back to the surface name itself when a
// route's link label matches it verbatim (none currently need the fallback,
// but the two divergences below are exactly why this is a map, not a rule).
const SIDEBAR_LINK_LABEL: Partial<Record<string, string>> = {
  Guide: 'TV Guide',
  Plugins: 'My Plugins',
  Logos: 'Logo Manager',
};

// The two Settings-hash surfaces reach their section via a *button* (see
// below), keyed by the fragment after `#` in `Surface.route`, labelled per
// `frontend/src/config/settingsNav.js`'s `SETTINGS_GROUPS[].sections[].label`.
const SETTINGS_SECTION_LABEL: Record<string, string> = {
  'user-agents': 'User-Agents',
  backups: 'Backup & Restore',
};

/**
 * Navigate and wait for the surface to have actually mounted.
 *
 * `page.goto(route)` alone cannot reach any surface here except `/channels`:
 * `frontend/src/App.jsx:150-183` registers every protected route only inside
 * the `isAuthenticated && isInitialized` branch, so on a fresh page load only
 * `/login` and the catch-all `*` route exist. A direct link matches the
 * catch-all, and its `<Navigate replace>` fires before the async auth check
 * resolves, destroying the originally requested URL and landing on the
 * hardcoded default (`/channels`) instead of the route the test asked for.
 * Filed as https://github.com/D10Scot/Dispatcharr/issues/58. Not patched
 * (rule: never patch `frontend/`).
 *
 * The workaround, proven in Task 3 against a real browser for all twelve PR A
 * ids: `goto('/channels')` — the one route safe to load directly, since it is
 * also the post-login default — and then drive the sidebar exactly as a real
 * user would. That second hop is client-side routing (`react-router`'s
 * `<Link>`/`navigate()`, no full page load), so it never re-enters the
 * `isInitialized` race #58 lives in. **Do not "simplify" this back to
 * `page.goto(surface.route)`** — it would silently make every render check
 * except Guide's first-run assert the Channels page instead of its own
 * surface, and still pass, because `gotoSurface` itself is the only place
 * that would notice.
 *
 * Two click shapes, because `Sidebar.jsx` renders them differently:
 *   - Seven surfaces are one `<Link>` away (role `link`): the accessible name
 *     is the nav item's label, `SIDEBAR_LINK_LABEL[surface.name]` where that
 *     diverges from `surface.name` itself.
 *   - Settings and Backups sit behind the sidebar's "Settings" row, which has
 *     no `to` — it's an `onClick` that opens a secondary sliding panel
 *     (`Sidebar.jsx`'s `SettingsPanelRow`) — and the section row inside that
 *     panel is *also* an `onClick`-only row (`navigate()` in a handler, not a
 *     `<Link>`). Both are role `button`, not `link`.
 *
 * `waitForLoadState('networkidle')` is deliberately NOT used: the Stats page
 * polls on an interval and the WebSocket consumer reconnects, so this app
 * never reaches network idle and the wait would burn the whole test timeout.
 * The test id becoming visible is the honest barrier.
 */
export async function gotoSurface(page: Page, surface: Surface): Promise<void> {
  await page.goto('/channels');

  const hashMatch = surface.route.match(/^\/settings#(.+)$/);
  if (hashMatch) {
    const sectionLabel = SETTINGS_SECTION_LABEL[hashMatch[1]];
    if (!sectionLabel) {
      throw new Error(
        `gotoSurface: no sidebar section label registered for "${surface.route}" — ` +
          'add one to SETTINGS_SECTION_LABEL in helpers.ts.'
      );
    }
    await page.getByRole('button', { name: 'Settings', exact: true }).click();
    await page.getByRole('button', { name: sectionLabel, exact: true }).click();
  } else {
    const linkLabel = SIDEBAR_LINK_LABEL[surface.name] ?? surface.name;
    await page.getByRole('link', { name: linkLabel, exact: true }).click();
  }

  await expect(page.getByTestId(surface.testId)).toBeVisible();
}
