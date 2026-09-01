import { test, expect } from '../../fixtures';
import { SURFACES, gotoSurface } from './helpers';

const guideSurface = SURFACES.find((s) => s.name === 'Guide');
if (!guideSurface) {
  throw new Error('guide.spec.ts: no "Guide" entry in SURFACES — check helpers.ts');
}

// Guide has no write flow — its COVERAGE row is "renders and navigates" — so
// its wiring proof is that the grid is populated from the channel API rather
// than from anything the browser could have invented. `gotoSurface` is what
// exercises the SPA's router wiring at all elsewhere in this project (see its
// own doc comment on #58); it also already absorbs the sidebar's real label —
// "TV Guide", not "Guide" (`frontend/src/config/navigation.js:50` — the
// plan's brief for this test named the wrong string, confirmed by reading
// `Sidebar.jsx`/`navigation.js` directly, not just relying on the brief).
test('the Guide grid is populated from the channel API, reached from the sidebar', { tag: '@contract' }, async ({
  adminPage,
  pageErrors,
  seed,
}) => {
  const channel = await seed.channel();

  await gotoSurface(adminPage, guideSurface);
  await expect(adminPage).toHaveURL(/\/guide/);

  const grid = adminPage.getByTestId('guide-grid');
  await expect(grid).toBeVisible();

  // The grid is react-window-virtualised (`overscanCount={3}` in
  // `Guide.jsx`): a freshly seeded channel has no `channel_number`, sorts to
  // Infinity in `sortChannels`, lands at the very end of whatever else this
  // shared instance holds, and is routinely absent from the DOM entirely —
  // no filter involved, just scrolled out of the virtualised window. Rather
  // than scroll to find it (fragile: row height varies with program count,
  // and a virtualised list's scroll-to-index math is an internal this suite
  // should not depend on), drive the page's own "Search channels..." box — a
  // real user control, not a test shortcut. It both re-fetches
  // server-side (`ChannelViewSet.summary`, `SearchFilter` on `name`) and
  // filters client-side (`filterGuideChannels` in `guideUtils.js`), so
  // typing the seeded name collapses the virtualised list to the one row
  // that matches, which is then guaranteed to be within the viewport.
  //
  // This also answers the plan's Step 3 question empirically instead of
  // needing a debug run to find out: a bare `seed.channel()` — no Channel
  // Profile membership, no group, no EPG data — comes back from the search,
  // so none of Step 3's suspected preconditions are needed for it to be
  // reachable in the Guide.
  await adminPage.getByPlaceholder('Search channels...').fill(channel.name);

  // `channel.name` is never rendered as visible text in a guide row
  // (`GuideRow.jsx`) — it appears only as a Mantine `Tooltip` `label` (mounted
  // in the DOM on hover only, via `openDelay`) and as the channel logo
  // `<img>`'s `alt`. A `getByText(channel.name)` locator — what the plan's
  // Step 1 code used — can match neither and would time out on every run
  // regardless of virtualisation or filtering, which is why this asserts on
  // the image's accessible name instead: it's the one place the API's `name`
  // field actually reaches the DOM.
  await expect(
    grid.getByAltText(channel.name, { exact: false })
  ).toBeVisible({ timeout: 30_000 });

  await pageErrors.expectClean();
});
