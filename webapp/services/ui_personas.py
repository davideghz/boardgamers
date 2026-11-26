"""Demo data with one user for each audience of the UI.

Used by the ``seed_ui_personas`` command, to look at the pages as each audience, and by
``test_ui_smoke``, which renders the main pages for each of them.

Audiences: the anonymous visitor (no user), the newcomer with no ties, the active player
(tables, events and a manifestation day), the member of two associations, the manager of the
three locations and the organizer of a manifestation, who manages no location.
"""
from dataclasses import dataclass
from datetime import time, timedelta

from django.contrib.auth.models import User
from django.contrib.gis.geos import Point
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from webapp.models import (
    Event, EventDate, EventParticipant, Location, LocationFollower, MasterEvent, MasterEventDate,
    MasterEventDateParticipant, Member, Membership, Player, Table, UserProfile,
)

# Shared by every demo user: the data only exists on DEBUG databases.
PASSWORD = 'boardgamers-demo'
EMAIL_DOMAIN = 'ui-demo.example.com'
PERSONAS = ('newcomer', 'player', 'member', 'manager', 'organizer')

LOCATION_NAMES = ('Negozio Demo', 'Circolo Demo', 'Associazione Demo')
MANIFESTATION_NAME = 'Manifestazione Demo'

MILAN = (45.4642, 9.19)


@dataclass
class UiPersonas:
    newcomer: UserProfile
    player: UserProfile
    member: UserProfile
    manager: UserProfile
    # Manages the manifestation only: no location, membership or table.
    organizer: UserProfile
    # Game shop open to everyone, managed through Location.managers.
    negozio: Location
    # Association that runs its nights with tables: only members create and join them.
    circolo: Location
    # Association that runs its nights as events, without opening tables: members
    # propose events and join them, only the manager opens tables.
    associazione: Location
    manifestation: MasterEvent
    # Shop event with tables.
    event: Event
    # Weekly association night, without tables.
    night: Event
    # Proposed by the member, waiting for the manager.
    draft_event: Event
    tables: dict

    def profile(self, persona):
        return getattr(self, persona)


def email_for(persona):
    return f'{persona}@{EMAIL_DOMAIN}'


def exists():
    return User.objects.filter(username__in=[email_for(p) for p in PERSONAS]).exists()


@transaction.atomic
def delete_ui_personas():
    """Delete the demo data, found through the demo users (slugs come from the names).

    Players go first, so deleting the tables notifies nobody.
    """
    profiles = UserProfile.objects.filter(user__username__in=[email_for(p) for p in PERSONAS])
    Player.objects.filter(table__author__in=profiles).delete()
    Table.objects.filter(author__in=profiles).delete()
    Event.objects.filter(creator__in=profiles).delete()
    MasterEvent.objects.filter(managers__in=profiles, name=MANIFESTATION_NAME).delete()
    Location.objects.filter(
        Q(creator__in=profiles) | Q(managers__in=profiles), name__in=LOCATION_NAMES).delete()
    User.objects.filter(pk__in=profiles.values('user_id')).delete()


def _profile(persona, nickname):
    user = User.objects.create_user(
        username=email_for(persona), email=email_for(persona), password=PASSWORD,
        first_name=nickname, last_name='Demo')
    lat, lng = MILAN
    # Verified and without mail notifications: the demo must not send emails.
    return UserProfile.objects.create(
        user=user, nickname=nickname, is_email_verified=True, address='Milano', city='Milano',
        latitude=str(lat), longitude=str(lng),
        notification_new_table=False, notification_new_player=False, notification_new_comments=False,
    )


def _location(name, creator, **fields):
    lat, lng = MILAN
    return Location.objects.create(
        name=name, creator=creator, address='Via Demo 1', city='Milano',
        latitude=str(lat), longitude=str(lng), point=Point(lng, lat, srid=4326),
        description=f'{name}: dati dimostrativi creati da seed_ui_personas.', **fields)


def _member(location, profile, last_name, status, approved_by=None, today=None):
    member = Member.objects.create(
        location=location, user_profile=profile, first_name='Demo', last_name=last_name,
        email=profile.user.email)
    period = {}
    if status == Membership.ACTIVE:
        period = {'start_date': today - timedelta(days=60), 'end_date': today + timedelta(days=300)}
    return Membership.objects.create(member=member, status=status, approved_by=approved_by, **period)


def _event(name, organizer, creator, dates, status=Event.PUBLISHED, **fields):
    event = Event.objects.create(
        name=name, status=status, creator=creator, organizer_location=organizer,
        description=f'{name}: dati dimostrativi creati da seed_ui_personas.', **fields)
    for day in dates:
        EventDate.objects.create(event=event, date=day)
    return event


def _join_event(event, profile, dates):
    participant = EventParticipant.objects.create(event=event, user_profile=profile)
    for event_date in event.dates.filter(date__in=dates):
        participant.selected_dates.create(event_date=event_date)


@transaction.atomic
def seed_ui_personas():
    today = timezone.localdate()
    newcomer = _profile('newcomer', 'demo_nuovo')
    player = _profile('player', 'demo_giocatore')
    member = _profile('member', 'demo_socio')
    manager = _profile('manager', 'demo_gestore')
    organizer = _profile('organizer', 'demo_organizzatore')

    negozio_name, circolo_name, associazione_name = LOCATION_NAMES
    negozio = _location(negozio_name, creator=None)
    negozio.managers.add(manager)
    circolo = _location(
        circolo_name, creator=manager, enable_membership=True,
        table_creation_permission=Location.PERM_MEMBERS_ONLY,
        table_join_permission=Location.PERM_MEMBERS_ONLY,
    )
    associazione = _location(
        associazione_name, creator=manager, enable_membership=True, enable_calendar=True,
        table_creation_permission=Location.PERM_MANAGERS_ONLY,
        event_creation_permission=Location.PERM_MEMBERS_ONLY,
        event_join_permission=Location.PERM_MEMBERS_ONLY,
    )

    event = _event('Evento Demo', negozio, manager, [today + timedelta(days=14)], venue_location=negozio)
    nights = [today + timedelta(days=days) for days in (2, 9, 16)]
    # The association's weekly evenings run without tables: no table booking.
    night = _event('Serata Demo', associazione, manager, nights, venue_location=associazione,
                   table_booking_enabled=False)
    _event('Serata Demo passata', associazione, manager, [today - timedelta(days=12)],
           venue_location=associazione, table_booking_enabled=False)
    draft_event = _event('Proposta del socio', associazione, member, [today + timedelta(days=23)],
                         status=Event.DRAFT, venue_location=associazione)

    # A two-day manifestation in a venue that is not a location, run by the organizer, with
    # an event of the shop and one of the association.
    manifestation_days = [today + timedelta(days=days) for days in (30, 31)]
    lat, lng = MILAN
    venue = {'venue_name': 'Fiera Demo', 'address': 'Viale Fiera 1', 'city': 'Milano'}
    manifestation = MasterEvent.objects.create(
        name=MANIFESTATION_NAME, status=Event.PUBLISHED, latitude=lat, longitude=lng,
        description='Manifestazione dei dati dimostrativi.', **venue)
    manifestation.managers.add(organizer)
    for day in manifestation_days:
        MasterEventDate.objects.create(master_event=manifestation, date=day)
    MasterEventDateParticipant.objects.create(
        master_event_date=manifestation.dates.first(), user_profile=player)
    for name, location in (('Negozio Demo in fiera', negozio), ('Associazione Demo in fiera', associazione)):
        _event(name, location, manager, manifestation_days, master_event=manifestation,
               latitude=str(lat), longitude=str(lng), **venue)

    # Tables first: following a location before would notify its new tables.
    tables = {
        'upcoming': Table.objects.create(
            title='Tavolo aperto', author=manager, location=negozio,
            date=today + timedelta(days=3), time=time(21, 0)),
        'past': Table.objects.create(
            title='Tavolo passato', author=manager, location=negozio,
            date=today - timedelta(days=7), time=time(21, 0)),
        'members': Table.objects.create(
            title='Tavolo per soci', author=member, location=circolo,
            date=today + timedelta(days=5), time=time(21, 0)),
        'event': Table.objects.create(
            title="Tavolo dell'evento", author=manager,
            event=event, date=event.dates.get().date, time=time(15, 0)),
    }
    for key, author in (('upcoming', manager), ('past', manager), ('members', member), ('event', manager)):
        Player.objects.create(table=tables[key], user_profile=author)
    for key in ('upcoming', 'past', 'event'):
        Player.objects.create(table=tables[key], user_profile=player)
    _join_event(event, player, [event.dates.get().date])
    _join_event(night, member, nights[:2])

    LocationFollower.objects.create(user_profile=player, location=negozio)
    LocationFollower.objects.create(user_profile=member, location=circolo)
    LocationFollower.objects.create(user_profile=member, location=associazione)

    _member(circolo, member, 'Socio', Membership.ACTIVE, approved_by=manager, today=today)
    _member(associazione, member, 'Socio', Membership.ACTIVE, approved_by=manager, today=today)
    # Waiting for the manager: what an association's to-do list shows.
    _member(circolo, player, 'Giocatore', Membership.PENDING)

    return UiPersonas(
        newcomer=newcomer, player=player, member=member, manager=manager, organizer=organizer,
        negozio=negozio, circolo=circolo, associazione=associazione, manifestation=manifestation,
        event=event, night=night, draft_event=draft_event, tables=tables,
    )
