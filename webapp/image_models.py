"""Shared transaction-safe lifecycle for models with uploaded images."""
from django.db import models, router, transaction
from django.db.models.signals import pre_delete

from webapp.services.image_files import delete_image_after_commit, image_fields


class ManagedImagesModel(models.Model):
    class Meta:
        abstract = True

    def save(self, *, using=None, update_fields=None, **kwargs):
        using = using or router.db_for_write(type(self), instance=self)
        if update_fields is not None:
            update_fields = frozenset(update_fields)
        fields = [field for field in image_fields(type(self))
                  if (update_fields is None or field.name in update_fields or field.attname in update_fields)
                  and not (update_fields is None and using == self._state.db
                           and field.attname in self.get_deferred_fields())]
        if not fields or self.pk is None or kwargs.get('force_insert'):
            return super().save(using=using, update_fields=update_fields, **kwargs)

        with transaction.atomic(using=using):
            previous = (type(self)._base_manager.using(using).select_for_update().filter(pk=self.pk)
                        .order_by().values_list(*(field.attname for field in fields)).first())
            result = super().save(using=using, update_fields=update_fields, **kwargs)
            if previous:
                for field, old_name in zip(fields, previous):
                    if old_name and old_name != getattr(self, field.attname).name:
                        delete_image_after_commit(field.storage, old_name, using=using)
            return result

    save.alters_data = True


def _delete_model_images(sender, instance, using, **kwargs):
    fields = image_fields(sender)
    # Read the row being deleted, rather than a possibly stale instance.
    names = (sender._base_manager.using(using).select_for_update().filter(pk=instance.pk)
             .order_by().values_list(*(field.attname for field in fields)).first())
    if names:
        for field, name in zip(fields, names):
            delete_image_after_commit(field.storage, name, using=using)


def connect_image_cleanup(apps):
    for model in apps.get_models():
        if issubclass(model, ManagedImagesModel) and image_fields(model):
            pre_delete.connect(_delete_model_images, sender=model,
                               dispatch_uid=f'managed_images_delete_{model._meta.label_lower}')
