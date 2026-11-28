from types import SimpleNamespace

from django.template import Context, Template
from django.contrib.auth.models import AnonymousUser
from django.test import RequestFactory, TestCase, override_settings
from django.urls import reverse
from django.utils import translation

from webapp.models import LocationAccess, Membership
from webapp.views.static_page_views import ui_gallery


def render(snippet, **context):
    with translation.override('it'):
        return Template('{% load custom_tags %}' + snippet).render(Context(context))


class ButtonTest(TestCase):
    def test_a_url_makes_a_link_otherwise_a_button(self):
        link = render('{% button "Vai" url="/x/" %}')
        self.assertIn('<a href="/x/"', link)
        self.assertIn('bg-primary', link)

        button = render('{% button "Invia" %}')
        self.assertIn('<button type="submit"', button)

    def test_variants_sizes_and_corners(self):
        html = render('{% button "Elimina" variant="danger" size="sm" type="button" disabled=True %}')
        self.assertIn('bg-danger-fill', html)
        self.assertIn('px-3 py-1.5 text-xs', html)
        self.assertIn('rounded-full', html)
        self.assertIn('type="button" disabled', html)
        self.assertIn('border-divider', render('{% button "Annulla" variant="secondary" %}'))

    def test_icon(self):
        self.assertIn('<svg', render('{% button "Nuovo" url="/x/" icon="plus" %}'))


class BadgeTest(TestCase):
    def test_states_are_filled_and_translated(self):
        html = render('{% status_badge "draft" %}')
        self.assertIn('Bozza', html)
        self.assertIn('bg-warning-soft', html)
        self.assertIn('Passato', render('{% status_badge "past" %}'))

    def test_types_are_outlined(self):
        html = render('{% type_badge "event" %}')
        self.assertIn('Evento', html)
        self.assertIn('border border-divider', html)

    def test_roles(self):
        self.assertIn('Titolare', render('{% role_badge "creator" %}'))
        self.assertIn('Socio', render('{% role_badge "member" %}'))

    def test_unknown_values_fall_back_to_a_neutral_label(self):
        self.assertIn('boh', render('{% status_badge "boh" %}'))


class PageHeaderTest(TestCase):
    def test_title_count_action_and_back_link(self):
        html = render('{% page_header "Eventi" count=3 action_label="Nuovo" action_url="/new/" back_url="/b/" back_label="Gestione" %}')
        self.assertIn('Eventi', html)
        self.assertIn('>3</span>', html)
        self.assertIn('href="/new/"', html)
        self.assertIn('href="/b/"', html)

    def test_a_zero_count_is_shown_none_is_not(self):
        self.assertIn('>0</span>', render('{% page_header "Eventi" count=0 %}'))
        self.assertNotIn('rounded-full bg-surface-input', render('{% page_header "Eventi" %}'))


class EmptyStateTest(TestCase):
    location = SimpleNamespace(slug='circolo', enable_membership=True)

    def test_plain_action(self):
        html = render('{% empty_state "Niente qui." action_label="Crea" action_url="/new/" %}')
        self.assertIn('Niente qui.', html)
        self.assertIn('href="/new/"', html)

    def test_a_refusal_becomes_the_way_forward(self):
        members_only = render('{% empty_state "Niente" access=access location=location action_url="/new/" %}',
                              access=LocationAccess(LocationAccess.MEMBERS_ONLY), location=self.location)
        self.assertIn(reverse('location-request-membership', args=['circolo']), members_only)
        self.assertNotIn('/new/', members_only)

        pending = render('{% empty_state "Niente" access=access location=location %}',
                         access=LocationAccess(LocationAccess.MEMBERSHIP_PENDING, membership=Membership.PENDING),
                         location=self.location)
        self.assertIn('in attesa', pending)

        allowed = render('{% empty_state "Niente" access=access location=location action_label="Crea" action_url="/new/" %}',
                         access=LocationAccess(), location=self.location)
        self.assertIn('href="/new/"', allowed)


class RowsAndTilesTest(TestCase):
    def test_result_row_keeps_type_and_state_apart(self):
        html = render('{% result_row "/t/" "Tavolo · sab 28 nov" "Catan" meta=meta status="open" %}',
                      meta=['Circolo Demo', ''])
        self.assertIn('href="/t/"', html)
        self.assertIn('Tavolo · sab 28 nov', html)
        self.assertIn('Aperto', html)
        self.assertEqual(html.count('text-xs text-content-muted">'), 1)  # empty meta lines are dropped

    def test_manage_tile_and_todo_card(self):
        tile = render('{% manage_tile "/m/" "Postazioni" description="4 configurate" icon="bolt" count=4 %}')
        self.assertIn('Postazioni', tile)
        self.assertIn('>4</span>', tile)
        todo = render('{% todo_card "/r/" "Richieste di adesione" 2 %}')
        self.assertIn('href="/r/"', todo)
        self.assertIn('>2</span>', todo)


class ParticipationAndDialogTest(TestCase):
    def test_participation_status(self):
        self.assertIn('Sei iscritto', render('{% participation_status %}'))
        html = render('{% participation_status "event" leave_dialog="leave" %}')
        self.assertIn("getElementById('leave').showModal()", html)

    def test_confirm_dialog_posts_with_the_csrf_token(self):
        html = render('{% confirm_dialog "leave" "Vuoi uscire?" "/leave/" "Esci" %}', csrf_token='tok')
        self.assertIn('<dialog id="leave"', html)
        self.assertIn('action="/leave/"', html)
        self.assertIn('value="tok"', html)
        self.assertIn('formmethod="dialog"', html)
        self.assertIn('bg-danger-fill', html)


class UiGalleryTest(TestCase):
    def test_only_in_debug(self):
        self.assertEqual(self.client.get(reverse('dev-ui')).status_code, 404)

        # Called directly: through the client, DEBUG=True would also bring in the debug toolbar,
        # whose URLs the test settings don't load.
        request = RequestFactory().get(reverse('dev-ui'))
        request.user = AnonymousUser()
        request.session = {}
        with override_settings(DEBUG=True):
            response = ui_gallery(request)
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'class="dark', response.content)
        self.assertIn(b'class="js-search-picker inline-flex"', response.content)  # the filter chip
