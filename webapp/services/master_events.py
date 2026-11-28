from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.db.models import Q
from django.utils.formats import date_format
from django.utils.translation import gettext_lazy as _

from webapp.models import Event, MasterEvent, Table


def linkable_events(user, master):
    """The events of other organizers can only join an approved manifestation."""
    events = Event.objects.filter(organizer_location__isnull=False, master_event__isnull=True)
    if user.is_superuser:
        return events.filter(status__in=[Event.DRAFT, Event.PUBLISHED])
    managed = Event.objects.managed_by(user.user_profile).filter(status__in=[Event.DRAFT, Event.PUBLISHED])
    if not master.is_published:
        return events.filter(pk__in=managed)
    return events.filter(Q(status=Event.PUBLISHED) | Q(pk__in=managed))


@transaction.atomic
def set_master(event, master, user, *, unlink=False):
    # EventDate.save uses the same lock order.
    event = Event.objects.select_for_update().get(pk=event.pk)
    master = MasterEvent.objects.select_for_update().get(pk=master.pk)
    # The organizer of an event can always take it out of a manifestation.
    if not (master.can_manage(user) or (unlink and event.is_manager(user.user_profile))):
        raise PermissionDenied
    if unlink:
        if event.master_event_id != master.pk:
            raise ValidationError(_('The gathering is no longer linked to this event.'))
        event.master_event = None
    else:
        if not linkable_events(user, master).filter(pk=event.pk).exists():
            raise ValidationError(_('The gathering is no longer available to link.'))
        missing_dates = list(event.dates.exclude(date__in=master.dates.values('date')).values_list('date', flat=True))
        if missing_dates:
            raise ValidationError(_('Add these dates to the event calendar before linking the gathering: %(dates)s.') % {
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
