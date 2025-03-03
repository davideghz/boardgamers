from django.urls import path, include
from rest_framework.routers import DefaultRouter
from webapp.api.views import TableViewSet

router = DefaultRouter()
router.register(r'tables', TableViewSet, basename='table')

urlpatterns = [
    path('', include(router.urls)),
]
