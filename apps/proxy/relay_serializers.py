"""Wire shapes for /proxy/relay/... (Phase 1 PR 7, D12).

The other direction's shapes live in apps/proxy/serializers.py; these are
Django->relay. CLAUDE.md section Conventions: a serializer for every
request and response body, never a raw dict, and every route in the
drf-spectacular schema.

Every optional field is declared `required=False` with NO `default=`.
Both info builders in apps/proxy/live_proxy/channel_status.py assign
their optional keys inside conditionals, so a key can be absent entirely
rather than null -- the behaviour CLAUDE.md section Observing a channel
documents and e2e/fixtures/types.ts encodes. DRF's Field.get_attribute
raises SkipField for a missing key in exactly that configuration, so the
rendered JSON keeps the absences. Adding a default would turn every
absence into a null and change /proxy/ts/status and /proxy/stats/, which
this PR must leave alone.
"""

from rest_framework import serializers


class RelayChannelClientSerializer(serializers.Serializer):
    """One row of get_basic_channel_info's `clients` list."""

    client_id = serializers.CharField()
    user_agent = serializers.CharField(required=False, allow_null=True)
    output_format = serializers.CharField(required=False, allow_null=True)
    output_profile_id = serializers.IntegerField(required=False, allow_null=True)
    ip_address = serializers.CharField(required=False)
    connected_at = serializers.FloatField(required=False)
    user_id = serializers.CharField(required=False)


class RelayChannelSerializer(serializers.Serializer):
    """get_basic_channel_info, field for field."""

    channel_id = serializers.CharField()
    state = serializers.CharField(required=False, allow_null=True)
    url = serializers.CharField(required=False, allow_blank=True, allow_null=True)
    stream_profile = serializers.CharField(
        required=False, allow_blank=True, allow_null=True
    )
    owner = serializers.CharField(required=False, allow_null=True)
    buffer_index = serializers.IntegerField(required=False)
    client_count = serializers.IntegerField(required=False)
    uptime = serializers.FloatField(required=False)
    started_at = serializers.FloatField(required=False, allow_null=True)
    channel_name = serializers.CharField(required=False)
    logo_id = serializers.IntegerField(required=False)
    m3u_profile_id = serializers.IntegerField(required=False)
    stream_id = serializers.IntegerField(required=False)
    stream_name = serializers.CharField(required=False)
    total_bytes = serializers.IntegerField(required=False)
    avg_bitrate_kbps = serializers.FloatField(required=False)
    avg_bitrate = serializers.CharField(required=False)
    healthy = serializers.BooleanField(required=False)
    video_codec = serializers.CharField(required=False)
    resolution = serializers.CharField(required=False)
    source_fps = serializers.FloatField(required=False)
    ffmpeg_speed = serializers.FloatField(required=False)
    audio_codec = serializers.CharField(required=False)
    audio_channels = serializers.CharField(required=False)
    stream_type = serializers.CharField(required=False)
    clients = RelayChannelClientSerializer(many=True, required=False)


class RelayChannelListSerializer(serializers.Serializer):
    channels = RelayChannelSerializer(many=True)
    count = serializers.IntegerField()


class RelayDetailClientSerializer(serializers.Serializer):
    """One row of get_detailed_channel_info's `clients` list. Six fields
    always assigned with a fallback default, the rest conditional."""

    client_id = serializers.CharField()
    user_agent = serializers.CharField()
    worker_id = serializers.CharField()
    ip_address = serializers.CharField()
    user_id = serializers.CharField()
    output_format = serializers.CharField()
    output_profile_id = serializers.IntegerField(allow_null=True)
    connected_at = serializers.FloatField(required=False)
    last_active = serializers.FloatField(required=False)
    last_active_ago = serializers.FloatField(required=False)
    bytes_sent = serializers.IntegerField(required=False)
    avg_rate_KBps = serializers.FloatField(required=False)
    current_rate_KBps = serializers.FloatField(required=False)


class RelayChannelDetailSerializer(serializers.Serializer):
    """get_detailed_channel_info, field for field.

    buffer_stats and local_manager are DictFields: buffer_stats carries a
    free-form `diagnostics` sub-dict whose keys depend on which Redis
    probe found something, and pinning it would turn a diagnostic into a
    contract.
    """

    channel_id = serializers.CharField()
    state = serializers.CharField(required=False, allow_null=True)
    url = serializers.CharField(required=False, allow_blank=True, allow_null=True)
    stream_profile = serializers.CharField(
        required=False, allow_blank=True, allow_null=True
    )
    started_at = serializers.FloatField(required=False)
    owner = serializers.CharField(required=False, allow_null=True)
    buffer_index = serializers.IntegerField(required=False)
    channel_name = serializers.CharField(required=False)
    stream_id = serializers.IntegerField(required=False)
    stream_name = serializers.CharField(required=False)
    m3u_profile_id = serializers.IntegerField(required=False)
    m3u_profile_name = serializers.CharField(required=False)
    state_changed_at = serializers.FloatField(required=False)
    state_duration = serializers.FloatField(required=False)
    uptime = serializers.FloatField(required=False)
    total_bytes = serializers.IntegerField(required=False)
    total_data = serializers.CharField(required=False)
    avg_bitrate_kbps = serializers.FloatField(required=False)
    avg_bitrate = serializers.CharField(required=False)
    client_count = serializers.IntegerField(required=False)
    buffer_stats = serializers.DictField(required=False)
    local_manager = serializers.DictField(required=False)
    video_codec = serializers.CharField(required=False)
    resolution = serializers.CharField(required=False)
    width = serializers.CharField(required=False)
    height = serializers.CharField(required=False)
    video_bitrate = serializers.CharField(required=False)
    source_fps = serializers.CharField(required=False)
    pixel_format = serializers.CharField(required=False)
    source_bitrate = serializers.CharField(required=False)
    audio_codec = serializers.CharField(required=False)
    sample_rate = serializers.CharField(required=False)
    audio_channels = serializers.CharField(required=False)
    audio_bitrate = serializers.CharField(required=False)
    ffmpeg_speed = serializers.FloatField(required=False)
    ffmpeg_fps = serializers.CharField(required=False)
    actual_fps = serializers.CharField(required=False)
    ffmpeg_bitrate = serializers.CharField(required=False)
    stream_type = serializers.CharField(required=False)
    clients = RelayDetailClientSerializer(many=True, required=False)


class RelayChannelStateSerializer(serializers.Serializer):
    """The two-field answer to GET /proxy/relay/channels/<id>?fields=state.

    Its own serializer rather than a partial render of
    RelayChannelDetailSerializer, and the reason is a DRF detail worth
    knowing: Field.get_attribute's except branch checks `default`, then
    `allow_null`, and only then `required` (rest_framework/fields.py,
    3.17.1). So a missing key on a field declared
    `required=False, allow_null=True` renders as null rather than being
    skipped -- which would put "url": null, "stream_profile": null and
    "owner": null into this response. Harmless to channel_snapshot,
    which reads only `state`, but a lie on the wire and in the schema.

    `state` is nullable here for the same reason it is on the detail
    serializer: a channel whose metadata hash carries no `state` field
    reports null, never the string 'unknown' (Phase 1 PR 7, ruling 4).
    """

    channel_id = serializers.CharField()
    state = serializers.CharField(allow_null=True)


class RelayStopResponseSerializer(serializers.Serializer):
    """ChannelService.stop_channel / stop_client, passed through.

    `status` is the service layer's own 'success' or 'error' and travels
    in the body rather than as an HTTP status: the relay answered, and
    "this channel is not running here" is an answer, not a refusal. The
    Django-side wrapper is what turns it into the 404 the admin API has
    always returned.
    """

    status = serializers.CharField()
    message = serializers.CharField(required=False)
    channel_id = serializers.CharField(required=False)
    client_id = serializers.CharField(required=False)
    previous_state = serializers.DictField(required=False, allow_null=True)
    model_released = serializers.BooleanField(required=False)
    locally_processed = serializers.BooleanField(required=False)
    stop_key_set = serializers.BooleanField(required=False)
    event_published = serializers.BooleanField(required=False)


class RelayAdvanceRequestSerializer(serializers.Serializer):
    """A fully-resolved source (ruling 11). `url` is required: Django
    resolves the candidate in the API process, where the ORM is, and the
    relay applies it. Without it ChannelService.change_stream_url would
    take its own next_source branch, putting an ORM query back inside the
    relay process that PR 6 took out of it."""

    url = serializers.CharField()
    user_agent = serializers.CharField(
        required=False, allow_blank=True, allow_null=True, default=None
    )
    stream_id = serializers.IntegerField(required=False, allow_null=True, default=None)
    m3u_profile_id = serializers.IntegerField(
        required=False, allow_null=True, default=None
    )
    stream_name = serializers.CharField(
        required=False, allow_blank=True, allow_null=True, default=None
    )
    # /proxy/ts/change_stream/ has always cleared the running manager's
    # tried_stream_ids so an operator's manual switch does not inherit a
    # failover's exclusion list. That reset used to run in the same
    # process as the manager; since PR 4's routing put the view on the
    # API role, proxy_server.stream_managers there is always empty and
    # the reset silently stopped happening. It moves here, where the
    # manager is. next_stream never reset it and still does not, which
    # is why this is a flag rather than unconditional.
    reset_tried = serializers.BooleanField(required=False, default=False)


class RelayAdvanceResponseSerializer(serializers.Serializer):
    """ChannelService.change_stream_url's dict, passed through.

    `confirmed` is present only when the owner never answered within
    STREAM_SWITCH_CONFIRM_TIMEOUT; the Django-side wrapper maps its
    absence to 502 and its presence to 504, which is what
    /proxy/ts/change_stream/ returns today.
    """

    status = serializers.CharField()
    success = serializers.BooleanField(required=False)
    confirmed = serializers.BooleanField(required=False)
    message = serializers.CharField(required=False)
    error = serializers.CharField(required=False)
    direct_update = serializers.BooleanField(required=False)
    event_published = serializers.BooleanField(required=False)
    metadata_updated = serializers.BooleanField(required=False)
    worker_id = serializers.CharField(required=False)
    diagnostics = serializers.DictField(required=False)
