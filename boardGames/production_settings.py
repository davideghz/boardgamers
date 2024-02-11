import dj_database_url
import environ
from django.conf.global_settings import DATABASES, MIDDLEWARE

ALLOWED_HOSTS = ['boardgamers-b44b863a1d98.herokuapp.com']
DATABASES['default'] = dj_database_url.config(conn_max_age=600, ssl_require=True)
MIDDLEWARE.append('whitenoise.middleware.WhiteNoiseMiddleware',)
