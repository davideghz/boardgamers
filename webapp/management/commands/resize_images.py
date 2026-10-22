from django.core.files.base import ContentFile
from django.core.management.base import BaseCommand

from webapp.services.images import jpeg_name, shrink_image_bytes
from webapp.signals import SHRINKABLE_IMAGE_FIELDS


class Command(BaseCommand):
    help = ("Shrink already-uploaded covers and avatars to JPEG with a max side "
            "(same rules as new uploads). Originals stay on S3: storage never overwrites.")

    def add_arguments(self, parser):
        parser.add_argument('--dry-run', action='store_true', help='Show what would be shrunk without saving')
        parser.add_argument('--model', help='Only this model (e.g. game, location, table, event, userprofile)')
        parser.add_argument('--limit', type=int, help='Stop after this many shrunk images')

    def handle(self, *args, **kwargs):
        dry_run = kwargs['dry_run']
        only_model = (kwargs['model'] or '').lower()
        limit = kwargs['limit']

        shrunk_count = 0
        bytes_before = 0
        bytes_after = 0

        for model, field_name, max_side in SHRINKABLE_IMAGE_FIELDS:
            if only_model and model.__name__.lower() != only_model:
                continue

            instances = model.objects.exclude(**{field_name: ''}).exclude(**{f'{field_name}__isnull': True})
            total = instances.count()
            self.stdout.write(f"\n{model.__name__}.{field_name}: {total} image(s), max side {max_side}px")

            for instance in instances.iterator():
                if limit and shrunk_count >= limit:
                    break

                field_file = getattr(instance, field_name)
                try:
                    with field_file.open('rb') as f:
                        data = f.read()
                except Exception as e:
                    self.stdout.write(self.style.ERROR(f"  {field_file.name}: cannot read ({e})"))
                    continue

                shrunk = shrink_image_bytes(data, max_side)
                if shrunk is None:
                    continue

                old_name = field_file.name
                if not dry_run:
                    field_file.save(jpeg_name(old_name), ContentFile(shrunk), save=False)
                    model.objects.filter(pk=instance.pk).update(**{field_name: field_file.name})

                shrunk_count += 1
                bytes_before += len(data)
                bytes_after += len(shrunk)
                self.stdout.write(
                    f"  {'(dry-run) ' if dry_run else ''}{old_name}: "
                    f"{len(data) // 1024} KB -> {len(shrunk) // 1024} KB"
                    + ('' if dry_run else f"  [{field_file.name}]")
                )

        self.stdout.write(self.style.SUCCESS(
            f"\nDone. {shrunk_count} image(s) {'would be ' if dry_run else ''}shrunk: "
            f"{bytes_before // 1024} KB -> {bytes_after // 1024} KB"
        ))
