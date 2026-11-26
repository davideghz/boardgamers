from django.conf import settings
from django.core.files.storage import storages
from django.core.signals import setting_changed
from django.dispatch import receiver
from django.utils.functional import LazyObject, empty
from storages.backends.s3boto3 import S3Boto3Storage


class PublicMediaStorage(S3Boto3Storage):
    location = settings.PUBLIC_MEDIA_LOCATION
    file_overwrite = False
    default_acl = 'public-read'


class PrivateMediaStorage(S3Boto3Storage):
    """
    Files that hold personal data. Never linked directly: views stream them
    after checking who is asking, so there are no public or signed URLs.
    """
    bucket_name = settings.AWS_PRIVATE_STORAGE_BUCKET_NAME
    location = 'private'
    file_overwrite = False
    default_acl = 'private'
    querystring_auth = True
    custom_domain = None
    object_parameters = {'CacheControl': 'private, no-store'}


class _PrivateStorage(LazyObject):
    def _setup(self):
        self._wrapped = storages['private']


#: Resolved on first use, and again whenever a test overrides STORAGES.
private_storage = _PrivateStorage()


def get_private_storage():
    """FileField `storage` callable: migrations store the reference, not the backend."""
    return private_storage


@receiver(setting_changed)
def _reset_private_storage(*, setting, **kwargs):
    if setting == 'STORAGES':
        private_storage._wrapped = empty
