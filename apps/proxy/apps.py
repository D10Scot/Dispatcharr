from django.apps import AppConfig

class ProxyConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'apps.proxy'
    verbose_name = "Stream Proxies"

    # ready() is deliberately absent. Until Phase 2 stage 2d-4 it imported
    # apps/proxy/live_proxy/server.py and instantiated the ProxyServer
    # singleton in every process that is not manage.py, setting
    # self.live_proxy for apps/proxy/signals.py and the `proxy` management
    # command to reach by getattr. The Go relay is that process now, so
    # there is no singleton to build and AppConfig.ready() is a no-op by
    # default -- an empty override would say less than its absence.
