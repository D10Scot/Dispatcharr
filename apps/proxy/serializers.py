"""Wire shapes for /api/relay/... (Phase 1 PR 6, D12).

Every request body is validated through one of these and every response
rendered through one — CLAUDE.md § Conventions, no raw dicts. They also
make the routes describable to drf-spectacular, which is where the
contract in the spec's § Architecture becomes checkable.
"""

from rest_framework import serializers


class StreamProfileRefSerializer(serializers.Serializer):
    """A StreamProfile, flattened.

    `args` is the wire name the spec's contract uses; the model field is
    `parameters` (core/models.py:57) — a TextField of shell-style
    arguments that StreamProfile.build_command() shlex-splits.

    Deviation from the task brief's draft: the brief spelled this field as
    `args = serializers.CharField(source="parameters", ...)`, which reads
    an `instance.parameters`/`instance["parameters"]`. But
    apps/proxy/next_source.py's producers (Task 3, already merged --
    resolve_initial_source, get_stream_info_for_switch via
    _source_from_info) build the stream_profile sub-dict pre-flattened to
    the wire shape, `{"id": ..., "command": ..., "args":
    stream_profile.parameters}`, exactly matching design ruling 4's
    "stream_profile is returned as {id, command, args}". A `source=`
    lookup on a dict that already carries the key `args` (not
    `parameters`) raises KeyError. Reading `args` directly is what the
    already-committed producer requires; renaming the producer's key back
    to `parameters` would touch reviewed Task 3 code for a purely internal
    field name with no wire-visible difference.
    """

    id = serializers.IntegerField()
    command = serializers.CharField(allow_blank=True)
    args = serializers.CharField(allow_blank=True)
    # Phase 2 PR 2c-1. Which of the three Stream Profile architectures
    # this is: "redirect", "proxy" or "transcode". Required, not
    # optional -- every producer goes through next_source.py's
    # _stream_profile_ref(), so there is no shape that can omit it, and
    # a Go relay that has to guess is the gap this field closes
    # (spec § Stage 2c, Amendment A1.1).
    #
    # NOT a ChoiceField: the three values are a closed set today, and a
    # ChoiceField would make adding a fourth architecture a wire-schema
    # change that 400s a relay one version behind. A relay reading an
    # unrecognised kind should degrade, not be told the payload is
    # invalid by its own control plane.
    kind = serializers.CharField()


class SourceSerializer(serializers.Serializer):
    stream_id = serializers.IntegerField()
    url = serializers.CharField()
    user_agent = serializers.CharField(allow_blank=True)
    transcode = serializers.BooleanField()
    m3u_profile_id = serializers.IntegerField()
    # Whether THIS call reserved a provider slot. The relay releases only
    # what it reserved; without it, views.py's error paths double-release.
    slot_reserved = serializers.BooleanField()
    stream_profile = StreamProfileRefSerializer()
    # Phase 2 PR 2b-1. Four values Django holds while it builds this answer
    # and the relay used to re-query for in its own process
    # (services/channel_service.py:324,331,911 and input/manager.py:737 in
    # the spec's § Stage 2b table).
    #
    # channel_name/stream_name/m3u_profile_name are NOT allow_null, on
    # evidence, not by symmetry with ffmpeg_stream_profile below: every
    # producer in next_source.py reads them off a Channel, Stream or
    # M3UAccountProfile row already in hand (.name, never a dict .get()
    # that could silently return None), and none of the three models'
    # `name` fields carries null=True (apps/channels/models.py's Channel
    # and Stream, apps/m3u/models.py's M3UAccountProfile) -- a review
    # checked all three before this was decided. The "Django looked and
    # found nothing" case this field type would exist to represent is
    # handled one level up instead: when there is no Source to return at
    # all, the *outer* `source` key on NextSourceResponseSerializer is
    # null (already allow_null=True), and this whole sub-object is never
    # serialized. A Go client should read these as required strings.
    #
    # ffmpeg_stream_profile stays allow_null=True: no producer treats
    # "no locked ffmpeg profile installed" as an error, and it is a real
    # reachable state (core/signals.py only blocks *deleting* a locked
    # profile, not unlocking or renaming one) -- unlike the three names
    # above, None here is a fact next_source.py's own
    # _locked_ffmpeg_profile() can genuinely produce for a valid Source.
    channel_name = serializers.CharField()
    stream_name = serializers.CharField()
    m3u_profile_name = serializers.CharField()
    ffmpeg_stream_profile = StreamProfileRefSerializer(allow_null=True)


class NextSourceRequestSerializer(serializers.Serializer):
    exclude_stream_ids = serializers.ListField(
        child=serializers.IntegerField(), required=False, default=list
    )
    # The URL already playing. Django skips any candidate resolving to it,
    # which is the only reason input/manager.py used to loop candidates.
    # A body field, never a query parameter: it carries provider
    # credentials and must not reach an access log.
    current_url = serializers.CharField(
        required=False, allow_blank=True, allow_null=True, default=None
    )
    target_stream_id = serializers.IntegerField(
        required=False, allow_null=True, default=None
    )
    # The stream the relay is failing over FROM, so the traversal can
    # rotate to start right after it (order_alternates_from_current) the
    # same way today's pre-move get_alternate_streams(current_stream_id=)
    # call does. Consulted only on the failover branch (exclude_stream_ids
    # non-empty, target_stream_id absent); harmless elsewhere.
    current_stream_id = serializers.IntegerField(
        required=False, allow_null=True, default=None
    )
    reason = serializers.CharField(required=False, default="initial")
    include_alternates = serializers.BooleanField(required=False, default=False)


class RelayProxySettingsSerializer(serializers.Serializer):
    """CoreSettings.get_proxy_settings()'s seven keys (core/models.py:709-717),
    as the next-source contract renders them for the relay/a Go client.

    Declared field by field rather than as a DictField so the contract is
    in the drf-spectacular schema and a Go client can generate against it.

    NOT core.serializers.ProxySettingsSerializer (the settings UI's own
    validator for the same seven keys) -- drf-spectacular names OpenAPI
    components by class name, and two classes named ProxySettingsSerializer
    collided on one component until this was renamed. It was latent only
    because core.serializers.ProxySettingsSerializer's own viewset
    (core/api_views.py's ProxySettingsViewSet) is unrouted; the day someone
    routes it, spectacular keeps whichever registers first, and the two
    disagree on type: core's declares buffering_timeout, channel_shutdown_
    delay and channel_init_grace_period as IntegerField (with validators),
    this one as FloatField (this module renders whatever
    CoreSettings.get_proxy_settings() returns, e.g. 15.0, verbatim) -- a Go
    client generated against the wrong one gets json.Unmarshal refusing
    15.0 into an int.
    """

    buffering_timeout = serializers.FloatField()
    buffering_speed = serializers.FloatField()
    redis_chunk_ttl = serializers.IntegerField()
    channel_shutdown_delay = serializers.FloatField()
    channel_init_grace_period = serializers.FloatField()
    channel_client_wait_period = serializers.FloatField()
    new_client_behind_seconds = serializers.FloatField()

    # Phase 2 spec Amendment A1.4: TSConfig's class-attribute defaults, the
    # half of the effective settings that had never been on the wire. Each
    # is declared explicitly rather than through a DictField for this
    # class's existing reason -- the contract belongs in the
    # drf-spectacular schema so a Go client can generate against it -- and
    # the field TYPE mirrors the Python literal's own type, so a Go client
    # is not handed 15.0 where the schema promised an integer.
    #
    # The list is not maintained by hand: test_effective_proxy_settings.py
    # enumerates apps/proxy/config.py and fails if a default is added there
    # without appearing here. The file:line and value in each comment are
    # provenance for a reader, not the source of truth.
    #
    # No `required=False`: this serializer only ever renders, and the one
    # producer (_with_proxy_settings) always supplies every key, so a
    # missing key is a contract bug and should be a loud 500 rather than a
    # silently dropped field -- which is the failure mode A1.4 exists to
    # remove.
    BUFFER_CHUNK_SIZE = serializers.IntegerField()  # config.py:15 = 255868
    BUFFER_SPEED = serializers.IntegerField()  # config.py:17 = 1
    CHUNK_BATCH_SIZE = serializers.IntegerField()  # config.py:95 = 5
    CHUNK_SIZE = serializers.IntegerField()  # config.py:7 = 8192
    CHUNK_TIMEOUT = serializers.IntegerField()  # config.py:99 = 5
    CLEANUP_CHECK_INTERVAL = serializers.IntegerField()  # config.py:111 = 1
    CLEANUP_INTERVAL = serializers.IntegerField()  # config.py:107 = 60
    CLIENT_HEARTBEAT_INTERVAL = serializers.IntegerField()  # config.py:112 = 5
    CLIENT_POLL_INTERVAL = serializers.FloatField()  # config.py:8 = 0.1
    CLIENT_RECORD_TTL = serializers.IntegerField()  # config.py:110 = 60
    CLIENT_WAIT_TIMEOUT = serializers.IntegerField()  # config.py:114 = 60
    CONNECTION_TIMEOUT = serializers.IntegerField()  # config.py:13 = 10
    DEFAULT_USER_AGENT = serializers.CharField()  # config.py:6 = 'VLC/3.0.20 LibVLC/3.0.20'
    FAILOVER_GRACE_PERIOD = serializers.IntegerField()  # config.py:120 = 20
    GHOST_CLIENT_MULTIPLIER = serializers.FloatField()  # config.py:113 = 10.0
    HEALTH_CHECK_INTERVAL = serializers.IntegerField()  # config.py:104 = 5
    INITIAL_BEHIND_CHUNKS = serializers.IntegerField()  # config.py:94 = 4
    KEEPALIVE_INTERVAL = serializers.FloatField()  # config.py:97 = 0.5
    MAX_HEALTH_RECOVERY_ATTEMPTS = serializers.IntegerField()  # config.py:117 = 2
    MAX_KEEPALIVE_DURATION = serializers.IntegerField()  # config.py:122 = 300
    MAX_RECONNECT_ATTEMPTS = serializers.IntegerField()  # config.py:118 = 3
    MAX_RETRIES = serializers.IntegerField()  # config.py:9 = 3
    MAX_STREAM_SWITCHES = serializers.IntegerField()  # config.py:14 = 10
    MIN_STABLE_TIME_BEFORE_RECONNECT = serializers.IntegerField()  # config.py:119 = 30
    NEW_CLIENT_BEHIND_SECONDS = serializers.IntegerField()  # config.py:96 = 5
    RETRY_WAIT_INTERVAL = serializers.FloatField()  # config.py:12 = 0.5
    RETRY_WINDOW_SECONDS = serializers.IntegerField()  # config.py:10 = 1800
    STABLE_CONNECTION_THRESHOLD = serializers.IntegerField()  # config.py:11 = 30
    STREAM_TIMEOUT = serializers.IntegerField()  # config.py:103 = 20
    TARGET_BITRATE = serializers.IntegerField()  # config.py:102 = 8000000
    URL_SWITCH_TIMEOUT = serializers.IntegerField()  # config.py:121 = 20


class OutputProfileRefSerializer(serializers.Serializer):
    """One OutputProfile, already built into argv.

    `argv` and not StreamProfileRefSerializer's {command, args} pair on
    purpose: a StreamProfile's command is templated (build_command
    substitutes {streamUrl}/{userAgent}/{channelId} per tune, so only the
    relay can finish it), while an OutputProfile's is not -- it reads raw
    MPEG-TS on pipe:0 and writes to pipe:1 with no per-tune substitution
    at all (core/models.py:200-203). Sending the finished list is what
    lets a Go relay spawn the transcode without reimplementing shlex.
    """

    id = serializers.IntegerField()
    argv = serializers.ListField(child=serializers.CharField(allow_blank=True))


class NextSourceResponseSerializer(serializers.Serializer):
    source = SourceSerializer(allow_null=True)
    alternates = SourceSerializer(many=True)
    error = serializers.CharField(allow_null=True)
    proxy_settings = RelayProxySettingsSerializer()
    # Phase 2 PR 2b-2. Every is_active OutputProfile, keyed by
    # stringified id -- not just the one X-Relay-Output named, because
    # next-source runs once per channel while the profile is resolved
    # once per client, and the second client on a running channel makes
    # no next-source call (apps/proxy/live_proxy/views.py:712). A
    # DictField of a nested serializer, so the value shape is still in
    # the OpenAPI schema and a Go client can generate against it.
    output_profiles = serializers.DictField(child=OutputProfileRefSerializer())


class ReleaseRequestSerializer(serializers.Serializer):
    # Read by the relay out of its own metadata hash and passed in, so the
    # channel-deleted-mid-playback fallback needs no second round trip and
    # Django never reads a relay-owned key.
    stream_id = serializers.IntegerField(required=False, allow_null=True, default=None)
    m3u_profile_id = serializers.IntegerField(required=False, allow_null=True, default=None)
    channel_pk = serializers.IntegerField(required=False, allow_null=True, default=None)


class ReleaseResponseSerializer(serializers.Serializer):
    released = serializers.BooleanField()


class RelayEventSerializer(serializers.Serializer):
    type = serializers.CharField()
    # allow_blank=True: a caller may legitimately send "" (e.g. a
    # channel-less vod_start/vod_stop built by hand rather than through
    # control_plane.emit_event, which omits the key entirely when None).
    # core.relay_events._clean() normalises "" to None before the write:
    # SystemEvent.channel_id is a UUIDField (core/models.py:803,
    # null=True); UUIDField.to_python("") raises ValidationError, and
    # log_system_event's bare `except Exception` (core/utils.py:922-924)
    # would swallow it — no row, no Connect fan-out, one error log per
    # event. Every channel-less event hits this: vod_start and vod_stop
    # (vod_proxy/multi_worker_connection_manager.py:902) carry no channel
    # at all, and they are written today.
    channel_id = serializers.CharField(
        required=False, allow_blank=True, allow_null=True, default=None
    )
    channel_name = serializers.CharField(
        required=False, allow_blank=True, allow_null=True, default=None
    )
    client_id = serializers.CharField(
        required=False, allow_blank=True, allow_null=True, default=None
    )
    stream_id = serializers.IntegerField(required=False, allow_null=True, default=None)
    details = serializers.DictField(required=False, default=dict)


class RelayEventBatchSerializer(serializers.Serializer):
    events = RelayEventSerializer(many=True, max_length=200)


class RelayEventResponseSerializer(serializers.Serializer):
    accepted = serializers.IntegerField()
    rejected = serializers.IntegerField()
