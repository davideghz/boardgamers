# IMPORTANT
# Create a new file named local_settings.py and override settings

from .settings import *

print('dentro local_settings.py')

# Geospatial libraries
GDAL_LIBRARY_PATH = '/Applications/Postgres.app/Contents/Versions/16/lib/libgdal.dylib'
GEOS_LIBRARY_PATH = os.path.join('/opt/homebrew/opt/geos/lib', 'libgeos_c.dylib')

# Django Toolbar
INTERNAL_IPS = ('127.0.0.1',)
INSTALLED_APPS.append('debug_toolbar')
MIDDLEWARE.append('debug_toolbar.middleware.DebugToolbarMiddleware',)
