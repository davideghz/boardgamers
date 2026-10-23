from .settings import *
import dj_database_url
import sentry_sdk

# Quick-start development settings - unsuitable for production
# See https://docs.djangoproject.com/en/5.0/howto/deployment/checklist/

ALLOWED_HOSTS = ['board-gamers.com']
DEBUG = False

# HTTPS / Session security
SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True

# Social auth: redirect to login with a toast instead of 500 on auth errors
SOCIAL_AUTH_LOGIN_ERROR_URL = '/accounts/login/'
# Enable Django messages framework inside SocialAuthExceptionMiddleware
MESSAGE_TAGS = {10: 'debug', 20: 'info', 25: 'success', 30: 'warning', 40: 'error'}

# DATABASE

DATABASES['default'] = dj_database_url.config(conn_max_age=600, ssl_require=True)
if DATABASES['default']['ENGINE'] == 'django.db.backends.postgresql':
    DATABASES['default']['ENGINE'] = 'django.contrib.gis.db.backends.postgis'

MIDDLEWARE.append('whitenoise.middleware.WhiteNoiseMiddleware')
MIDDLEWARE.append('social_django.middleware.SocialAuthExceptionMiddleware')

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
def _sentry_before_send(event, hint):
    # social_core logs every failed OAuth token exchange before turning it into
    # AuthCanceled, which SocialAuthExceptionMiddleware already handles. A 400
    # "invalid_grant" is the user reusing a stale code (reload/back on the
    # callback): drop it. Other failures (e.g. invalid_client) still get through.
    record = hint.get('log_record')
    if record is not None and record.name == 'social':
        message = record.getMessage()
        if message.startswith('Request failed with 400') and 'invalid_grant' in message:
            return None
    return event


sentry_sdk.init(
    before_send=_sentry_before_send,
    dsn="https://33011e036835387caf005ea63685f8fe@o90644.ingest.us.sentry.io/4510884885102592",
    # Add data like request headers and IP for users,
    # see https://docs.sentry.io/platforms/python/data-management/data-collected/ for more info
    send_default_pii=True,
)

# GOOGLE RECAPTCHA
RECAPTCHA_PUBLIC_KEY = env('RECAPTCHA_PUBLIC_KEY')
RECAPTCHA_PRIVATE_KEY = env('RECAPTCHA_PRIVATE_KEY')

print('prod settings loaded')
