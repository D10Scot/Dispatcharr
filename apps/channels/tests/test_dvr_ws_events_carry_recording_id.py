"""Tests for #132: three of the seven DVR WebSocket events carried no
`recording_id`, only `channel`.

`recording_started` and both `recording_ended` payloads (`apps/channels/tasks.py`)
and `recording_stopped` (`apps/channels/api_views.py`) used to omit
`recording_id` from the event dict, even though all four sites have the id
in scope. For a channel recording twice at once -- `_stop_dvr_clients`'s own
docstring calls this a supported case -- a listener that only had `channel`
had no way to tell which recording an event was about.
"""
import ast
from datetime import timedelta
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIRequestFactory, force_authenticate

from apps.channels.models import Channel, Recording
from apps.channels.api_views import RecordingViewSet

REPO_ROOT = Path(__file__).resolve().parents[3]


def _iter_non_test_python_files(root: Path):
    for path in sorted(root.rglob("*.py")):
        if not path.is_file():
            continue
        parts = path.relative_to(root).parts
        if "tests" in parts or "test" in parts:
            continue
        if path.name.startswith("test_"):
            continue
        if "node_modules" in parts or ".venv" in parts or "venv" in parts:
            continue
        yield path


def _recording_event_violations(root: Path):
    """Every dict literal whose "type" starts with "recording_" must also
    carry a "recording_id" key. Returns a list of "path:line: type_value"
    strings for every dict that doesn't."""
    violations = []
    for path in _iter_non_test_python_files(root / "apps"):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.Dict):
                continue
            type_value_node = None
            has_recording_id = False
            for key, value in zip(node.keys, node.values):
                if not isinstance(key, ast.Constant) or not isinstance(key.value, str):
                    continue
                if key.value == "type" and isinstance(value, ast.Constant) and isinstance(value.value, str):
                    if value.value.startswith("recording_"):
                        type_value_node = value
                elif key.value == "recording_id":
                    has_recording_id = True
            if type_value_node is not None and not has_recording_id:
                rel = path.relative_to(root)
                violations.append(f"{rel}:{type_value_node.lineno}: {type_value_node.value}")
    return violations


class RecordingEventPayloadStaticTests(TestCase):
    def test_every_recording_event_payload_carries_recording_id(self):
        violations = _recording_event_violations(REPO_ROOT)
        self.assertEqual(
            violations,
            [],
            "Every WS event dict whose type starts with 'recording_' must "
            "also carry a 'recording_id' key:\n" + "\n".join(violations),
        )


def _make_admin():
    from django.contrib.auth import get_user_model
    User = get_user_model()
    u, _ = User.objects.get_or_create(
        username="ws_events_test_admin",
        defaults={"user_level": User.UserLevel.ADMIN},
    )
    u.set_password("pass")
    u.save()
    return u


def _async_channel_layer_mock():
    layer = MagicMock()
    layer.group_send = AsyncMock()
    return layer


class RecordingStartedEventTests(TestCase):
    """run_recording sends recording_started before the pre-stopped check,
    so the mocked layer's first group_send is the event. Borrows
    RunRecordingRaceGuardTests' harness (test_recording_stop_cancel.py):
    patching Recording.objects.get to report 'stopped' short-circuits
    run_recording right after that event is sent, without driving ffmpeg."""

    def setUp(self):
        self.channel = Channel.objects.create(
            channel_number=94, name="WS Event Started Channel"
        )

    def test_recording_started_event_names_the_recording(self):
        from apps.channels.tasks import run_recording as run_rec

        now = timezone.now()
        rec = Recording.objects.create(
            channel=self.channel,
            start_time=now - timedelta(minutes=1),
            end_time=now + timedelta(hours=1),
            custom_properties={},
        )
        mock_layer = _async_channel_layer_mock()
        original_get = Recording.objects.get

        def patched_get(*args, **kwargs):
            obj = original_get(*args, **kwargs)
            if kwargs.get("id") == rec.id or (args and args[0] == rec.id):
                obj.custom_properties = {"status": "stopped"}
            return obj

        with patch("apps.channels.tasks.get_channel_layer", return_value=mock_layer), \
             patch("core.utils.log_system_event", side_effect=Exception("skip")), \
             patch.object(Recording.objects, "get", side_effect=patched_get):
            run_rec(rec.id, self.channel.id, str(rec.start_time), str(rec.end_time))

        mock_layer.group_send.assert_called()
        first_call = mock_layer.group_send.call_args_list[0]
        payload = first_call[0][1]
        self.assertEqual(payload["data"]["type"], "recording_started")
        self.assertEqual(payload["data"]["recording_id"], rec.id)


class RecordingStoppedEventTests(TestCase):
    """Drives POST /api/channels/recordings/{id}/stop/ with
    core.utils.send_websocket_update patched, as StopEndpointTests does in
    test_recording_stop_cancel.py."""

    def setUp(self):
        self.channel = Channel.objects.create(
            channel_number=93, name="WS Event Stopped Channel"
        )
        self.user = _make_admin()
        self.factory = APIRequestFactory()

    def _stop(self, rec):
        request = self.factory.post(f"/api/channels/recordings/{rec.id}/stop/")
        force_authenticate(request, user=self.user)
        view = RecordingViewSet.as_view({"post": "stop"})
        return view(request, pk=rec.id)

    @patch("core.utils.send_websocket_update")
    @patch("threading.Thread")
    def test_recording_stopped_event_names_the_recording(self, mock_thread, mock_ws):
        mock_thread.return_value.start = MagicMock()
        now = timezone.now()
        rec = Recording.objects.create(
            channel=self.channel,
            start_time=now - timedelta(hours=1),
            end_time=now + timedelta(hours=1),
            custom_properties={"status": "recording"},
        )

        response = self._stop(rec)

        self.assertEqual(response.status_code, 200)
        payload = mock_ws.call_args[0][2]
        self.assertEqual(payload["type"], "recording_stopped")
        self.assertEqual(payload["recording_id"], rec.id)
