from collections import defaultdict

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from webapp.models import Event, EventParticipant, EventParticipantDate, Player


@transaction.atomic
def select_event_days(event, profile, ids):
    event = Event.objects.select_for_update().get(pk=event.pk)
    eligible = set(event.dates.filter(date__gte=timezone.localdate()).values_list('pk', flat=True))
    try:
        selected = {int(value) for value in ids}
    except (TypeError, ValueError) as error:
        raise ValidationError(_('Choose one of the event dates.')) from error
    if not selected and len(eligible) == 1:
        selected = eligible
    if not selected or selected - eligible:
        raise ValidationError(_('Choose one of the event dates.'))
    participant, created = EventParticipant.objects.get_or_create(event=event, user_profile=profile)
    participant.selected_dates.filter(event_date_id__in=eligible - selected).delete()
    EventParticipantDate.objects.bulk_create([
        EventParticipantDate(participant=participant, event_date_id=pk) for pk in selected
    ], ignore_conflicts=True)
    return created


def attendance_by_day(events, *, public=False):
    """A stable user or guest identity per day, across all the supplied events."""
    days = defaultdict(set)
    selections = EventParticipantDate.objects.filter(participant__event__in=events).values_list(
        'event_date__date', 'participant__user_profile_id')
    for day, person in selections:
        days[day].add(('profile', person))
    players = Player.objects.filter(table__event__in=events)
    if public:
        players = players.filter(table__event__table_booking_enabled=True)
    for day, profile, guest in players.values_list('table__date', 'user_profile_id', 'guest_profile_id'):
        if profile:
            days[day].add(('profile', profile))
        elif guest:
            days[day].add(('guest', guest))
    return days
