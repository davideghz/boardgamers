import dj_database_url
from django.conf.global_settings import DATABASES

DATABASES['default'] = dj_database_url.config(conn_max_age=600, ssl_require=True)
