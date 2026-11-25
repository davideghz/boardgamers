from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.db.models import Q
from django.utils.formats import date_format
from django.utils.translation import gettext_lazy as _

from webapp.models import Event, MasterEvent, Table


def linkable_events(user):
    events = Event.objects.filter(organizer_location__isnull=False, master_event__isnull=True)
    if user.is_superuser:
        return events.filter(status__in=[Event.DRAFT, Event.PUBLISHED])
    managed_drafts = Event.objects.managed_by(user.user_profile).filter(status=Event.DRAFT)
    return events.filter(Q(status=Event.PUBLISHED) | Q(pk__in=managed_drafts))


@transaction.atomic
def set_master(event, master, user, *, unlink=False):
    # EventDate.save uses the same lock order.
    event = Event.objects.select_for_update().get(pk=event.pk)
    master = MasterEvent.objects.select_for_update().get(pk=master.pk)
    if not master.can_manage(user):
        raise PermissionDenied
    if unlink:
        if event.master_event_id != master.pk:
            raise ValidationError(_('The event is no longer linked to this manifestation.'))
        event.master_event = None
    else:
        if not linkable_events(user).filter(pk=event.pk).exists():
            raise ValidationError(_('The event is no longer available to link.'))
        missing_dates = list(event.dates.exclude(date__in=master.dates.values('date')).values_list('date', flat=True))
        if missing_dates:
            raise ValidationError(_('Add these dates to the manifestation calendar before linking the event: %(dates)s.') % {
                'dates': ', '.join(date_format(day) for day in missing_dates),
            })
        event.master_event = master
    event.save(update_fields=['master_event', 'updated_at'])


def public_children(master):
    return master.events.filter(status=Event.PUBLISHED).select_related('organizer_location').order_by('name', 'pk')


def public_program(master):
    return Table.objects.public().filter(event__master_event=master).select_related(
        'event__organizer_location',
    ).order_by('date', 'time', 'pk')
