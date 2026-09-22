from django.urls import path, include

from apps.proxy import stats_views

app_name = 'proxy'

urlpatterns = [
    path('stats/', stats_views.combined_stats, name='combined_stats'),
    path('ts/', include('apps.proxy.ts_admin_urls')),
    path('ts/', include('apps.proxy.stream_routes')),
    path('catchup/', include('apps.timeshift.urls')),
    path('vod/', include('apps.proxy.vod_proxy.urls')),
]
