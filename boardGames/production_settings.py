import dj_database_url
from django.conf.global_settings import DATABASES, MIDDLEWARE

# Quick-start development settings - unsuitable for production
# See https://docs.djangoproject.com/en/5.0/howto/deployment/checklist/

ALLOWED_HOSTS = ['boardgamers-b44b863a1d98.herokuapp.com']
DATABASES['default'] = dj_database_url.config(conn_max_age=600, ssl_require=True)
MIDDLEWARE += ['whitenoise.middleware.WhiteNoiseMiddleware',]

print(env)
