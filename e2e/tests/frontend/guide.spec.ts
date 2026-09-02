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

// Membership timing matters here and is easy to get backwards. Two facts,
// both read off `apps/channels/`, not assumed:
//   - `ChannelProfile`'s `post_save` receiver (`create_profile_memberships`,
//     signals.py) enrols every channel that ALREADY EXISTS at the moment a
//     profile is created — so a channel seeded before `seed.channelProfile()`
//     would land in it regardless of anything this test does.
//   - `ChannelViewSet.create` (api_views.py) enrols a NEW channel in every
//     profile that already exists whenever `channel_profile_ids` is omitted
//     — `seed.channel()`'s default — so a channel seeded after the profile
//     with no override would also land in it.
// Both channels below are therefore seeded AFTER the profile, each with an
// explicit `channel_profile_ids` override that sidesteps both paths:
// `[profile.id]` for the member, `[]` (enrol in nothing) for the one that
// must stay out of it. See `ChannelOverrides.channel_profile_ids` in
// `fixtures/types.ts` for the full evidence trail — `channel-profiles.spec.ts`
// exercises the same receiver from the opposite direction.
test('filtering by Channel Profile narrows the grid to that profile\'s channels', { tag: '@contract' }, async ({
  adminPage,
  pageErrors,
  seed,
}) => {
  const profile = await seed.channelProfile();
  const member = await seed.channel({ channel_profile_ids: [profile.id] });
  const nonMember = await seed.channel({ channel_profile_ids: [] });

  await gotoSurface(adminPage, guideSurface);
  await expect(adminPage).toHaveURL(/\/guide/);

  const grid = adminPage.getByTestId('guide-grid');
  await expect(grid).toBeVisible();

  // Mantine `Select`: a click on the placeholder input opens the option
  // list, which portals to the document body but stays reachable through
  // `getByRole('option', …)` — Task 1's finding, re-used rather than
  // re-derived.
  await adminPage.getByPlaceholder('Filter by profile').click();
  await adminPage.getByRole('option', { name: profile.name, exact: true }).click();

  // The profile filter alone proves the API call was scoped correctly, but
  // this shared instance's other workers keep enrolling their own plain
  // `seed.channel()` calls into every profile that exists when they run
  // (the second fact in the comment above) — so the filtered grid can hold
  // far more than this test's one member row, and the freshly seeded member
  // still has no `channel_number` and is routinely scrolled out of the
  // virtualised window on its own (`guide.spec.ts`'s sibling test, above).
  // Driving the same "Search channels..." box that test uses, on top of the
  // profile filter, narrows to the one row this test actually seeded and
  // proves it is not just off-screen.
  const search = adminPage.getByPlaceholder('Search channels...');
  await search.fill(member.name);
  await expect(
    grid.getByAltText(member.name, { exact: false })
  ).toBeVisible({ timeout: 30_000 });

  const profileSelect = adminPage.getByPlaceholder('Filter by profile');

  // A bare `search.fill(nonMember.name)` followed immediately by
  // `toHaveCount(0)` would pass on its very first check for a reason that
  // has nothing to do with the profile filter: at that instant the grid
  // still renders the *previous* search's result (the member row), so the
  // non-member's count is legitimately zero before the new fetch has even
  // landed — the assertion would hold identically if profile filtering were
  // deleted from the product outright. To anchor the absence on the filter
  // rather than on that timing accident, first prove the non-member row is
  // reachable through search alone, with the profile filter cleared to
  // "All Profiles" (`getProfileOptions` in `guideUtils.js` always injects
  // this option), then re-apply the profile filter and assert the same row
  // disappears. Only the second assertion can fail if filtering is broken;
  // the first proves there was something there for it to filter out.
  await search.fill(nonMember.name);
  await profileSelect.click();
  await adminPage.getByRole('option', { name: 'All Profiles', exact: true }).click();
  await expect(
    grid.getByAltText(nonMember.name, { exact: false })
  ).toBeVisible({ timeout: 30_000 });

  await profileSelect.click();
  await adminPage.getByRole('option', { name: profile.name, exact: true }).click();
  await expect(grid.getByAltText(nonMember.name, { exact: false })).toHaveCount(0);

  await pageErrors.expectClean();
});
