from .settings import *
import dj_database_url

# Quick-start development settings - unsuitable for production
# See https://docs.djangoproject.com/en/5.0/howto/deployment/checklist/

ALLOWED_HOSTS = ['boardgamers-b44b863a1d98.herokuapp.com']
DATABASES['default'] = dj_database_url.config(conn_max_age=600, ssl_require=True)
MIDDLEWARE.append('whitenoise.middleware.WhiteNoiseMiddleware')

DOMAIN = "boardgamers-b44b863a1d98.herokuapp.com"
DOMAIN_PROTOCOL = 'https'
DOMAIN_URL = DOMAIN_PROTOCOL + "://" + DOMAIN

AWS_STORAGE_BUCKET_NAME = 'boardgamers-prod-public'

print('prod settings loaded')
