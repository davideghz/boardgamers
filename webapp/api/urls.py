from django.urls import path, include
from rest_framework.routers import DefaultRouter
from webapp.api.views import TableViewSet
from webapp.api.telegram_views import telegram_webhook, generate_setup_token

router = DefaultRouter()
router.register(r'tables', TableViewSet, basename='table')

urlpatterns = [
    path('', include(router.urls)),
    path('telegram/webhook/', telegram_webhook, name='telegram-webhook'),
    path('telegram/generate-token/<slug:slug>/', generate_setup_token, name='telegram-generate-token'),
]
