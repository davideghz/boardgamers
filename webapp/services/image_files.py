"""Delete replaced images only after commit and after their last reference is gone."""
import os

from django.apps import apps
from django.core.files.storage import FileSystemStorage
from django.db import models, router, transaction


def image_fields(model):
    return [field for field in model._meta.concrete_fields if isinstance(field, models.ImageField)]


def same_storage(left, right):
    if left is right:
        return True
    if isinstance(left, FileSystemStorage) and isinstance(right, FileSystemStorage):
        return os.path.realpath(left.location) == os.path.realpath(right.location)
    if hasattr(left, 'bucket_name') and hasattr(right, 'bucket_name'):
        return all(getattr(left, name, None) == getattr(right, name, None)
                   for name in ('bucket_name', 'location', 'endpoint_url'))
    # For unknown backends be conservative: a possible reference keeps the file.
    return type(left) is type(right)


def image_is_referenced(storage, name, *, using):
    for model in apps.get_models():
        if model._meta.proxy or not model._meta.managed or not router.allow_migrate_model(using, model):
            continue
        fields = [field for field in model._meta.local_fields
                  if isinstance(field, models.ImageField) and same_storage(storage, field.storage)]
        if not fields:
            continue
        query = models.Q()
        for field in fields:
            query |= models.Q(**{field.attname: name})
        if model._base_manager.using(using).filter(query).exists():
            return True
    return False


def delete_image_after_commit(storage, name, *, using):
    if not name:
        return

    def delete_if_unreferenced():
        if not image_is_referenced(storage, name, using=using):
            storage.delete(name)

    transaction.on_commit(delete_if_unreferenced, using=using, robust=True)


def resizable_image_fields():
    """Discover configured image fields, including future covers such as banners."""
    from webapp.fields import ManagedImageField
    for model in apps.get_models():
        for field in model._meta.local_fields:
            if isinstance(field, ManagedImageField) and field.max_side:
                yield model, field.name, field.max_side
