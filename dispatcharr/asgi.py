import django
import os
from django.core.asgi import get_asgi_application
from channels.routing import ProtocolTypeRouter, URLRouter
import dispatcharr.routing

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "dispatcharr.settings")

# Daphne does not fork and has no ASGI lifespan support, so import time is the
# hook (observability spec D10). Before django.setup() and the ASGI handler.
from dispatcharr.observability.bootstrap import init as _otel_init

_otel_init("mino-api", "daphne")

django.setup()

from .jwt_ws_auth import JWTAuthMiddleware

application = ProtocolTypeRouter({
    "http": get_asgi_application(),
    "websocket": JWTAuthMiddleware(
        URLRouter(dispatcharr.routing.websocket_urlpatterns)
    ),
})
