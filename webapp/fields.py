from django.core.files.base import File
from django.db.models import ImageField
from django.db.models.fields.files import ImageFieldFile

from webapp.services.images import normalize_network_logo, shrink_content_file


class ManagedImageFile(ImageFieldFile):
    def save(self, name, content, save=True):
        if not isinstance(content, File):
            content = File(content, name=name)
        if self.field.max_side:
            content.seek(0)
            name, content = shrink_content_file(content.read(), name, self.field.max_side)
        super().save(name, content, save=save)

    save.alters_data = True

    def delete(self, save=True):
        """Clear the field; ManagedImagesModel removes the stored file after commit."""
        if not self:
            return
        if hasattr(self, '_file'):
            self.close()
            del self.file
        if hasattr(self, '_dimensions_cache'):
            del self._dimensions_cache
        self.name = None
        setattr(self.instance, self.field.attname, self.name)
        self._committed = False
        if save:
            self.instance.save()

    delete.alters_data = True


class ManagedImageField(ImageField):
    """Pair with ManagedImagesModel; max_side enables shared image normalization."""
    attr_class = ManagedImageFile

    def __init__(self, *args, max_side=None, **kwargs):
        self.max_side = max_side
        super().__init__(*args, **kwargs)

    def deconstruct(self):
        name, path, args, kwargs = super().deconstruct()
        if self.max_side is not None:
            kwargs['max_side'] = self.max_side
        return name, path, args, kwargs


class NetworkLogoFile(ManagedImageFile):
    def save(self, name, content, save=True):
        if not isinstance(content, File):
            content = File(content, name=name)
        name, content = normalize_network_logo(content, name)
        super().save(name, content, save=save)

    save.alters_data = True


class NetworkLogoImageField(ManagedImageField):
    attr_class = NetworkLogoFile
    # Check the decoded format before saving, regardless of the upload's extension.
    default_validators = []
