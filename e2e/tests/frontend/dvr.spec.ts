import { test, expect } from '../../fixtures';
import type { Recording } from '../../fixtures';
import { listRows } from '../../setup/http';
import { SURFACES, gotoSurface } from './helpers';

const DVR_SURFACE = SURFACES.find((s) => s.name === 'DVR')!;

/**
 * Move a Mantine DateTimePicker one month forward, pick the 15th, and set an
 * explicit 24-hour `hour:minute`.
 *
 * Why not "today plus two days": `getSingleFormDefaults()`
 * (frontend/src/utils/forms/RecordingUtils.js) defaults start_time to a
 * rounded *now* and end_time to now + 60 min, so a form submitted as rendered
 * schedules a recording that `run_recording` fires immediately — the opposite
 * of what this row wants. Advancing one month and picking the 15th is
 * deterministic whatever today's date is (15 to 46 days out), exists in every
 * month, needs no arithmetic, and cannot land in the past.
 *
 * Both pickers move, because the form validates end_time > start_time.
 *
 * Why the time is set explicitly, not left at the picker's default (as an
 * earlier version of this helper did). `getSingleFormDefaults()`'s end_time
 * is `now + 60min`, which crosses into the next calendar day whenever `now`
 * falls in the last hour before midnight. This helper moves each picker's
 * *date* independently, so on that trigger Start's original time (e.g.
 * 23:xx) and End's original time (already rolled to the next day, e.g. 00:xx)
 * both land on the same target day-of-month, and the leftover 00:xx < 23:xx
 * fails the form's own end-after-start validation — reproduced and confirmed
 * live at 23:13 BST (Start "10:00 PM", End "12:00 AM" *same* date). Setting
 * the time ourselves removes the dependency on the clock entirely: whatever
 * `hour`/`minute` the caller passes is what lands, independent of `now`.
 *
 * Four locators diverge from the plan, all confirmed against the real DOM
 * (headed run, `[data-dates-dropdown]`'s `outerHTML`) rather than assumed:
 *  - The prev/next controls are icon-only `ActionIcon`s with **no accessible
 *    name at all** (no `aria-label`, no text) — `getByRole('button', {name:
 *    /next month/i})` can never match. Use `[data-direction="next"]`.
 *  - A day cell's accessible name is the full date (`aria-label="15 August
 *    2026"`), not the bare visible digit `getByRole('button', {name: '15'})`
 *    looks for — never resolves. Match on `.mantine-DateTimePicker-day`'s
 *    text content instead, excluding `[data-outside]` (adjacent-month
 *    padding days, which the plan's own step 2 flagged as a risk — day 15
 *    is never padding, since padding is confined to the first/last week).
 *  - `DateTimePicker` (unlike a plain `DatePicker`) does not close on a day
 *    click: a time row stays under the calendar and the popover only closes
 *    on its own checkmark `.mantine-DateTimePicker-submitButton` (also
 *    unnamed).
 *  - The time row is a Mantine `TimePicker` in 24-hour mode (`role=spinbutton`
 *    `<input>`s, `aria-valuemax` 23 and 59) despite `Recording.jsx` passing
 *    `timeInputProps={{ format: '12', … }}` — no AM/PM segment renders at
 *    all, confirmed against the live DOM. `.mantine-TimePicker-field`'s
 *    first/second match are the hour/minute inputs respectively; `.fill()`
 *    on each sets the segment directly (confirmed by re-reading the
 *    popover's hidden `value="HH:MM"` input after filling).
 */
async function scheduleNextMonth(
  page: import('@playwright/test').Page,
  fieldLabel: string,
  hour: number,
  minute: number
): Promise<void> {
  await page.getByLabel(fieldLabel, { exact: true }).click();
  const popover = page.locator('[data-dates-dropdown]');
  await popover.waitFor({ state: 'visible' });
  // Both the header's <button> and its inner <svg> icon carry
  // data-direction="next" — scope to the button element itself, or the
  // locator resolves to two elements and click() throws in strict mode.
  await popover.locator('button[data-direction="next"]').click();
  await popover
    .locator('.mantine-DateTimePicker-day:not([data-outside])', { hasText: '15' })
    .click();
  const timeFields = popover.locator('.mantine-TimePicker-field');
  await timeFields.nth(0).click();
  await timeFields.nth(0).fill(String(hour).padStart(2, '0'));
  await timeFields.nth(1).click();
  await timeFields.nth(1).fill(String(minute).padStart(2, '0'));
  await popover.locator('.mantine-DateTimePicker-submitButton').click();
  await popover.waitFor({ state: 'hidden' });
}

test('a recording scheduled from the DVR page exists on the server and can be cancelled', async ({
  adminPage,
  api,
  seed,
  pageErrors,
}) => {
  const channel = await seed.channel();

  // `Recording` has no name field of its own — its identity for lookup
  // purposes is the seeded channel it belongs to, which *is* generated
  // (`seed.channel()`). `find()` below looks it up by `channel.id`, never by
  // a remembered `created.id`, matching this goal's "look the row up by
  // generated name" rule adapted to the one entity in this suite that has
  // none.
  const find = async (): Promise<Recording | undefined> =>
    listRows<Recording>(
      await api.json<unknown>(
        await api.get('/api/channels/recordings/'),
        'list recordings'
      )
    ).find((r) => r.channel === channel.id);

  // Captured rather than thrown immediately: cleanup below must run
  // unconditionally, and a bare `finally` would let an unrelated cleanup
  // failure silently replace a real assertion failure already in flight —
  // same shape as logos.spec.ts / connect.spec.ts.
  let testError: unknown;

  try {
    let created: Recording | undefined;

    await gotoSurface(adminPage, DVR_SURFACE);
    await expect(adminPage.getByTestId('dvr-page')).toBeVisible();

    await adminPage.getByRole('button', { name: 'New Recording' }).click();
    // `getByLabel('Channel')` is ambiguous: Mantine's Select
    // `aria-labelledby`s both the combobox `<input>` and its (initially
    // detached) listbox `<div>` to the same label, so a bare getByLabel
    // resolves to two elements even though there is exactly one visible
    // "Channel" control. Role-scope to the textbox to disambiguate.
    await adminPage.getByRole('textbox', { name: 'Channel', exact: true }).click();
    await adminPage.getByRole('option', { name: new RegExp(channel.name) }).click();

    // Fixed, chosen-by-the-test times on the same date — not the picker's
    // clock-derived defaults. See scheduleNextMonth's doc comment for why.
    await scheduleNextMonth(adminPage, 'Start', 10, 0);
    await scheduleNextMonth(adminPage, 'End', 11, 0);

    await adminPage
      .getByRole('dialog')
      .getByRole('button', { name: /save|create|schedule|submit/i })
      .click();

    // The point of this row is the scheduling round-trip, not the recording:
    // `run_recording` never fires for a window this far out.
    await expect.poll(find, { timeout: 30_000 }).toBeDefined();
    created = (await find())!;

    // The window really is in the future, which is what makes this test safe
    // to run on a shared instance: a recording starting now would spawn
    // ffmpeg.
    expect(new Date(created.start_time).getTime()).toBeGreaterThan(
      Date.now() + 7 * 24 * 60 * 60 * 1000
    );
    expect(new Date(created.end_time).getTime()).toBeGreaterThan(
      new Date(created.start_time).getTime()
    );

    // Listed under "Upcoming Recordings", scoped to this page and identified
    // by the seeded channel's generated name.
    await expect(adminPage.getByTestId('dvr-page').getByText(channel.name)).toBeVisible({
      timeout: 30_000,
    });

    // Cancel from the card, scoped to the one containing this recording's
    // channel name — not `.first()`, which would risk another worker's card.
    //
    // `RecordingCard.jsx`'s cancel/delete control (`SquareX`, ~line 420) is
    // an icon-only `ActionIcon` wrapped only in a Mantine `Tooltip` — no
    // `aria-label`, no visible text, and a `Tooltip` only sets
    // `aria-describedby` on hover, which is not an accessible name. It has
    // **no accessible name by any route**, confirmed by the real
    // accessibility tree captured mid-run (`button [ref=e190]`, no name) —
    // the same defect #65 already tracks for Users/Logos row actions. Filed
    // as a new site on that issue rather than a duplicate (comment, not
    // `test.fail()`: this test doesn't assert the row-action's own
    // behaviour, so it routes around the gap with the icon's lucide class
    // instead of a role/label locator).
    // See https://github.com/D10Scot/Dispatcharr/issues/65.
    const card = adminPage
      .getByTestId('dvr-page')
      .locator('.mantine-Card-root', { hasText: channel.name });
    await card.locator('button:has(svg.lucide-square-x)').click();

    // `handleDeleteClick` (`RecordingCard.jsx:187-198`) branches three ways:
    // a recurring rule opens the recurring-rule editor, a series group opens
    // a separate "Cancel Series" modal (`RecordingCard.jsx:616-639`, its own
    // "Only this upcoming" / "Entire series + rule" buttons), and everything
    // else — this recording, which is neither — sets `deleteConfirmOpen`,
    // opening the confirmation dialog asserted below. Its confirm button
    // reads "Cancel" for an upcoming recording ("Delete" or
    // "Cancel & Delete" are the past-recording/in-progress labels, ~line
    // 592-598). Excluding "Go Back" (the modal's other named button) is not
    // enough on its own: the modal also has an unnamed top-right close
    // `ActionIcon` (`Modal-close`, no text and no "Go Back" substring
    // either) that a bare `hasNotText` filter still matches, resolving to
    // two elements — confirmed by hitting exactly that strict-mode error on
    // a real run. Matching the confirm button's own known text is
    // unambiguous instead of trying to exclude every other button in the
    // dialog.
    await adminPage
      .getByRole('dialog')
      .getByRole('button', { name: /^(cancel|delete|cancel & delete)$/i })
      .click();

    await expect.poll(find, { timeout: 30_000 }).toBeUndefined();
    expect((await api.get(`/api/channels/recordings/${created.id}/`)).status()).toBe(404);

    await pageErrors.expectClean();
  } catch (err) {
    testError = err;
  }

  // Cleanup always runs, whether or not the flow above succeeded, and looks
  // the row up by `channel.id` (never a remembered id) so it works no matter
  // how far the flow got — including the case where the on-page cancel
  // itself is what failed, leaving the recording behind server-side.
  //
  // This isn't just hygiene: a leaked "Custom Recording" here is actively
  // dangerous to every later run, not merely untidy. `categorizeRecordings()`
  // (`frontend/src/utils/pages/DVRUtils.js:63-73`) groups "Upcoming
  // Recordings" by `${program.tvg_id}|${program.title}`, which is `'|'` for
  // *every* ad-hoc recording with no EPG match — so any leaked recording
  // here collapses into the same "Series" card as the next run's fresh one,
  // and `RecordingCard.jsx` renders only the first grouped recording's
  // channel/time, hiding the rest from the DOM entirely. This is exactly how
  // this test failed twice while under development (three leaked debug
  // recordings merged into one card and hid the real assertion target) —
  // filed as https://github.com/D10Scot/Dispatcharr/issues/71. The fix here
  // is this cleanup block, not a workaround in the assertion: it must never
  // leave a recording behind.
  //
  // What a scheduled recording actually creates, beyond the `Recording` row
  // itself (confirmed against source and empirically against this
  // container's DB, not assumed): `schedule_task_on_save`
  // (`apps/channels/signals.py:337-378`) creates a django-celery-beat
  // `ClockedSchedule` at `start_time` and a one-off `PeriodicTask` named
  // `dvr-recording-<id>` running `apps.channels.tasks.run_recording`. A
  // plain `DELETE` on the `Recording` row is enough to remove all three:
  // `revoke_task_on_delete` (`signals.py:389`, a `post_delete` receiver)
  // calls `revoke_task()`, which deletes the `PeriodicTask` and, if no other
  // `PeriodicTask` still references it, the `ClockedSchedule` too
  // (`signals.py:289-310`). No separate cleanup of either is needed — the
  // same `api.delete()` this block already issues covers all three, and is
  // exactly what the on-page cancel button itself triggers
  // (`deleteRecordingById` → `DELETE /api/channels/recordings/<id>/`).
  let leftover: Recording | undefined;
  try {
    leftover = await find();
  } catch (lookupError) {
    if (testError) {
      console.error(
        'dvr.spec.ts: cleanup lookup failed after an in-flight test failure — ' +
          'not overwriting it. Lookup error:',
        lookupError
      );
    } else {
      testError = lookupError;
    }
  }
  if (leftover) {
    if (testError) {
      console.error(
        'dvr.spec.ts: an in-flight test failure preceded cleanup (see below); ' +
          'running cleanup regardless:',
        testError
      );
    }
    const cleanup = await api.delete(`/api/channels/recordings/${leftover.id}/`);
    expect(cleanup.status()).toBe(204);
  }

  if (testError) throw testError;
});
