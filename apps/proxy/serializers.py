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
    # the spec's § Stage 2b table). Nullable, never absent: a null says
    # "Django looked and there is nothing", which is a different fact from
    # a missing key, and the relay's fallbacks branch on exactly that.
    channel_name = serializers.CharField(allow_null=True)
    stream_name = serializers.CharField(allow_null=True)
    m3u_profile_name = serializers.CharField(allow_null=True)
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


class ProxySettingsSerializer(serializers.Serializer):
    """CoreSettings.get_proxy_settings()'s seven keys (core/models.py:709-717).

    Declared field by field rather than as a DictField so the contract is
    in the drf-spectacular schema and a Go client can generate against it.
    """

    buffering_timeout = serializers.FloatField()
    buffering_speed = serializers.FloatField()
    redis_chunk_ttl = serializers.IntegerField()
    channel_shutdown_delay = serializers.FloatField()
    channel_init_grace_period = serializers.FloatField()
    channel_client_wait_period = serializers.FloatField()
    new_client_behind_seconds = serializers.FloatField()


class NextSourceResponseSerializer(serializers.Serializer):
    source = SourceSerializer(allow_null=True)
    alternates = SourceSerializer(many=True)
    error = serializers.CharField(allow_null=True)
    proxy_settings = ProxySettingsSerializer()


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
