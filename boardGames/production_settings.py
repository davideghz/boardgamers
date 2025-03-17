from .settings import *
import dj_database_url
import sentry_sdk

# Quick-start development settings - unsuitable for production
# See https://docs.djangoproject.com/en/5.0/howto/deployment/checklist/

ALLOWED_HOSTS = ['board-gamers.com']
DEBUG = False

# DATABASE

DATABASES['default'] = dj_database_url.config(conn_max_age=600, ssl_require=True)
if DATABASES['default']['ENGINE'] == 'django.db.backends.postgresql':
    DATABASES['default']['ENGINE'] = 'django.contrib.gis.db.backends.postgis'

MIDDLEWARE.append('whitenoise.middleware.WhiteNoiseMiddleware')

DOMAIN = "board-gamers.com"
DOMAIN_PROTOCOL = 'https'
DOMAIN_URL = DOMAIN_PROTOCOL + "://" + DOMAIN

# S3
AWS_STORAGE_BUCKET_NAME = 'boardgamers-prod-public'
AWS_S3_CUSTOM_DOMAIN = f'{AWS_STORAGE_BUCKET_NAME}.s3.amazonaws.com'

# SES
EMAIL_BACKEND = 'django_ses.SESBackend'
AWS_SES_ACCESS_KEY_ID = env('AWS_SES_ACCESS_KEY_ID')
AWS_SES_SECRET_ACCESS_KEY = env('AWS_SES_SECRET_ACCESS_KEY')
AWS_SES_REGION_NAME = 'eu-west-1'
AWS_SES_REGION_ENDPOINT = 'email.eu-west-1.amazonaws.com'

# SENTRY
sentry_sdk.init(
    dsn="https://9e20218ac6979cd5bc4ef57c44082902@o4506841965133824.ingest.sentry.io/4506841968017408",
    # Set traces_sample_rate to 1.0 to capture 100%
    # of transactions for performance monitoring.
    traces_sample_rate=1.0,
    # Set profiles_sample_rate to 1.0 to profile 100%
    # of sampled transactions.
    # We recommend adjusting this value in production.
    profiles_sample_rate=1.0,
)

print('prod settings loaded')
