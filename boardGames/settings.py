import os
import secrets
from pathlib import Path
import environ
from django.utils.translation import gettext_lazy as _


env = environ.Env()

# Build paths inside the project like this: BASE_DIR / 'subdir'.
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))

# Take environment variables from .env file
environ.Env.read_env(os.path.join(BASE_DIR, '.env'))

ENV = env('ENV')
SECRET_KEY = env('DJANGO_SECRET_KEY')
DEBUG = env.bool('DEBUG', default=False)

SITE_PROTOCOL = env('SITE_PROTOCOL', default='http')
SITE_DOMAIN = env('SITE_DOMAIN', default='localhost:8000')

TELEGRAM_BOT_TOKEN = env('TELEGRAM_BOT_TOKEN', default='')
TELEGRAM_BOT_USERNAME = env('TELEGRAM_BOT_USERNAME', default='')
TELEGRAM_WEBHOOK_SECRET = env('TELEGRAM_WEBHOOK_SECRET', default='')
BGG_API_TOKEN = env('BGG_API_TOKEN', default='')

ALLOWED_HOSTS = [
    'localhost',
    '127.0.0.1',
    '0.0.0.0',
    'urban-ever-spectacular-vcr.trycloudflare.com'
]

MIDDLEWARE = [
    'corsheaders.middleware.CorsMiddleware',  # Deve essere il primo middleware
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.middleware.locale.LocaleMiddleware',
    'webapp.middleware.UserLanguageRedirectMiddleware',  # Redirect to user's preferred language
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

# Application definition

INSTALLED_APPS = [
    # translations
    'modeltranslation',

    # admin (custom site for reorganized groups)
    'boardGames.admin_config.CustomAdminConfig',

    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',

    # sitemap
    'django.contrib.sitemaps',

    # geoDjango
    'django.contrib.gis',

    # webApp
    'webapp',

    # autocompletes
    'dal',
    'dal_select2',

    # AWS S3
    'storages',

    # Social Login
    'social_django',

    # API
    'corsheaders',
    'rest_framework',

    # GOOGLE RECAPTCHA
    'django_recaptcha',

    # SEO
    'meta',

    # JSON widget for admin
    'django_json_widget',
]

ROOT_URLCONF = 'boardGames.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',

                # django social auth
                'social_django.context_processors.backends',
                'social_django.context_processors.login_redirect',

                # notifications
                'webapp.context_processors.unread_notifications_count',
                'webapp.context_processors.maps_api_key',
                'webapp.context_processors.telegram_config',
            ],
        },
    },
]

WSGI_APPLICATION = 'boardGames.wsgi.application'

# GeoIP
GEOIP_PATH = os.path.join(BASE_DIR, 'geoip/')


# Database
# https://docs.djangoproject.com/en/5.0/ref/settings/#databases

DATABASES = {
    'default': {
        'ENGINE': 'django.contrib.gis.db.backends.postgis',
        'NAME': env('DB_NAME', default='boardgamers'),
        'USER': env('DB_USER', default='bg_user'),
        'PASSWORD': env('DB_PASSWORD', default='bg_password'),
        'HOST': env('DB_HOST', default='localhost'),
        'PORT': env('DB_PORT', default='5432'),
    }
}

# SOCIAL LOGIN
LOGIN_REDIRECT_URL = 'home'
LOGIN_URL = 'login'
SOCIAL_AUTH_USERNAME_IS_FULL_EMAIL = True
SOCIAL_AUTH_JSONFIELD_ENABLED = True
AUTHENTICATION_BACKENDS = (
    'social_core.backends.google.GoogleOAuth2',
    'social_core.backends.telegram.TelegramAuth',
    'django.contrib.auth.backends.ModelBackend',
)
SOCIAL_AUTH_PIPELINE = (
    # Get the information we can about the user and return it in a simple
    # format to create the user instance later. In some cases the details are
    # already part of the auth response from the provider, but sometimes this
    # could hit a provider API.
    'social_core.pipeline.social_auth.social_details',

    # Get the social uid from whichever service we're authing thru. The uid is
    # the unique identifier of the given user in the provider.
    'social_core.pipeline.social_auth.social_uid',

    # Verifies that the current auth process is valid within the current
    # project, this is where emails and domains whitelists are applied (if
    # defined).
    'social_core.pipeline.social_auth.auth_allowed',

    # Checks if the current social-account is already associated in the site.
    'social_core.pipeline.social_auth.social_user',

    # Guard against conflicts during account linking (authenticated user).
    'webapp.pipeline.validate_social_connect',

    # Make up a username for this person, appends a random string at the end if
    # there's any collision.
    'social_core.pipeline.user.get_username',

    # Send a validation email to the user to verify its email address.
    # Disabled by default.
    # 'social_core.pipeline.mail.mail_validation',

    # Associates the current social details with another user account with
    # a similar email address. Disabled by default.
    'social_core.pipeline.social_auth.associate_by_email',

    # Create a user account if we haven't found one yet.
    'social_core.pipeline.user.create_user',

    # Create UserProfile <--- THIS IS THE ONLY CUSTOM OPERATION
    'webapp.pipeline.create_user_profile',

    # Create the record that associates the social account with the user.
    # Custom step: handles race-condition double-submit gracefully.
    'webapp.pipeline.safe_associate_user',

    # Populate the extra_data field in the social record with the values
    # specified by settings (and the default ones like access_token, etc).
    'social_core.pipeline.social_auth.load_extra_data',

    # Update the user record with any changed info from the auth service.
    'social_core.pipeline.user.user_details',

    # If connecting Google to an account with no email, copy the Google email over.
    'webapp.pipeline.copy_email_from_google_if_missing',

    # Save language preference from OAuth state to user profile
    'webapp.pipeline.save_language_from_state',
)

SOCIAL_AUTH_GOOGLE_OAUTH2_KEY = env('GOOGLE_OAUTH2_KEY', default='')
SOCIAL_AUTH_GOOGLE_OAUTH2_SECRET = env('GOOGLE_OAUTH2_SECRET', default='')

SOCIAL_AUTH_TELEGRAM_BOT_TOKEN = env('TELEGRAM_BOT_TOKEN', default='')
SOCIAL_AUTH_TELEGRAM_IMMUTABLE_USER_FIELDS = ['first_name', 'last_name']
SOCIAL_AUTH_LOGIN_ERROR_URL = 'login'
SOCIAL_AUTH_NEW_ASSOCIATION_REDIRECT_URL = '/account/edit-profile/'
SOCIAL_AUTH_DISCONNECT_REDIRECT_URL = '/account/edit-profile/'

MAPS_API_KEY = env('MAPS_API_KEY', default='')

# Password validation
# https://docs.djangoproject.com/en/5.0/ref/settings/#auth-password-validators

AUTH_PASSWORD_VALIDATORS = [
    # {
    #     'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator',
    # },
    {
        'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator',
    },
    # {
    #     'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator',
    # },
    # {
    #     'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator',
    # },
]


# Internationalization
# https://docs.djangoproject.com/en/5.0/topics/i18n/

LANGUAGES = [
    ('en', 'English'),
    ('it', 'Italiano'),
]

LOCALE_PATHS = [
    os.path.join(BASE_DIR, 'webapp', 'locale'),
]

LANGUAGE_CODE = 'it'
TIME_ZONE = 'UTC'
USE_I18N = True
USE_L10N = True
USE_TZ = True

# Static files (CSS, JavaScript, Images)
# https://docs.djangoproject.com/en/3.2/howto/static-files/

STATIC_ROOT = os.path.join(BASE_DIR, 'staticfiles')
STATIC_URL = '/static/'

# Extra places for collectstatic to find static files.
STATICFILES_DIRS = (
    os.path.join(PROJECT_ROOT, 'static'),
)

STATICFILES_FINDERS = (
    'django.contrib.staticfiles.finders.FileSystemFinder',
    'django.contrib.staticfiles.finders.AppDirectoriesFinder',
)

DEFAULT_AVATAR_URL = 'images/avatar.webp'
DEFAULT_LOCATION_COVER_URL = 'images/location_cover.webp'
DEFAULT_GAME_COVER_URL = 'images/game.webp'

# Default primary key field type
# https://docs.djangoproject.com/en/5.0/ref/settings/#default-auto-field

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

DOMAIN = "localhost:8000"
DOMAIN_PROTOCOL = 'http'
DOMAIN_URL = DOMAIN_PROTOCOL + "://" + DOMAIN

# EMAILS
ENABLE_EMAIL_SIGNALS = True
DEFAULT_FROM_EMAIL = "Board-Gamers <info@board-gamers.com>"
EMAIL_BACKEND = 'django.core.mail.backends.smtp.EmailBackend'
EMAIL_USE_TLS = True
EMAIL_USE_SSL = False
EMAIL_HOST = env('EMAIL_HOST', default='sandbox.smtp.mailtrap.io')
EMAIL_HOST_USER = env('EMAIL_HOST_USER', default='')
EMAIL_HOST_PASSWORD = env('EMAIL_HOST_PASSWORD', default='')
EMAIL_PORT = env('EMAIL_PORT', default='2525')

# FILES UPLOAD

AWS_S3_ACCESS_KEY_ID = env('AWS_S3_ACCESS_KEY_ID')
AWS_S3_SECRET_ACCESS_KEY = env('AWS_S3_SECRET_ACCESS_KEY')

AWS_STORAGE_BUCKET_NAME = 'boardgamers-staging-public'
AWS_S3_CUSTOM_DOMAIN = f'{AWS_STORAGE_BUCKET_NAME}.s3.amazonaws.com'
AWS_S3_OBJECT_PARAMETERS = {'CacheControl': 'max-age=86400'}

# s3 static settings
# AWS_LOCATION = 'static'
# STATIC_URL = f'https://{AWS_S3_CUSTOM_DOMAIN}/{AWS_LOCATION}/'
# STATICFILES_STORAGE = 'storages.backends.s3boto3.S3Boto3Storage'

# s3 public media settings
PUBLIC_MEDIA_LOCATION = 'media'
MEDIA_URL = f'https://{AWS_S3_CUSTOM_DOMAIN}/{PUBLIC_MEDIA_LOCATION}/'
DEFAULT_FILE_STORAGE = 'boardGames.storage_backends.PublicMediaStorage'

DATA_UPLOAD_MAX_MEMORY_SIZE = 1024 * 1024 * 15  # 5MB
FILE_UPLOAD_MAX_MEMORY_SIZE = DATA_UPLOAD_MAX_MEMORY_SIZE

# API

REST_FRAMEWORK = {
    'DEFAULT_THROTTLE_RATES': {
        'anon': '100/hour',  # Limita le richieste anonime a 100 all'ora
    }
}

CORS_ALLOW_ALL_ORIGINS = True
# CORS_ALLOWED_ORIGINS = [
#     "https://board-gamers.com",
#     "https://www.anonimagiocatori.it/",
# ]

# GOOGLE RECAPTCHA
RECAPTCHA_PUBLIC_KEY = env('RECAPTCHA_PUBLIC_KEY')
RECAPTCHA_PRIVATE_KEY = env('RECAPTCHA_PRIVATE_KEY')

# SEO
META_USE_TITLE_TAG = True
META_SITE_PROTOCOL = SITE_PROTOCOL
META_SITE_DOMAIN = SITE_DOMAIN
META_USE_JSON_LD_SCHEMA = False
META_USE_TWITTER_PROPERTIES = True

LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'handlers': {
        'console': {
            'class': 'logging.StreamHandler',
        },
    },
    'root': {
        'handlers': ['console'],
        'level': 'WARNING',
    },
    'loggers': {
        'webapp': {
            'handlers': ['console'],
            'level': 'INFO' if DEBUG else 'WARNING',
            'propagate': False,
        },
    },
}
