# IMPORTANT
# Create a new file named local_settings.py and override settings

from .settings import *

print('dentro local_settings.py')

USE_S3 = env.bool('USE_S3', default=False)
if not USE_S3:
    MEDIA_ROOT = os.path.join(BASE_DIR, 'media')
    MEDIA_URL = '/media/'
    STORAGES = {
        **STORAGES,
        'default': {'BACKEND': 'django.core.files.storage.FileSystemStorage'},
    }

# Geospatial libraries
GDAL_LIBRARY_PATH = os.getenv(
    "GDAL_LIBRARY_PATH",
    "/Applications/Postgres.app/Contents/Versions/16/lib/libgdal.dylib"
)

GEOS_LIBRARY_PATH = os.getenv(
    "GEOS_LIBRARY_PATH",
    os.path.join('/opt/homebrew/opt/geos/lib', 'libgeos_c.dylib')
)

# Django Toolbar
INTERNAL_IPS = ('127.0.0.1',)
INSTALLED_APPS.append('debug_toolbar')
MIDDLEWARE.append('debug_toolbar.middleware.DebugToolbarMiddleware',)
