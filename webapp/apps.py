from django.apps import AppConfig


class WebappConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'webapp'

    def ready(self):
        import webapp.signals
        from webapp.services.images import restrict_open_formats
        restrict_open_formats()
