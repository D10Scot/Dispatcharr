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

/**
 * A user who can authenticate against the Xtream Codes surface.
 *
 * **The XC username is the Django username.** There is no `xc_username`
 * custom property anywhere in the product: `xc_get_user`
 * (`apps/output/views.py`), `stream_xc` (`apps/proxy/live_proxy/views.py`)
 * and `_authenticate_user` (`apps/timeshift/views.py`) all look the user up
 * by `username` and then compare `custom_properties["xc_password"]` with
 * `!=`. The `xc_username` locals in `apps/timeshift/views.py` are *provider*
 * credentials from `get_transformed_credentials` and are unrelated.
 *
 * `xcPassword` is carried here rather than read back from the API because
 * `UserSerializer` does not return `custom_properties`.
 */
export type XcUser = User & { xcPassword: string };

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
 * ingested from an M3U account.
 *
 * Fields from `StreamSerializer.Meta.fields`; nullability from
 * `apps/channels/models.py` (`Stream`). Not typed here: `local_file`,
 * `current_viewers`, `updated_at`, `is_adult`, `stream_profile_id`,
 * `stream_hash`, `stream_stats`, `stream_stats_updated_at`, `stream_id` —
 * writable or readable, but nothing needs them.
 */
export type Stream = {
  id: number;
  name: string;
  url: string;
  is_custom: boolean;
  /** FK `CASCADE`, `null=True` — null on a hand-created (`is_custom`) row. */
  m3u_account: number | null;
  /** The playlist's `tvg-logo`. `TextField(blank=True, null=True)`. */
  logo_url: string | null;
  /** The playlist's `tvg-id`. `CharField(blank=True, null=True)`. */
  tvg_id: string | null;
  /** FK `SET_NULL` to `ChannelGroup`, set from `group-title` on refresh. */
  channel_group: number | null;
  /** `DateTimeField(default=timezone.now)` — never null. */
  last_seen: string;
  is_stale: boolean;
  /** The playlist's `tvg-chno`. `FloatField(null=True)`; the fake provider declares none. */
  stream_chno: number | null;
  /**
   * `Stream.is_catchup`, rolled up onto `Channel.is_catchup` by
   * `rollup_channel_catchup_fields` (`apps/m3u/tasks.py:1963-2014`) and by the
   * `ChannelStream` signal `update_channel_catchup_fields`
   * (`apps/channels/signals.py:393-407`). Set on XC ingest from the
   * provider's `tv_archive`, compared as `str(...) in ("1", "True")`
   * (`apps/m3u/tasks.py:1164-1165`), and on the standard-M3U path from the
   * same-named `#EXTINF` attribute (`:1383-1384`).
   */
  is_catchup: boolean;
  /**
   * `Stream.catchup_days`, from the provider's `tv_archive_duration` via
   * `int(... or 0)` (`apps/m3u/tasks.py:1167`). The fake provider declares
   * `7` for every catch-up channel (`DEFAULT_ARCHIVE_DAYS`,
   * `e2e-upstream/src/xc/catalogue.ts`), so `7` is the expected value
   * throughout G10 — and `0` when `no-tv-archive` is armed, because the
   * fields are then omitted from the catalogue entirely rather than sent as
   * zero.
   */
  catchup_days: number;
};

/**
 * `GET /api/channels/streams/`. `StreamPagination` is unconditional on this
 * endpoint (page_size 50, `page_size` query param, max 10000), so the list
 * form is always this envelope and never a bare array.
 */
export type StreamPage = {
  count: number;
  next: string | null;
  previous: string | null;
  results: Stream[];
};

/**
 * `/api/channels/groups/`. `ChannelGroup` has exactly one model field, `name`
 * (`TextField(unique=True)`). `ChannelGroupSerializer` adds three read-only
 * mirrors (`channel_count`, `m3u_account_count`, `m3u_accounts`) that nothing
 * here reads. The endpoint has no filterset and no pagination, so it returns a
 * bare array of every group in the instance — assert membership, never length.
 */
export type ChannelGroup = {
  id: number;
  name: string;
};

/**
 * `apps.channels.Logo` via `LogoViewSet` (`apps/channels/api_urls.py`,
 * `logos`). `LogoSerializer.Meta.fields` also has `channel_names`; not typed
 * here because nothing reads it yet.
 *
 * `url` is **not** necessarily an HTTP-fetchable location: for a logo
 * created through `LogoViewSet.upload` it is the raw server-side filesystem
 * path (`/data/logos/<name>`, from `core.utils.safe_upload_path`). No URL
 * pattern in `dispatcharr/urls.py` actually serves `/data/logos/*` — but a
 * `GET` against it does not 404 cleanly either. `dispatcharr/urls.py`
 * registers the XC live-stream route,
 * `<str:username>/<str:password>/<str:channel_id>`, ahead of the SPA
 * catch-all, and `/data/logos/<file>` happens to have exactly three path
 * segments, so it parses as `username="data", password="logos",
 * channel_id="<file>"` and 404s from `stream_xc`'s own "no such user"
 * lookup (`{"detail":"No User matches the given query."}`) — confirmed
 * empirically against a running container by `logos.spec.ts`, not assumed.
 * A bare status check against `url` proves nothing either way about whether
 * the upload actually landed; `cache_url` is the field that is always
 * fetchable: `LogoSerializer.get_cache_url` builds an absolute URL to
 * `LogoViewSet.cache` (`AllowAny`, streams the real file via
 * `core.image_proxy.serve_local_or_remote_image`) off the *request's own
 * host*, so it resolves against this harness's `baseURL` whether the logo
 * is a local upload or a remote URL.
 *
 * `url`'s local-path/remote-URL duality also has no discriminator field —
 * every consumer (`apps/output/views.py:290`'s `tvg-logo`, the XC
 * `stream_icon` field, `LogosTable.jsx`'s URL column) tells them apart with
 * its own copy-pasted `startsWith('http')`/`startsWith(('http://',
 * 'https://'))` check. All four currently agree, so this is not a filed
 * defect, but it is the same shape as the eight-site channel-authorization
 * filter in the root `CLAUDE.md`'s defect list, where one of the eight
 * copies was wrong — and a fifth site that forgets the check here would not
 * fail cleanly, it would land in the XC-route 404 above and send whoever
 * debugs it looking in the wrong subsystem entirely.
 */
export type Logo = {
  id: number;
  name: string;
  url: string;
  cache_url: string;
  channel_count: number;
  is_used: boolean;
};

/**
 * Options for {@link Seeder.logo}. There is no `name` here for the usual
 * reason — the factory generates it — and no `url` either: an upload derives
 * `url` from the filename it wrote, so passing one would do nothing.
 */
export type LogoOverrides = {
  /** Must be one of `validate_logo_file`'s allowed types. Default `image/png`. */
  mimeType?: string;
  /** The generated filename's extension, without the dot. Default `png`. */
  extension?: string;
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
 * Not typed here: `channel_groups`, `filters` and the
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
  /**
   * `M3UAccountProfileSerializer(many=True, read_only=True)` on
   * `M3UAccountSerializer` — nested and read-only, never created directly by
   * this harness. See {@link M3uAccountProfile}.
   */
  profiles: M3uAccountProfile[];
};

/**
 * One entry of {@link M3uAccount.profiles} — `M3UAccountProfileSerializer`
 * (`apps/m3u/serializers.py`), nested read-only on `M3UAccountSerializer`.
 * `id` and `account` are `read_only_fields`; the rest are writable on the
 * profile's own (untyped here) endpoint, not through this nested view.
 * Nullability: `custom_properties` and `exp_date` from
 * `apps/m3u/models.py`'s `M3UAccountProfile` (`JSONField(null=True)`,
 * `DateTimeField(null=True)`); the rest are non-null model fields with
 * defaults.
 */
export type M3uAccountProfile = {
  id: number;
  name: string;
  max_streams: number;
  is_active: boolean;
  is_default: boolean;
  current_viewers: number;
  search_pattern: string;
  replace_pattern: string;
  custom_properties: Record<string, unknown> | null;
  exp_date: string | null;
  /** `SerializerMethodField` — a fixed-shape summary of the parent account. */
  account: {
    id: number;
    name: string;
    account_type: string;
    is_xtream_codes: boolean;
  };
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
 * `/api/epg/epgdata/` — one row per `<channel>` in an XMLTV document, created
 * by `parse_channels_only`. Fields from `EPGDataSerializer.Meta.fields`;
 * nullability from `apps/epg/models.py` (`EPGData`), whose `epg_source` is a
 * `null=True` FK and whose `icon_url` is `blank=True, null=True`.
 *
 * `EPGDataViewSet` declares no filterset and no pagination, so a GET returns
 * a bare array of **every** row in the instance. Filter it client-side on
 * `tvg_id`, and never assert its length.
 */
export type EpgData = {
  id: number;
  tvg_id: string;
  name: string;
  icon_url: string | null;
  epg_source: number | null;
};

/** One row of {@link ProgramSearchPage}, from `ProgramSearchResultSerializer`. */
export type ProgramSearchResult = {
  id: number;
  title: string;
  start_time: string;
  end_time: string;
  tvg_id: string | null;
  /** The Channels reached through `EPGData.channels` (the reverse of `Channel.epg_data`). */
  channels: { id: number; name: string; channel_number: number | null; tvg_id: string | null }[];
};

/**
 * `GET /api/epg/programs/search/`. Paginated by `ProgramSearchPagination`
 * (page_size 50, `page_size` param, max 500). With `?channel_id=<id>` the
 * filter is `Q(epg__channels__id=<id>)`, so `count` is scoped to one channel
 * and is a legitimate thing to assert on.
 */
export type ProgramSearchPage = {
  count: number;
  next: string | null;
  previous: string | null;
  results: ProgramSearchResult[];
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
 * Fake upstream provider — XC catalogue
 * ------------------------------------------------------------------------ *
 * The five types below are not derived from a Dispatcharr serializer — their
 * consumer is the fake upstream provider itself. Each mirrors the
 * like-named `*Spec` type declared and validated in `e2e-upstream/src/
 * scenario.ts` (G8 task 1), field for field, so an `UpstreamScenario`'s
 * catalogue echo and a `ScenarioRequest`'s catalogue declaration can share
 * one shape. Consult that file, not a Dispatcharr model, if a field here
 * looks wrong.
 * ------------------------------------------------------------------------ */

/** Mirrors `CategorySpec`. A live channel group, VOD category or series category declared on a scenario — never call it a "profile" (CONTEXT.md). */
export type UpstreamCategory = {
  id: number;
  name: string;
};

/** Mirrors `MovieSpec`. One VOD movie declared on an XC scenario. */
export type UpstreamMovie = {
  id: number;
  name: string;
  year: number | null;
  /** Mirrors `MovieSpec.categoryId` — `null` emits no `category_id` key at all. */
  categoryId: number | null;
  containerExtension: string;
  tmdbId: string | null;
  imdbId: string | null;
  /** Mirrors `MovieSpec.isAdult`. */
  isAdult?: boolean;
  /** Mirrors `MovieSpec.vodInfo`. */
  vodInfo?: Record<string, unknown>;
};

/** Mirrors `EpisodeSpec`. One episode within an {@link UpstreamSeason}. */
export type UpstreamEpisode = {
  id: number;
  title: string;
  episodeNum: number;
  containerExtension: string;
};

/** Mirrors `SeasonSpec`. One season within an {@link UpstreamSeries}. */
export type UpstreamSeason = {
  number: number;
  episodes: UpstreamEpisode[];
};

/** Mirrors `SeriesSpec`. One VOD series declared on an XC scenario. */
export type UpstreamSeries = {
  id: number;
  name: string;
  categoryId: number;
  seasons: UpstreamSeason[];
  /** Mirrors `SeriesSpec.seasonsAsArray`. */
  seasonsAsArray?: boolean;
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
 * generated `name` — plus `channel_profile_ids`, which is not a serializer
 * field at all (see its own doc comment below). A curated subset, not the
 * complete writable set — `auto_created_by` is omitted, as are the nested
 * `override` and the read-only mirrors noted on {@link Channel}. Add what
 * you need, with evidence; see this file's header.
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
  /**
   * Not a `ChannelSerializer` field — `ChannelViewSet.create`
   * (apps/channels/api_views.py) reads it straight off `request.data` after
   * `serializer.is_valid()`; the serializer itself ignores unknown keys in
   * `data`, since `.is_valid()` only pulls the fields it declares, so this
   * one reaches the view unvalidated. Controls which
   * `ChannelProfile`s the new channel is enrolled in at creation: omitted
   * (`seed.channel()`'s default) enrols it in every profile that exists at
   * that moment, `[]` enrols it in none, and an explicit id list enrols it
   * in exactly those ids. `guide.spec.ts`'s profile-filter test uses `[]` to
   * seed a channel that is provably absent from a fresh profile, despite
   * that profile's own `post_save` receiver (`create_profile_memberships`,
   * apps/channels/signals.py) enrolling every channel that already existed
   * when the profile itself was created.
   */
  channel_profile_ids?: number[];
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
 * `ChannelGroupSerializer` exposes `id`, `name` and three read-only fields
 * (`channel_count`, `m3u_account_count`, `m3u_accounts` — see
 * {@link ChannelGroup}'s doc comment), so once the generated `name` is
 * removed there is nothing left to override — exactly the shape
 * {@link ChannelProfileOverrides} has, and `Record<string, never>` for the
 * same reason: TypeScript applies no excess-property check against a bare
 * `{}`.
 */
export type ChannelGroupOverrides = Record<string, never>;

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
 * One entry of `M3UAccountSerializer.channel_groups`, which is
 * `ChannelGroupM3UAccountSerializer(source="channel_group", many=True)`.
 * `channel_group` is the `ChannelGroup`'s primary key. Reading it from
 * `GET /api/m3u/accounts/<id>/` is account-scoped, which is why it is
 * preferred over the global `/api/channels/groups/` list.
 *
 * `auto_sync_channel_start`/`_end` are `FloatField(null=True, blank=True)` on
 * `ChannelGroupM3UAccount`.
 */
export type M3uAccountChannelGroup = {
  channel_group: number;
  enabled: boolean;
  auto_channel_sync: boolean;
  auto_sync_channel_start: number | null;
  auto_sync_channel_end: number | null;
  is_stale: boolean;
  stream_count: number;
};

/**
 * One row of the `group_settings` array in the body of
 * `PATCH /api/m3u/accounts/<id>/group-settings/`
 * (`M3UAccountViewSet.update_group_settings`).
 *
 * **Every field is required on every call.** That action does not use a
 * serializer: it reads raw `request.data` and issues a
 * `bulk_create(update_conflicts=True, update_fields=[...])`, so an omitted
 * field is written as its zero value — omitting `custom_properties` writes
 * `{}`, omitting `auto_channel_sync` writes `false`, omitting `enabled` writes
 * `true`. This is also the ONLY route that writes `auto_channel_sync`:
 * `M3UAccountSerializer.update` pops the nested `channel_groups` payload and
 * applies `enabled` alone, silently discarding the rest.
 */
export type GroupSettingRow = {
  /** The `ChannelGroup`'s id. Rows without it are silently skipped. */
  channel_group: number;
  enabled: boolean;
  auto_channel_sync: boolean;
  /** Validated `>= 1` by the view, and `end >= start`. */
  auto_sync_channel_start: number;
  auto_sync_channel_end: number;
  custom_properties: Record<string, unknown>;
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

/* ------------------------------------------------------------------------ *
 * Parsed client-output surfaces (M3U playlist, XMLTV guide)
 * ------------------------------------------------------------------------ */

/** One `#EXTINF` line plus the URL beneath it. */
export type M3uEntry = {
  /**
   * The quoted `key="value"` attributes on the `#EXTINF` line. Dispatcharr
   * emits `tvg-id`, `tvg-name`, `tvg-logo`, `tvg-chno`, optionally
   * `tvc-guide-stationid`, and `group-title` — and nothing else. No `catchup=`
   * family attribute is emitted, so the XC `tv_archive` field is currently the
   * only surface on which Dispatcharr advertises catch-up. Whether that is
   * intended or an omission is open: it reads the same attributes on ingest
   * (`apps/m3u/tasks.py:1383-1388`) but never writes them, and there are three
   * incompatible M3U conventions to choose between. Filed as #94 and pinned by
   * `e2e/tests/seeded/catchup-m3u-advertisement.spec.ts`.
   */
  attributes: Record<string, string>;
  /** Everything after the comma that ends the attribute list. */
  title: string;
  url: string;
  /**
   * False when the `#EXTINF` line's attribute region did not end cleanly at
   * the title comma — i.e. the reader stopped on something that is neither
   * another `key="value"` pair nor the comma, so text spilled out of a
   * quoted value.
   *
   * The one thing that produces this against Dispatcharr today is a channel
   * or group name containing a `"`, which `apps/output/views.py:306-308`
   * interpolates unescaped (D10Scot/Dispatcharr#80). `attributes` and
   * `title` are then both unreliable for that entry, and this flag is how a
   * test says so rather than asserting on the wreckage.
   */
  wellFormed: boolean;
};

export type M3uPlaylist = {
  /** Attributes on the `#EXTM3U` line: `x-tvg-url` and `url-tvg`. */
  header: Record<string, string>;
  entries: M3uEntry[];
};

export type XmltvChannel = { id: string; displayNames: string[] };

/** `start`/`stop` are XMLTV timestamps, e.g. `20260829120000 +0000`. */
export type XmltvProgramme = {
  channel: string;
  start: string;
  stop: string;
  title: string;
};

export type XmltvDocument = {
  channels: XmltvChannel[];
  programmes: XmltvProgramme[];
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

/**
 * `VODLogoSerializer`; the model is `apps/vod/models.py` `VODLogo` (`name`,
 * unique `url`). `Meta.fields` is all eight below — the five after `url` are
 * `SerializerMethodField`s, so they are read-only and always present.
 * `item_names` is capped at ten movies plus ten series.
 */
export type VodLogo = {
  id: number;
  name: string;
  url: string;
  /** `vodlogo_cache_url()` (`apps/vod/image_proxy.py`) returns `-> str`, falling back to `""` for a falsy logo — never `null`. */
  cache_url: string;
  movie_count: number;
  series_count: number;
  is_used: boolean;
  item_names: string[];
};

/**
 * The `quality_info` method field on both `M3UMovieRelationSerializer` and
 * `M3UEpisodeRelationSerializer`. It returns `None` — hence `null` — when it
 * can derive nothing, and otherwise a dict carrying one or more of `quality`,
 * `resolution` and `bitrate` — the video-dimensions branch of
 * `get_quality_info` sets both `resolution` and `quality` together — never a
 * fixed set.
 */
export type QualityInfo = {
  quality?: string;
  resolution?: string;
  bitrate?: string;
} | null;

/**
 * `/api/vod/movies/` — `MovieSerializer`, `fields = '__all__'` plus a nested
 * read-only `logo`. Nullability is the model's (`apps/vod/models.py` `Movie`).
 *
 * `custom_properties` is `None` far more often than it looks: ingest sets it
 * to `custom_props or None` and only ever populates
 * `youtube_trailer`/`director`/`actors`/`release_date`
 * (`apps/vod/tasks.py`, `process_movie_batch`), and
 * `clean_custom_properties({})` returns `None`. A provider entry carrying none
 * of those four leaves it null — which is the precondition of the
 * `get_vod_info` defect pinned in `xc-vod-catalogue.spec.ts`.
 *
 * `rating` is a `CharField`, not a number.
 */
export type Movie = {
  id: number;
  uuid: string;
  name: string;
  description: string | null;
  year: number | null;
  rating: string | null;
  genre: string | null;
  duration_secs: number | null;
  logo: VodLogo | null;
  tmdb_id: string | null;
  imdb_id: string | null;
  is_adult: boolean;
  custom_properties: Record<string, unknown> | null;
  created_at: string;
  updated_at: string;
};

/** `/api/vod/series/` — `SeriesSerializer`, `fields = '__all__'` plus nested `logo` and the `episode_count` method field. `Series` has no `is_adult` and no `duration_secs`. */
export type Series = {
  id: number;
  uuid: string;
  name: string;
  description: string | null;
  year: number | null;
  rating: string | null;
  genre: string | null;
  logo: VodLogo | null;
  tmdb_id: string | null;
  imdb_id: string | null;
  custom_properties: Record<string, unknown> | null;
  episode_count: number;
  created_at: string;
  updated_at: string;
};

/**
 * `/api/vod/episodes/` — `EpisodeSerializer`, `fields = '__all__'` with a
 * nested read-only `series`. `season_number` and `episode_number` are both
 * `IntegerField(null=True)` and both participate in
 * `unique_together ('series', 'season_number', 'episode_number')`.
 */
export type Episode = {
  id: number;
  uuid: string;
  name: string;
  description: string | null;
  air_date: string | null;
  rating: string | null;
  duration_secs: number | null;
  series: Series;
  season_number: number | null;
  episode_number: number | null;
  tmdb_id: string | null;
  imdb_id: string | null;
  custom_properties: Record<string, unknown> | null;
  created_at: string;
  updated_at: string;
};

/**
 * `/api/vod/categories/` — `VODCategorySerializer`. **Unpaginated**: no
 * `pagination_class` on `VODCategoryViewSet` and no
 * `DEFAULT_PAGINATION_CLASS` in `dispatcharr/settings.py`, so the list
 * endpoint returns a bare array of every category on the instance. Locate
 * yours with `find`, never a length or an index.
 *
 * `m3u_accounts` is `M3UVODCategoryRelationSerializer(source='m3u_relations')`,
 * whose three fields are exactly `category` (the id), `m3u_account` (the id)
 * and `enabled` — not nested objects.
 */
export type VodCategoryRelation = {
  category: number;
  m3u_account: number;
  enabled: boolean;
};
export type VodCategory = {
  id: number;
  name: string;
  category_type: 'movie' | 'series';
  category_type_display: string;
  m3u_accounts: VodCategoryRelation[];
};

/**
 * `/api/vod/movies/<pk>/providers/` — `M3UMovieRelationSerializer`,
 * `fields = '__all__'` with `movie`, `category` and `m3u_account` all nested
 * as full objects, plus a `quality_info` method field.
 *
 * `custom_properties` is the read-back surface for "what did the provider
 * actually say": `basic_data` is the whole `get_vod_streams` entry,
 * `detailed_info`/`movie_data` arrive from `refresh_movie_advanced_data`, and
 * `detailed_fetched` gates the 24-hour throttle.
 */
export type M3uMovieRelation = {
  id: number;
  movie: Movie;
  category: VodCategory | null;
  m3u_account: M3uAccount;
  quality_info: QualityInfo;
  stream_id: string;
  container_extension: string | null;
  custom_properties: Record<string, unknown> | null;
  last_advanced_refresh: string | null;
  last_seen: string;
  created_at: string;
  updated_at: string;
};

/** `/api/vod/series/<pk>/providers/` — `M3USeriesRelationSerializer`, `fields = '__all__'`. **`id` is what XC's `get_series` emits as `series_id`** — not `Series.id`. */
export type M3uSeriesRelation = {
  id: number;
  series: Series;
  category: VodCategory | null;
  m3u_account: M3uAccount;
  external_series_id: string;
  custom_properties: Record<string, unknown> | null;
  last_episode_refresh: string | null;
  last_seen: string;
  created_at: string;
  updated_at: string;
};

/** `M3UEpisodeRelationSerializer`, `fields = '__all__'` plus the `quality_info` method field. `unique_together` is `('m3u_account', 'stream_id')`, so several relations may point at one `Episode`. */
export type M3uEpisodeRelation = {
  id: number;
  episode: Episode;
  series_relation: number | null;
  m3u_account: M3uAccount;
  quality_info: QualityInfo;
  stream_id: string;
  container_extension: string | null;
  custom_properties: Record<string, unknown> | null;
  last_seen: string;
  created_at: string;
  updated_at: string;
};

/**
 * One row of the `category_settings` array in the body of
 * `PATCH /api/m3u/accounts/<id>/group-settings/`
 * (`M3UAccountViewSet.update_group_settings`, `apps/m3u/api_views.py`).
 *
 * **The key is `id` — the `VODCategory` primary key — not `category`.** Rows
 * without it are silently skipped. Like {@link GroupSettingRow}, this action
 * uses no serializer and issues a `bulk_create(update_conflicts=True,
 * update_fields=['enabled', 'custom_properties'])`, so an omitted field is
 * written as its zero value: omitting `custom_properties` writes `{}`.
 */
export type CategorySettingRow = {
  id: number;
  enabled: boolean;
  custom_properties: Record<string, unknown>;
};

/** `VODPagination` — `page_size` 20, `page_size` query param up to 100. Movies, series and episodes all paginate; categories do not. */
export type VodPage<T> = { count: number; next: string | null; previous: string | null; results: T[] };

/**
 * `apps.channels.RecurringRecordingRule` via `RecurringRecordingRuleSerializer`
 * (`apps/channels/serializers.py`, `fields = "__all__"`, only `created_at`/
 * `updated_at` read-only). `days_of_week` is `0`-`6`, Monday(`0`) through
 * Sunday(`6`), validated by `validate_days_of_week` — this **is** Python's
 * `date.weekday()` numbering, matching `sync_recurring_rule_impl`'s own
 * `target_date.weekday() not in days` check (`tasks.py:896`), not a
 * different scheme that merely happens to start the same day.
 * `start_time`/`end_time` are `TimeField`s (`"HH:MM:SS"`, no date component) —
 * unlike `Recording.start_time`/`end_time`, which are full `DateTimeField`s.
 */
export type RecurringRule = {
  id: number;
  channel: number;
  days_of_week: number[];
  start_time: string;
  end_time: string;
  enabled: boolean;
  name: string;
  start_date: string | null;
  end_date: string | null;
  created_at: string;
  updated_at: string;
};

/**
 * `/api/m3u/accounts/<id>/filters/` — nested under the account
 * (`apps/m3u/api_urls.py:24-26`, `M3UFilterViewSet.get_queryset` scopes to
 * `m3u_account_id` from the URL kwarg, `apps/m3u/api_views.py:589-591`), which
 * is also why `m3u_account` is not a field on `M3UFilterSerializer.Meta.fields`
 * — the full list (no field is read-only). `filter_type` is one of the three
 * `M3UFilter.FILTER_TYPE_CHOICES` (`apps/m3u/models.py`): `'group'` matches
 * the Xtream category / M3U `group-title`, `'name'` the stream name, `'url'`
 * the stream URL. `custom_properties` is `| null` because the model column is
 * `JSONField(null=True)` (`apps/m3u/models.py:196`).
 */
export type M3uFilter = {
  id: number;
  filter_type: 'group' | 'name' | 'url';
  regex_pattern: string;
  exclude: boolean;
  order: number;
  custom_properties: Record<string, unknown> | null;
};

/** The writable subset of {@link M3uFilter} — everything `M3UFilterSerializer.Meta.fields` lists except the generated `id`. */
export type M3uFilterOverrides = {
  filter_type?: 'group' | 'name' | 'url';
  regex_pattern?: string;
  exclude?: boolean;
  order?: number;
  custom_properties?: Record<string, unknown>;
};

/**
 * `/api/core/settings/` — `CoreSettingsSerializer` is `fields = "__all__"`
 * over the four-column `CoreSettings` model (`core/models.py`): `id`, `key`,
 * `name`, `value` (a `JSONField`). Lookup is by **`id`**, not `key` — `key`
 * is unique but is not the route's primary key, so a caller lists first to
 * find the row's `id`.
 */
export type CoreSetting = {
  id: number;
  key: string;
  name: string;
  value: unknown;
};

/**
 * `POST /api/core/settings/check/` — `CoreSettingsViewSet.check`
 * (`core/api_views.py`). For the network-access-list key only, returns
 * `{...perScopeExcludedCidrs, client_ip}`: one key per scope in the posted
 * `value`, each holding the CIDRs from that scope that do **not** contain the
 * requesting client, plus the resolved `client_ip`. An empty array for a
 * scope means the client is covered by it.
 */
export type NetworkAccessCheck = {
  client_ip: string;
  [scope: string]: string | string[];
};

/**
 * `POST /api/plugins/plugins/<key>/run/` — `PluginRunAPIView.post`
 * (`apps/plugins/api_views.py`). `result` is **double-wrapped** unless the
 * plugin action returns a `dict`: `PluginManager.run_action`
 * (`apps/plugins/loader.py`) passes a `dict` result through as-is, but wraps
 * anything else as `{"status": "ok", "result": <value>}` before this view
 * nests it again under its own `"result"` key.
 */
export type PluginRunResponse = {
  success: boolean;
  result?: unknown;
  error?: string;
};

/**
 * One entry of the `associations` array in the `epg_match` WebSocket event
 * (`apps/channels/tasks.py`, `match_epg_channels`/`match_selected_channels_epg`),
 * which carries the return value of
 * `apply_matched_epg_to_channels` (`apps/channels/epg_matching.py`) verbatim —
 * one row per channel whose `epg_data` assignment actually changed.
 */
export type EpgMatchAssociation = {
  channel_id: number;
  epg_data_id: number;
};

/**
 * The response shared by `ChannelViewSet.set_names_from_epg`,
 * `set_logos_from_epg` and `set_tvg_ids_from_epg`
 * (`apps/channels/api_views.py`) — each starts a Celery task over
 * `channel_ids` (or, for `set_logos_from_epg` only, an `epg_source_id`) and
 * returns immediately with the task handle, not the task's result.
 */
export type EpgFieldCopyResponse = {
  message: string;
  task_id: string;
  channel_count: number;
};
