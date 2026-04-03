from django.contrib.admin.apps import AdminConfig


class CustomAdminConfig(AdminConfig):
    """Replaces 'django.contrib.admin' in INSTALLED_APPS to use our custom AdminSite."""
    default_site = 'webapp.admin_site.CustomAdminSite'
