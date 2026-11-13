from urllib.parse import parse_qs
from channels.middleware import BaseMiddleware
from channels.db import database_sync_to_async
from rest_framework_simplejwt.tokens import UntypedToken
from django.contrib.auth.models import AnonymousUser
from django.contrib.auth import get_user_model
from rest_framework_simplejwt.exceptions import InvalidToken, TokenError
from rest_framework_simplejwt.authentication import JWTAuthentication
import logging

logger = logging.getLogger(__name__)
User = get_user_model()

@database_sync_to_async
def get_user(validated_token):
    try:
        jwt_auth = JWTAuthentication()
        user = jwt_auth.get_user(validated_token)
        return user
    except User.DoesNotExist:
        user_id = validated_token.get('user_id', 'unknown')
        logger.warning(f"User from token does not exist. User ID: {user_id}")  # credential-logging: ignore - "token" is message text only; the argument is a user id claim from an already validated token
        return AnonymousUser()
    except Exception as e:
        logger.error(f"Error getting user from token: {type(e).__name__}")  # credential-logging: ignore - "token" is message text only; the argument is the exception type name
        return AnonymousUser()

class JWTAuthMiddleware(BaseMiddleware):
    async def __call__(self, scope, receive, send):
        try:
            # Extract the token from the query string
            query_string = parse_qs(scope["query_string"].decode())
            token = query_string.get("token", [None])[0]

            if token is not None:
                try:
                    validated_token = JWTAuthentication().get_validated_token(token)
                    scope["user"] = await get_user(validated_token)
                except (InvalidToken, TokenError) as e:
                    logger.warning(f"Invalid token: {type(e).__name__}")  # credential-logging: ignore - "token" is message text only; the argument is the exception type name
                    scope["user"] = AnonymousUser()
            else:
                scope["user"] = AnonymousUser()
        except Exception as e:
            logger.error(f"Error in JWT authentication: {type(e).__name__}")
            scope["user"] = AnonymousUser()

        return await super().__call__(scope, receive, send)
