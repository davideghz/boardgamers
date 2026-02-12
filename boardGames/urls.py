from django.conf import settings
from django.conf.urls.i18n import i18n_patterns
from django.conf.urls.static import static

from django.contrib import admin
from django.urls import path, include
from webapp.views.i18n import custom_set_language

urlpatterns = [
    # Lingua: endpoint per cambiare lingua (cookie + redirect)
    path("i18n/setlang/", custom_set_language, name="set_language"),

    # --- URL NON localizzati (niente prefisso /en)
    # API: meglio evitare di cambiare path in base alla lingua
    path("api/", include("webapp.api.urls")),

    # Social auth: spesso i redirect URI sono fissi
    path("", include("social_django.urls", namespace="social")),
]

# --- URL localizzati (IT su '/', EN su '/en/...') ---
urlpatterns += i18n_patterns(
    # Admin (opzionale dentro i18n; così avrai /admin e /en/admin)
    path("admin/", admin.site.urls),

    # Tutto il sito “umano” (pagine, tabelle, profili, ecc.)
    path("", include("webapp.urls")),
    prefix_default_language=False,  # <- niente /it, solo / e /en
)

# Debug & static: fuori da i18n
if settings.DEBUG:
    import debug_toolbar
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)
    urlpatterns += [path("__debug__/", include(debug_toolbar.urls))]
