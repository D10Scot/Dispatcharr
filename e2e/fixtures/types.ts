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
 *    server-generated `id`/`uuid`/`created_at`), and then **narrowed further
 *    to what this harness has a use for**. Each `*Overrides` type says what it
 *    left out and why, so a missing field reads as "not needed yet" rather
 *    than "not writable". They can therefore reject a legitimate field; they
 *    cannot admit an invalid one, which is the direction to err in.
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
  /**
   * Stream ids, through `ChannelStream` — **for the default query only**.
   * `ChannelSerializer.to_representation` swaps this for full
   * `StreamSerializer` objects when `include_streams` is in the serializer
   * context, which the viewset sets from `?include_streams=true`. No call this
   * harness makes passes it, so `number[]` is accurate today — but the first
   * test that does will get objects where this promises numbers, with no
   * compile error to warn it. Widen this to a union at that point rather than
   * casting at the call site.
   */
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

/**
 * A `Stream` row. Streams are what a `Channel` points at; the channel is what
 * a client tunes. `is_custom: true` marks a row created by hand rather than
 * ingested from an M3U account — which is what every G4 test wants, because
 * ingesting would test the M3U path (G3) rather than the streaming path.
 */
export type Stream = {
  id: number;
  name: string;
  url: string;
  is_custom: boolean;
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

/**
 * One entry of {@link ChannelStatus}'s `clients` array — one row per client
 * currently reading the channel. Built by hand in
 * `apps/proxy/live_proxy/channel_status.py`
 * (`ChannelStatus.get_detailed_channel_info`), not a DRF serializer, so field
 * names and optionality are read off that function directly rather than off
 * `Meta.fields`: the six required fields are always assigned with a fallback
 * default (`'unknown'`, `'0'`, `'mpegts'`); the rest are only set when the
 * corresponding key exists in the client's Redis hash.
 */
export type ChannelStatusClient = {
  client_id: string;
  user_agent: string;
  worker_id: string;
  ip_address: string;
  user_id: string;
  output_format: string;
  output_profile_id: number | null;
  connected_at?: number;
  last_active?: number;
  last_active_ago?: number;
  bytes_sent?: number;
  avg_rate_KBps?: number;
  current_rate_KBps?: number;
};

/**
 * `GET /proxy/ts/status/<id>` (admin-only) — G4's primary assertion surface.
 * Shape as specified by the G4 task-2 brief. Built by hand in
 * `ChannelStatus.get_detailed_channel_info`, not a DRF serializer: the source
 * defaults `owner` to the string `'unknown'` and `url` to `''` rather than
 * `null` when the channel has never started, and both `total_bytes` and
 * `avg_bitrate_kbps` are only assigned once `uptime` is known — so treat this
 * type as the caller-facing contract, not a byte-for-byte transcription of
 * the Python dict.
 *
 * Two fields are optional rather than nullable, confirmed against the same
 * function: `stream_id`/`stream_name` are assigned only inside the
 * `if stream_id_bytes:` conditional within `get_detailed_channel_info` — with
 * no stream chosen yet the key is simply absent from the JSON, never `null`.
 *
 * `ffmpeg_speed` is a `string`, not a `number`: `get_detailed_channel_info`
 * assigns the raw Redis value with no numeric conversion; `decode_responses=True`
 * on the Redis client makes that a `str` (e.g. `"1.02"`), and the dict goes
 * straight into `JsonResponse` with no serializer to coerce it.
 * `get_basic_channel_info`, the function behind the *bare* `/proxy/ts/status`
 * collection endpoint, does convert via `float(ffmpeg_speed)` — the two
 * functions disagree about this field's type. That is a product inconsistency,
 * not a harness bug; a caller against *this* type must parse the string itself.
 */
export type ChannelStatus = {
  stream_id?: number;
  stream_name?: string;
  url: string | null;
  state: string;
  owner: string | null;
  client_count: number;
  buffer_index: number;
  total_bytes: number;
  avg_bitrate_kbps: number;
  clients: ChannelStatusClient[];
  ffmpeg_speed?: string;
  video_codec?: string;
  resolution?: string;
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

/**
 * The writable fields on `ChannelSerializer` this harness uses, minus the
 * generated `name`. A curated subset, not the complete writable set —
 * `auto_created_by` is omitted, as are the nested `override` and the
 * read-only mirrors noted on {@link Channel}. Add what you need, with
 * evidence; see this file's header.
 */
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
 * The writable fields on `UserSerializer` this harness uses, minus the
 * generated `username`. A curated subset: `is_staff`, `is_superuser`,
 * `avatar_config`, `last_login` and `date_joined` are writable on that
 * serializer and are deliberately not here, because nothing needs them yet
 * and the last two are timestamps no test should be setting by hand.
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

/**
 * The writable fields on `StreamProfileSerializer` this harness uses, minus
 * the generated `name`. `locked` is writable there too and is omitted on
 * purpose: it marks the three built-in profiles, and a seeded profile has no
 * business claiming to be one.
 */
export type StreamProfileOverrides = {
  command?: string;
  parameters?: string;
  is_active?: boolean;
  /** `UserAgent` id. */
  user_agent?: number | null;
};

/**
 * The writable fields on `M3UAccountSerializer` this harness uses, minus the
 * generated `name`. A curated subset: `server_group`, `status`, `exp_date`,
 * `locked` and `updated_at` are writable on that serializer and are not here.
 * The last two only because `read_only_fields` is declared on the serializer
 * class rather than on `Meta`, so DRF ignores it — D10Scot/Dispatcharr#15.
 * Treating them as writable in this contract would encode that bug.
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
 * The writable fields on `EPGSourceSerializer` this harness uses, minus the
 * generated `name`. A curated subset: `status` and `updated_at` are writable
 * there and are not here — `updated_at` only because of the same misplaced
 * `read_only_fields` as above (D10Scot/Dispatcharr#15).
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

/** Omits `name`: the factory owns it. See the ordering note in seed.ts. */
export type StreamOverrides = {
  url?: string;
  is_custom?: boolean;
  channel_group?: number | null;
};

/**
 * Options for {@link Seeder.upstreamChannel}. `channelIds` are the *fake
 * provider's* channel ids, in the order the resulting Channel should try
 * them — so `[1, 2]` makes provider channel 1 the primary and 2 the
 * failover target.
 */
export type UpstreamChannelOptions = {
  channelIds: number[];
  streamProfileId?: number | null;
  // Narrowed: `upstreamChannel()` spreads `...channel` first and then
  // unconditionally assigns its own `streams` and `stream_profile_id`
  // afterwards, so a caller-supplied value for either would be silently
  // discarded. Omitting them here turns that into a compile error instead.
  channel?: Omit<ChannelOverrides, 'streams' | 'stream_profile_id'>;
};

/** `core.UserAgent` via `UserAgentViewSet` (`core/api_urls.py`, `useragents`). */
export type UserAgent = {
  id: number;
  name: string;
  user_agent: string;
  /** `CharField(max_length=255, blank=True)` — no `null=True` (`core/models.py:29`), so DRF emits `""`, never `null`. */
  description: string;
  is_active: boolean;
};

/** `apps.connect.Integration` via `IntegrationViewSet` (`apps/connect/api_urls.py`). */
export type ConnectIntegration = {
  id: number;
  name: string;
  type: string;
  enabled: boolean;
  config: Record<string, unknown>;
  subscriptions: { event: string; enabled: boolean }[];
};

/** `apps.channels.Recording` via `RecordingViewSet` (`apps/channels/api_urls.py`). */
export type Recording = {
  id: number;
  channel: number;
  start_time: string;
  end_time: string;
  custom_properties: Record<string, unknown> | null;
};

/** `apps.channels.Logo` via `LogoViewSet` (`apps/channels/api_urls.py`, `logos`). */
export type Logo = {
  id: number;
  name: string;
  url: string;
};

/**
 * One entry of `{"plugins": [...]}` from `GET /api/plugins/plugins/`
 * (`PluginsListAPIView`, whose body is `PluginManager.list_plugins()`).
 */
export type PluginListEntry = {
  key: string;
  name: string;
  version: string;
  enabled: boolean;
  ever_enabled: boolean;
  settings: Record<string, unknown>;
};

/** One row of `GET /api/backups/` (`apps/backups/services.py`, `list_backups`). */
export type BackupEntry = {
  name: string;
  size: number;
  created: string;
};
