/**
 * The request and response shapes the fixtures traffic in.
 *
 * ---------------------------------------------------------------------------
 * What these are, and what they are not
 * ---------------------------------------------------------------------------
 * These are **not** the DRF serializers. They are the subset of each
 * serializer this harness has actually verified, and nothing else. A type that
 * claims more than it verifies is worse than `unknown`, because the next agent
 * trusts it and writes an assertion against a field that was never there.
 *
 * Every field below was derived one of two ways, never from memory:
 *
 *  - **Response types** — from a live create response against the container
 *    (`POST` to the same URL the factory uses), with nullability read off the
 *    model field or the serializer declaration rather than off the one value
 *    that response happened to carry. So `Channel.channel_number` is
 *    `number | null` because `apps/channels/models.py` declares
 *    `FloatField(null=True)`, even though a create always auto-assigns one.
 *  - **Writable types** — from the serializer's `Meta.fields` minus everything
 *    read-only there (`SerializerMethodField`, `read_only=True`, and the
 *    server-generated `id`/`uuid`/`created_at`).
 *
 * ---------------------------------------------------------------------------
 * If a field you need is missing
 * ---------------------------------------------------------------------------
 * Add it, with the same evidence: find it in the serializer, confirm its
 * nullability in the model, and confirm the live API round-trips it. **Do not
 * reach for a cast.** A cast asserts the field exists; adding it here, having
 * checked, is the same claim made once, in the place the next reader looks.
 *
 * ---------------------------------------------------------------------------
 * The limit of the guarantee
 * ---------------------------------------------------------------------------
 * `seed.channel({ nmae: 'x' })` fails to compile because TypeScript applies
 * excess-property checking to a **fresh object literal**. Assign the same
 * object to a variable first and the check does not fire — that is a
 * TypeScript rule, not a gap in these types, and it is why the runtime
 * enforcement in `seed.ts` (identity fields spread *after* `...overrides`)
 * remains load-bearing. Nothing here validates a payload at runtime, and a
 * body parsed from JSON is not type-checked at all.
 */

/* ------------------------------------------------------------------------ *
 * Responses
 * ------------------------------------------------------------------------ */

/**
 * `/api/channels/channels/`. Fields verified against a live create response;
 * nullability from `apps/channels/models.py` (`Channel`).
 *
 * Not typed here: `override` (a nested upsert with three distinct meanings for
 * a null), `source_stream`, and the eight `effective_*` mirrors. All are
 * `SerializerMethodField`s and none is used by this harness.
 */
export type Channel = {
  id: number;
  name: string;
  /** `FloatField(null=True)`. Auto-assigned on create when omitted. */
  channel_number: number | null;
  uuid: string;
  /** FK `SET_NULL` — null once its group is deleted. */
  channel_group_id: number | null;
  /** Streamer 0 / Standard 1 / Admin 10 — the minimum level that may view. */
  user_level: number;
  /** Stream ids, through `ChannelStream`. */
  streams: number[];
  stream_profile_id: number | null;
  logo_id: number | null;
  epg_data_id: number | null;
  tvg_id: string | null;
  tvc_guide_stationid: string | null;
  is_adult: boolean;
  is_catchup: boolean;
  catchup_days: number;
  hidden_from_output: boolean;
  auto_created: boolean;
};

/**
 * `/api/accounts/users/` and `/api/accounts/users/me/`.
 *
 * `password` is `write_only=True` and is never in a response — it is on
 * {@link UserOverrides} only.
 */
export type User = {
  id: number;
  username: string;
  email: string;
  /** `User.UserLevel`: Streamer 0, Standard 1, Admin 10. */
  user_level: number;
  /** `ChannelProfile` ids this user may see. */
  channel_profiles: number[];
  /** `read_only=True, allow_null=True` on the serializer. */
  api_key: string | null;
  stream_limit: number;
  is_staff: boolean;
  is_superuser: boolean;
};

/**
 * `/api/channels/profiles/` — the *channel* profile. CONTEXT.md's first rule:
 * three different things in this product are called a profile.
 *
 * `channels` is a `SerializerMethodField` (the ids of its enabled
 * memberships), so it is read-only — which is why {@link ChannelProfileOverrides}
 * is empty.
 */
export type ChannelProfile = {
  id: number;
  name: string;
  channels: number[];
};

/** `/api/core/streamprofiles/` — how we talk *upstream*, not the output transcode. */
export type StreamProfile = {
  id: number;
  name: string;
  command: string;
  parameters: string;
  is_active: boolean;
  /** `UserAgent` id. */
  user_agent: number | null;
  /** The three built-in profiles are locked and cannot be deleted or edited. */
  locked: boolean;
};

/** `M3UAccount.Status` (`apps/m3u/models.py`). Note `pending_setup`, which `EpgSourceStatus` has no equivalent of. */
export type M3uAccountStatus =
  | 'idle'
  | 'fetching'
  | 'parsing'
  | 'error'
  | 'success'
  | 'pending_setup'
  | 'disabled';

/**
 * `/api/m3u/accounts/`.
 *
 * Not typed here: `profiles`, `channel_groups`, `filters` and the
 * `earliest_expiration`/`all_expirations` pair — nested shapes no fixture
 * reads. `password` is `write_only=True` but the serializer's
 * `to_representation` re-adds it for `user_level >= 10`, so an admin *does*
 * see it in a response; it is deliberately left off this type rather than
 * inviting a test to assert on a plaintext provider credential.
 */
export type M3uAccount = {
  id: number;
  name: string;
  server_url: string | null;
  file_path: string | null;
  is_active: boolean;
  /** Hours between automatic refreshes; 0 maps to the `(every=1, HOURS)` schedule. */
  refresh_interval: number;
  status: M3uAccountStatus;
  last_message: string | null;
  max_streams: number;
  priority: number;
  stale_stream_days: number;
  account_type: string;
  username: string | null;
  user_agent: number | null;
  locked: boolean;
  created_at: string;
  /** Only bumped on a *successful* refresh — see `Waiter.m3uRefreshComplete`. */
  updated_at: string | null;
  custom_properties: Record<string, unknown> | null;
};

/** `EPGSource.STATUS_CHOICES` (`apps/epg/models.py`). Deliberately not the same set as {@link M3uAccountStatus}. */
export type EpgSourceStatus =
  | 'idle'
  | 'fetching'
  | 'parsing'
  | 'error'
  | 'success'
  | 'disabled';

/** `EPGSource.SOURCE_TYPE_CHOICES`. */
export type EpgSourceType = 'xmltv' | 'schedules_direct' | 'dummy';

/** `/api/epg/sources/`. `password` is `write_only=True` and never in a response. */
export type EpgSource = {
  id: number;
  name: string;
  source_type: EpgSourceType;
  url: string | null;
  username: string | null;
  is_active: boolean;
  file_path: string | null;
  refresh_interval: number;
  status: EpgSourceStatus;
  last_message: string | null;
  priority: number;
  created_at: string;
  updated_at: string | null;
  custom_properties: Record<string, unknown> | null;
  epg_data_count: number;
  has_channels: boolean;
};

/* ------------------------------------------------------------------------ *
 * Seed overrides
 * ------------------------------------------------------------------------ */

/**
 * Every `*Overrides` type below omits the factory's **identity field** —
 * `name`, or `username` for a user.
 *
 * That is not an oversight and not a style choice. `seed.*` spreads the
 * generated identity *after* `...overrides`, so a caller-supplied one is
 * discarded; listing it here would advertise a knob that silently does
 * nothing. The omission and the spread order say the same thing in two
 * places, and neither replaces the other: **the runtime spread is what
 * actually holds**, because a body reaching the factory from `JSON.parse`,
 * from a widened variable, or from any `as` cast was never type-checked.
 * `seed-fixture.spec.ts` pins the runtime behaviour; the `@ts-expect-error`
 * lines in that same file pin these types.
 */

/** Writable fields on `ChannelSerializer`, minus the generated `name`. */
export type ChannelOverrides = {
  channel_number?: number | null;
  channel_group_id?: number;
  epg_data_id?: number | null;
  stream_profile_id?: number | null;
  logo_id?: number | null;
  streams?: number[];
  tvg_id?: string | null;
  tvc_guide_stationid?: string | null;
  user_level?: number;
  is_adult?: boolean;
  is_catchup?: boolean;
  catchup_days?: number;
  hidden_from_output?: boolean;
  auto_created?: boolean;
};

/**
 * Writable fields on `UserSerializer`, minus the generated `username`.
 *
 * `email` and `password` *are* overridable: the factory puts both before
 * `...overrides`, unlike the username. Override `password` and
 * `SEEDED_USER_PASSWORD` no longer describes that user.
 */
export type UserOverrides = {
  email?: string;
  password?: string;
  user_level?: number;
  channel_profiles?: number[];
  custom_properties?: Record<string, unknown>;
  stream_limit?: number;
  first_name?: string;
  last_name?: string;
};

/**
 * `ChannelProfileSerializer` exposes exactly three fields — `id`, `name` and
 * a `SerializerMethodField` `channels` — so once the generated `name` is
 * removed there is nothing left to override. That is the honest type.
 *
 * `Record<string, never>` rather than `{}`: TypeScript applies **no**
 * excess-property check against a bare `{}`, so `Partial<{}>` would let
 * `seed.channelProfile({ nmae: 'x' })` compile — the exact mistake this
 * typing exists to catch. The trade is a blunt error message ("Type 'string'
 * is not assignable to type 'never'"); this comment is what it points at.
 */
export type ChannelProfileOverrides = Record<string, never>;

/** Writable fields on `StreamProfileSerializer`, minus the generated `name`. */
export type StreamProfileOverrides = {
  command?: string;
  parameters?: string;
  is_active?: boolean;
  /** `UserAgent` id. */
  user_agent?: number | null;
};

/**
 * Writable fields on `M3UAccountSerializer`, minus the generated `name`.
 *
 * **`refresh_interval` is load-bearing when accounts are created
 * concurrently.** Two creates racing on the same value both insert an
 * `IntervalSchedule` row for it and brick the container permanently
 * (D10Scot/Dispatcharr#7). `bootstrap` pre-warms the default (`0`, which maps
 * to `every=1`); any *other* value used from parallel tests must be unique
 * per test. See `ws-fixture.spec.ts`.
 *
 * Not typed: `channel_groups`, a nested membership shape no fixture writes.
 */
export type M3uAccountOverrides = {
  server_url?: string | null;
  file_path?: string | null;
  is_active?: boolean;
  refresh_interval?: number;
  cron_expression?: string;
  max_streams?: number;
  priority?: number;
  stale_stream_days?: number;
  account_type?: string;
  username?: string | null;
  password?: string;
  user_agent?: number | null;
  custom_properties?: Record<string, unknown>;
  enable_vod?: boolean;
  auto_enable_new_groups_live?: boolean;
  auto_enable_new_groups_vod?: boolean;
  auto_enable_new_groups_series?: boolean;
};

/**
 * Writable fields on `EPGSourceSerializer`, minus the generated `name`.
 *
 * `refresh_interval` carries the same concurrency hazard as
 * {@link M3uAccountOverrides} — `EPGSource.refresh_interval` lands on the same
 * `IntervalSchedule` table.
 */
export type EpgSourceOverrides = {
  source_type?: EpgSourceType;
  url?: string | null;
  username?: string | null;
  password?: string;
  is_active?: boolean;
  file_path?: string | null;
  refresh_interval?: number;
  cron_expression?: string;
  priority?: number;
  custom_properties?: Record<string, unknown>;
};
