from django.core.files.base import File
from django.db.models import ImageField
from django.db.models.fields.files import ImageFieldFile

from webapp.services.images import normalize_network_logo


class NetworkLogoFile(ImageFieldFile):
    def save(self, name, content, save=True):
        if not isinstance(content, File):
            content = File(content, name=name)
        name, content = normalize_network_logo(content, name)
        super().save(name, content, save=save)

    save.alters_data = True

    def delete(self, save=True):
        """Clear the field. The model removes the stored file after commit."""
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


class NetworkLogoImageField(ImageField):
    attr_class = NetworkLogoFile
    # Check the decoded format before saving, regardless of the upload's extension.
    default_validators = []
