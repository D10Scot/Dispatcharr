import { test, expect } from '../../fixtures';
import type { ChannelProfile } from '../../fixtures';

/**
 * `ChannelProfile` is the authorization grouping — not a Stream Profile (how
 * we talk upstream) and not an Output Profile (a downstream transcode). See
 * the root CONTEXT.md.
 *
 * Two facts shape every assertion here. `create_profile_memberships`, a
 * post_save receiver on ChannelProfile, bulk-creates a membership for EVERY
 * existing Channel the moment a profile is created, at
 * `ChannelProfileMembership.enabled`'s `True` default — so a fresh profile
 * already contains the whole instance, and `profile.channels` is a global
 * list. Enrolment in the other direction is done by a view, not a receiver:
 * `ChannelViewSet.create` (`apps/channels/api_views.py:873-880`) adds a new
 * channel to EVERY existing profile when `channel_profile_ids` is omitted,
 * which `seed.channel()` always omits. So a channel seeded after a profile
 * is in it too, and other workers' channels keep arriving in this profile
 * for the length of the run — which is the second reason nothing here may
 * assert on a length; every membership assertion below is toContain /
 * not.toContain.
 */
test('toggling one channel’s membership flips its enabled flag', { tag: '@contract' }, async ({
  seed,
  api,
}) => {
  // Seeded before the profile: the post_save receiver is what enrols it.
  const channel = await seed.channel();
  const profile = await seed.channelProfile();
  expect(profile.channels).toContain(channel.id);

  // A second profile, created after `channel` exists, is enrolled by the
  // same receiver. It must stay untouched by everything done to `profile`
  // below — proving the toggle is scoped to the profile in the URL, not to
  // the channel across every profile that contains it.
  const otherProfile = await seed.channelProfile();
  expect(otherProfile.channels).toContain(channel.id);

  const disabled = await api.patch(
    `/api/channels/profiles/${profile.id}/channels/${channel.id}/`,
    { enabled: false }
  );
  expect(disabled.status()).toBe(200);
  const disabledBody = await api.json<{ channel: number; enabled: boolean }>(
    disabled,
    'membership PATCH response'
  );
  expect(disabledBody.channel).toBe(channel.id);
  expect(disabledBody.enabled).toBe(false);

  // `ChannelProfileSerializer.channels` lists the ids of ENABLED memberships,
  // so one read proves both directions of the toggle.
  const afterDisable = await api.json<ChannelProfile>(
    await api.get(`/api/channels/profiles/${profile.id}/`),
    'profile read-back after disabling'
  );
  expect(afterDisable.channels).not.toContain(channel.id);

  const otherAfterDisable = await api.json<ChannelProfile>(
    await api.get(`/api/channels/profiles/${otherProfile.id}/`),
    'other profile read-back after disabling'
  );
  expect(otherAfterDisable.channels).toContain(channel.id);

  const reEnabled = await api.patch(
    `/api/channels/profiles/${profile.id}/channels/${channel.id}/`,
    { enabled: true }
  );
  expect(reEnabled.status()).toBe(200);

  const afterEnable = await api.json<ChannelProfile>(
    await api.get(`/api/channels/profiles/${profile.id}/`),
    'profile read-back after re-enabling'
  );
  expect(afterEnable.channels).toContain(channel.id);
});

test('bulk-update sets several memberships in one call', { tag: '@contract' }, async ({ seed, api }) => {
  const stays = await seed.channel();
  const goes = await seed.channel();
  const profile = await seed.channelProfile();
  expect(profile.channels).toContain(stays.id);
  expect(profile.channels).toContain(goes.id);

  // A second profile, enrolled in both channels by the same receiver, must
  // stay untouched by the bulk-update below — proving the write is scoped
  // to the profile in the URL, not to the channels across every profile
  // that contains them.
  const otherProfile = await seed.channelProfile();
  expect(otherProfile.channels).toContain(stays.id);
  expect(otherProfile.channels).toContain(goes.id);

  // PATCH, not POST, and the body is `{ channels: [...] }` — not a bare list.
  const res = await api.patch(
    `/api/channels/profiles/${profile.id}/channels/bulk-update/`,
    {
      channels: [
        { channel_id: stays.id, enabled: true },
        { channel_id: goes.id, enabled: false },
      ],
    }
  );
  expect(res.status()).toBe(200);
  const body = await api.json<{
    status: string;
    updated: number;
    created: number;
    invalid_channels: number[];
  }>(res, 'bulk-update response');
  expect(body.status).toBe('success');
  expect(body.invalid_channels).toEqual([]);
  // Split rather than summed: this proves the pre-enrolment the receiver
  // guarantees — both memberships already existed, so nothing is created.
  expect(body.updated).toBe(2);
  expect(body.created).toBe(0);

  const readBack = await api.json<ChannelProfile>(
    await api.get(`/api/channels/profiles/${profile.id}/`),
    'profile read-back after bulk-update'
  );
  expect(readBack.channels).toContain(stays.id);
  expect(readBack.channels).not.toContain(goes.id);

  const otherAfterBulkUpdate = await api.json<ChannelProfile>(
    await api.get(`/api/channels/profiles/${otherProfile.id}/`),
    'other profile read-back after bulk-update'
  );
  expect(otherAfterBulkUpdate.channels).toContain(stays.id);
  expect(otherAfterBulkUpdate.channels).toContain(goes.id);
});
