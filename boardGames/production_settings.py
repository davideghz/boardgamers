from .settings import *
import dj_database_url

# Quick-start development settings - unsuitable for production
# See https://docs.djangoproject.com/en/5.0/howto/deployment/checklist/

ALLOWED_HOSTS = ['board-gamers.com']

DATABASES['default'] = dj_database_url.config(conn_max_age=600, ssl_require=True)
if DATABASES['default']['ENGINE'] == 'django.db.backends.postgresql':
    DATABASES['default']['ENGINE'] = 'django.contrib.gis.db.backends.postgis'

MIDDLEWARE.append('whitenoise.middleware.WhiteNoiseMiddleware')

DOMAIN = "board-gamers.com"
DOMAIN_PROTOCOL = 'https'
DOMAIN_URL = DOMAIN_PROTOCOL + "://" + DOMAIN

AWS_STORAGE_BUCKET_NAME = 'boardgamers-prod-public'
AWS_S3_CUSTOM_DOMAIN = f'{AWS_STORAGE_BUCKET_NAME}.s3.amazonaws.com'

# GDAL_LIBRARY_PATH = ''
# GEOS_LIBRARY_PATH = ''

print('prod settings loaded')
