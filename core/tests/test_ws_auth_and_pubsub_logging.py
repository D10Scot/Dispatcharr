"""The WebSocket JWT middleware and the Redis pub/sub manager log fixed events
and exception types, never exception text or a subscription pattern."""

from unittest.mock import MagicMock, patch

from asgiref.sync import async_to_sync
from django.test import SimpleTestCase
from rest_framework_simplejwt.exceptions import InvalidToken

from core import redis_pubsub
from core.tests.test_credential_logging_url_sites import assert_no_secret, capture
from dispatcharr import jwt_ws_auth


class JwtWsAuthLoggingTests(SimpleTestCase):
    def test_unexpected_user_lookup_error_logs_its_type_only(self):
        with patch.object(
            jwt_ws_auth.JWTAuthentication, "get_user", side_effect=RuntimeError("faketoken")
        ):
            with capture(jwt_ws_auth.logger) as logs:
                user = jwt_ws_auth.get_user.func({"user_id": 1})
        self.assertTrue(user.is_anonymous)
        assert_no_secret(self, logs.records)

    def test_invalid_token_logs_its_type_only(self):
        async def inner(scope, receive, send):
            return None

        middleware = jwt_ws_auth.JWTAuthMiddleware(inner)
        scope = {"query_string": b"token=faketoken"}
        with patch.object(
            jwt_ws_auth.JWTAuthentication,
            "get_validated_token",
            side_effect=InvalidToken("faketoken is bad"),
        ):
            with capture(jwt_ws_auth.logger) as logs:
                async_to_sync(middleware)(scope, None, None)
        self.assertTrue(scope["user"].is_anonymous)
        assert_no_secret(self, logs.records)

    def test_unexpected_middleware_error_logs_its_type_only(self):
        async def inner(scope, receive, send):
            return None

        middleware = jwt_ws_auth.JWTAuthMiddleware(inner)
        scope = {"query_string": b"token=faketoken"}
        with patch.object(
            jwt_ws_auth.JWTAuthentication,
            "get_validated_token",
            side_effect=RuntimeError("faketoken"),
        ):
            with capture(jwt_ws_auth.logger) as logs:
                async_to_sync(middleware)(scope, None, None)
        assert_no_secret(self, logs.records)


class PubSubLoggingTests(SimpleTestCase):
    def test_psubscribe_logs_no_pattern(self):
        manager = redis_pubsub.RedisPubSubManager(redis_client=MagicMock(), auto_reconnect=False)
        manager.pubsub = MagicMock()
        with capture(redis_pubsub.logger) as logs:
            manager.psubscribe("events:fakesecret:*")
        assert_no_secret(self, logs.records)
