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
    dsn="https://33011e036835387caf005ea63685f8fe@o90644.ingest.us.sentry.io/4510884885102592",
    # Add data like request headers and IP for users,
    # see https://docs.sentry.io/platforms/python/data-management/data-collected/ for more info
    send_default_pii=True,
)

# GOOGLE RECAPTCHA
RECAPTCHA_PUBLIC_KEY = '6Ld_rv4qAAAAADThVKzB_SG3bbYiPxq2ZAXq0Psy'
RECAPTCHA_PRIVATE_KEY = '6Ld_rv4qAAAAAEMTjDwFIOuxyzVjBYISzU_ECS7A'

print('prod settings loaded')
