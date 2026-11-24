from io import BytesIO
from tempfile import TemporaryDirectory
from unittest.mock import patch

from django.contrib.admin.widgets import AdminFileWidget
from django.contrib.auth.models import Permission
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import transaction
from django.db.models import ProtectedError
from django.test import TestCase, override_settings
from django.urls import reverse
from PIL import Image

from webapp.factories import LocationFactory, SuperUserProfileFactory, UserProfileFactory
from webapp.models import LocationNetwork, Network
from webapp.views.location_views import _location_map_data


def logo_upload(name, size=(640, 320), color=(13, 68, 148, 128)):
    output = BytesIO()
    Image.new('RGBA', size, color=color).save(output, 'PNG')
    return SimpleUploadedFile(name, output.getvalue(), content_type='image/png')


class LocationNetworksTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.owner = UserProfileFactory(latitude='45', longitude='9')
        cls.manager = UserProfileFactory()
        cls.other_owner = UserProfileFactory()
        cls.location = LocationFactory(name='Magno Fato', creator=cls.owner, latitude='45', longitude='9')
        cls.location.managers.add(cls.manager)
        cls.other_location = LocationFactory(name='Other club', creator=cls.other_owner,
                                             latitude='46', longitude='9')
        cls.network = Network.objects.create(name='La Tana dei Goblin')
        cls.federludo = Network.objects.create(name='FederLudo')

    def setUp(self):
        media = TemporaryDirectory()
        self.addCleanup(media.cleanup)
        self.enterContext(override_settings(MEDIA_ROOT=media.name))
        self.manage_url = reverse('location-manage-networks', args=[self.location.slug])
        self.detail_url = reverse('location-detail', args=[self.location.slug])
        self.index_url = reverse('locations-index')

    def post_admin_affiliation(self, affiliation, inline_data):
        location = self.location
        return self.client.post(reverse('admin:webapp_location_change', args=[location.pk]), {
            'name': location.name,
            'slug': location.slug,
            'creator': location.creator_id,
            'description': location.description,
            'point': location.point.ewkt,
            'game_loan_days': location.game_loan_days,
            'leaderboard_edit_days': location.leaderboard_edit_days,
            'default_table_time': location.default_table_time.isoformat(),
            'table_creation_permission': location.table_creation_permission,
            'table_join_permission': location.table_join_permission,
            'network_affiliations-TOTAL_FORMS': 1,
            'network_affiliations-INITIAL_FORMS': 1,
            'network_affiliations-0-id': affiliation.pk,
            **{f'network_affiliations-0-{key}': value for key, value in inline_data.items()},
            '_save': '1',
        })

    def test_manager_adds_edits_and_removes_affiliation(self):
        self.client.force_login(self.manager.user)
        manage_index = self.client.get(reverse('location-manage', args=[self.location.slug]))
        self.assertContains(manage_index, self.manage_url)
        add_response = self.client.post(self.manage_url, {'network': self.network.pk, 'local_name': 'TdG Vicenza'})
        self.assertRedirects(add_response, self.manage_url)
        affiliation = self.location.network_affiliations.get(network=self.network)
        self.assertEqual(affiliation.local_name, 'TdG Vicenza')

        edit_url = reverse('location-edit-network', args=[self.location.slug, affiliation.pk])
        response = self.client.post(edit_url, {'local_name': ' TdG VI ', 'custom_logo': logo_upload('local.img')})
        self.assertRedirects(response, self.manage_url)
        affiliation.refresh_from_db()
        self.assertEqual(affiliation.local_name, 'TdG VI')
        self.assertTrue(affiliation.custom_logo.name.endswith('.png'))
        with Image.open(affiliation.custom_logo) as logo:
            self.assertEqual(logo.size, (512, 256))
            self.assertEqual(logo.getpixel((0, 0))[3], 128)

        storage = affiliation.custom_logo.storage
        original_name = affiliation.custom_logo.name
        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.post(edit_url, {'local_name': 'TdG VI', 'custom_logo': logo_upload('local.png')})
            self.assertTrue(storage.exists(original_name))
        self.assertRedirects(response, self.manage_url)
        affiliation.refresh_from_db()
        self.assertFalse(storage.exists(original_name))

        replacement_name = affiliation.custom_logo.name
        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.post(edit_url, {'local_name': '', 'custom_logo-clear': 'on'})
            self.assertTrue(storage.exists(replacement_name))
        self.assertRedirects(response, self.manage_url)
        self.assertFalse(storage.exists(replacement_name))
        affiliation.refresh_from_db()
        self.assertEqual(affiliation.display_name, self.network.name)
        self.assertFalse(affiliation.custom_logo)

        affiliation.custom_logo = logo_upload('local.png')
        affiliation.save(update_fields=['custom_logo'])
        removed_name = affiliation.custom_logo.name
        remove_url = reverse('location-remove-network', args=[self.location.slug, affiliation.pk])
        self.assertEqual(self.client.get(remove_url).status_code, 405)
        with self.captureOnCommitCallbacks(execute=True):
            self.assertRedirects(self.client.post(remove_url), self.manage_url)
            self.assertTrue(storage.exists(removed_name))
        self.assertFalse(storage.exists(removed_name))
        self.assertFalse(self.location.network_affiliations.exists())

    def test_direct_logo_save_normalizes_the_upload(self):
        self.network.logo.save('national.img', logo_upload('national.img'))
        self.network.refresh_from_db()
        self.assertTrue(self.network.logo.name.endswith('.png'))
        with Image.open(self.network.logo) as logo:
            self.assertEqual(logo.format, 'PNG')
            self.assertEqual(logo.size, (512, 256))
            self.assertEqual(logo.getpixel((0, 0))[3], 128)

    def test_logo_clear_and_affiliation_deletion_keep_their_files_on_rollback(self):
        self.network.logo.save('national.png', logo_upload('national.png'))
        affiliation = LocationNetwork.objects.create(location=self.location, network=self.network,
                                                      custom_logo=logo_upload('local.png'))
        national_name, local_name = self.network.logo.name, affiliation.custom_logo.name
        storage = affiliation.custom_logo.storage

        with self.captureOnCommitCallbacks(execute=True) as callbacks:
            with transaction.atomic():
                self.network.logo.delete()
                affiliation.delete()
                self.assertTrue(storage.exists(national_name))
                self.assertTrue(storage.exists(local_name))
                transaction.set_rollback(True)

        self.assertEqual(callbacks, [])
        self.network.refresh_from_db()
        self.assertEqual(self.network.logo.name, national_name)
        self.assertEqual(self.location.network_affiliations.get().custom_logo.name, local_name)
        self.assertTrue(storage.exists(national_name))
        self.assertTrue(storage.exists(local_name))

    def test_cascade_keeps_a_logo_until_the_last_reference_is_removed(self):
        affiliation = LocationNetwork.objects.create(location=self.location, network=self.network,
                                                      custom_logo=logo_upload('shared.png'))
        name = affiliation.custom_logo.name
        storage = affiliation.custom_logo.storage
        self.network.logo = name
        self.network.save(update_fields=['logo'])

        with self.captureOnCommitCallbacks(execute=True):
            self.location.delete()
        self.assertFalse(LocationNetwork.objects.filter(pk=affiliation.pk).exists())
        self.assertTrue(storage.exists(name))

        with self.captureOnCommitCallbacks(execute=True):
            self.network.delete()
            self.assertTrue(storage.exists(name))
        self.assertFalse(storage.exists(name))

    def test_owner_can_declare_two_networks_without_creating_duplicates(self):
        self.client.force_login(self.manager.user)
        stale_form = self.client.get(self.manage_url).context['form']
        self.assertIn(self.network, stale_form.fields['network'].queryset)

        self.client.force_login(self.owner.user)
        for network in (self.network, self.federludo):
            self.assertRedirects(self.client.post(self.manage_url, {
                'network': network.pk, 'local_name': 'Original name',
            }), self.manage_url)

        affiliation = self.location.network_affiliations.get(network=self.network)
        self.client.force_login(self.manager.user)
        response = self.client.post(self.manage_url, {
            'network': self.network.pk, 'local_name': 'Conflicting name', 'custom_logo': logo_upload('ignored.png'),
        }, follow=True)
        edit_url = reverse('location-edit-network', args=[self.location.slug, affiliation.pk])
        self.assertRedirects(response, edit_url)
        self.assertContains(response, 'Affiliazione già presente.')
        affiliation.refresh_from_db()
        self.assertEqual(affiliation.local_name, 'Original name')
        self.assertFalse(affiliation.custom_logo)
        self.assertFalse(affiliation.custom_logo.storage.exists('location-network-logos/ignored.png'))
        self.assertCountEqual(self.location.networks.all(), [self.network, self.federludo])

    def test_permissions_apply_to_mutations_and_to_the_specific_location(self):
        affiliation = LocationNetwork.objects.create(location=self.location, network=self.network)
        edit_url = reverse('location-edit-network', args=[self.location.slug, affiliation.pk])
        remove_url = reverse('location-remove-network', args=[self.location.slug, affiliation.pk])
        self.assertEqual(self.client.get(self.manage_url).status_code, 302)
        self.assertEqual(self.client.get(edit_url).status_code, 302)
        self.assertEqual(self.client.post(self.manage_url, {'network': self.federludo.pk}).status_code, 302)
        self.assertFalse(self.location.networks.filter(pk=self.federludo.pk).exists())

        self.client.force_login(self.other_owner.user)
        self.assertEqual(self.client.get(self.manage_url).status_code, 403)
        self.assertEqual(self.client.post(self.manage_url, {'network': self.federludo.pk}).status_code, 403)
        self.assertEqual(self.client.post(edit_url, {'local_name': 'Wrong club'}).status_code, 403)
        self.assertEqual(self.client.post(remove_url).status_code, 403)
        other_edit_url = reverse('location-edit-network', args=[self.other_location.slug, affiliation.pk])
        other_remove_url = reverse('location-remove-network', args=[self.other_location.slug, affiliation.pk])
        self.assertEqual(self.client.post(other_edit_url, {'local_name': 'Wrong club'}).status_code, 404)
        self.assertEqual(self.client.post(other_remove_url).status_code, 404)
        affiliation.refresh_from_db()
        self.assertEqual(affiliation.local_name, '')

    def test_manager_sees_the_full_affiliation_list(self):
        networks = Network.objects.bulk_create([
            Network(name=f'Network {i:02}', slug=f'network-{i:02}') for i in range(26)
        ])
        LocationNetwork.objects.bulk_create([
            LocationNetwork(location=self.location, network=network) for network in networks
        ])
        self.client.force_login(self.manager.user)
        response = self.client.get(self.manage_url, {'page': 2})
        self.assertEqual(len(response.context['affiliations']), 26)
        self.assertNotIn('page_obj', response.context)
        self.assertContains(response, 'Network 00')
        self.assertContains(response, 'Network 25')

    def test_public_filter_and_map_show_only_matching_locations_with_all_their_badges(self):
        LocationNetwork.objects.create(location=self.location, network=self.network, local_name='TdG Vicenza')
        LocationNetwork.objects.create(location=self.location, network=self.federludo)
        LocationNetwork.objects.create(location=self.other_location, network=self.federludo)
        without_coordinates = LocationFactory(name='No coordinates', latitude=None, longitude=None)
        LocationNetwork.objects.create(location=without_coordinates, network=self.network)
        self.client.force_login(self.owner.user)
        response = self.client.get(self.index_url, {'network': self.network.slug, 'new_table': '1', 'view': 'map'})

        self.assertEqual(response.context['nearby_locations'][0], self.location)
        self.assertCountEqual(response.context['nearby_locations'], [self.location, without_coordinates])
        self.assertIsNone(response.context['user_created_locations'])
        self.assertEqual(response.context['map_locations'], [{
            'name': 'Magno Fato', 'lat': 45.0, 'lng': 9.0, 'url': self.detail_url,
            'affiliations': ['FederLudo', 'TdG Vicenza'],
        }])
        self.assertContains(response, 'id="network-filter"')
        self.assertContains(response, f'value="{self.network.slug}" selected')
        self.assertContains(response, 'name="new_table" value="1"')
        self.assertContains(response, 'id="locations-list" hidden')
        self.assertContains(response, 'TdG Vicenza')
        self.assertNotContains(response, self.other_location.name)

    def test_detail_shows_both_logos_and_the_national_name_when_using_a_local_name(self):
        self.network.logo = 'network-logos/national.png'
        self.network.save(update_fields=['logo'])
        affiliation = LocationNetwork.objects.create(location=self.location, network=self.network,
                                                      local_name='TdG Vicenza', custom_logo='location-network-logos/vicenza.png')
        other_affiliation = LocationNetwork.objects.create(location=self.other_location, network=self.network,
                                                            custom_logo='location-network-logos/padova.png')
        response = self.client.get(self.detail_url)
        self.assertContains(response, f'{self.index_url}?network={self.network.slug}')
        self.assertContains(response, 'TdG Vicenza')
        self.assertContains(response, self.network.name)
        self.assertContains(response, self.network.logo.url)
        self.assertContains(response, affiliation.custom_logo.url)
        self.assertNotContains(response, other_affiliation.custom_logo.url)
        sidebar = response.text.split('<aside class="lg:col-span-1">', 1)[1].split('</aside>', 1)[0]
        self.assertLess(sidebar.index('id="location-directions"'), sidebar.index('id="location-affiliations"'))

    def test_filtered_page_shows_the_selected_network_logo_and_website(self):
        self.federludo.logo = 'network-logos/federludo.png'
        self.federludo.website = 'https://federludo.example.org/'
        self.federludo.save(update_fields=['logo', 'website'])

        response = self.client.get(self.index_url, {'network': self.federludo.slug})
        self.assertContains(response, '<h1 class="text-2xl font-extrabold text-content">FederLudo</h1>', html=True)
        self.assertContains(response, f'src="{self.federludo.logo.url}"')
        self.assertContains(response, f'href="{self.federludo.website}"')
        self.assertFalse(response.context['nearby_locations'])

        response = self.client.get(self.index_url)
        self.assertNotContains(response, self.federludo.logo.url)
        self.assertNotContains(response, self.federludo.website)

        self.federludo.is_active = False
        self.federludo.save(update_fields=['is_active'])
        response = self.client.get(self.index_url, {'network': self.federludo.slug})
        self.assertNotContains(response, self.federludo.website)
        self.assertNotContains(response, self.federludo.logo.url)

    def test_filter_excludes_locations_if_network_is_archived_during_the_request(self):
        LocationNetwork.objects.create(location=self.location, network=self.network)

        def archive_before_reading_locations(locations):
            Network.objects.filter(pk=self.network.pk).update(is_active=False)
            return _location_map_data(locations)

        with patch('webapp.views.location_views._location_map_data', side_effect=archive_before_reading_locations):
            response = self.client.get(self.index_url, {'network': self.network.slug})

        self.assertEqual(response.context['selected_network'], self.network)
        self.assertFalse(response.context['nearby_locations'])
        self.assertEqual(response.context['map_locations'], [])

    def test_archived_networks_disappear_publicly_and_cannot_be_added(self):
        affiliation = LocationNetwork.objects.create(location=self.location, network=self.network,
                                                      local_name='TdG Vicenza', custom_logo='location-network-logos/local.png')
        self.network.is_active = False
        self.network.save(update_fields=['is_active'])
        response = self.client.get(self.index_url, {'network': self.network.slug, 'view': 'map'})
        self.assertContains(response, f'href="{self.index_url}?view=map"')
        self.assertTrue(response.context['network_unavailable'])
        self.assertEqual(response.context['map_locations'], [])
        self.assertNotContains(self.client.get(self.index_url), 'TdG Vicenza')
        self.assertNotContains(self.client.get(self.detail_url), affiliation.custom_logo.url)
        with self.assertRaises(ProtectedError):
            self.network.delete()

        self.client.force_login(self.other_owner.user)
        other_manage = reverse('location-manage-networks', args=[self.other_location.slug])
        response = self.client.post(other_manage, {'network': self.network.pk})
        self.assertIn('network', response.context['form'].errors)
        self.assertFalse(self.other_location.networks.filter(pk=self.network.pk).exists())

        self.client.force_login(self.manager.user)
        self.assertContains(self.client.get(self.manage_url), 'TdG Vicenza')
        edit_url = reverse('location-edit-network', args=[self.location.slug, affiliation.pk])
        self.assertEqual(self.client.post(edit_url, {'local_name': 'Archived edit'}).status_code, 404)
        self.network.is_active = True
        self.network.save(update_fields=['is_active'])
        self.assertContains(self.client.get(self.detail_url), 'TdG Vicenza')
        self.network.is_active = False
        self.network.save(update_fields=['is_active'])
        remove_url = reverse('location-remove-network', args=[self.location.slug, affiliation.pk])
        self.assertRedirects(self.client.post(remove_url), self.manage_url)

    def test_empty_catalogue_links_to_contacts_and_valid_filter_has_an_empty_state(self):
        response = self.client.get(self.index_url, {'network': self.network.slug})
        self.assertFalse(response.context['network_unavailable'])
        self.assertFalse(response.context['nearby_locations'])
        self.assertContains(response, 'data-reset-network')

        Network.objects.all().update(is_active=False)
        self.client.force_login(self.manager.user)
        response = self.client.get(self.manage_url)
        self.assertContains(response, f'href="{reverse("contacts")}"')
        self.assertNotContains(response, 'name="network"')

    def test_invalid_logo_uploads_leave_affiliation_unchanged(self):
        self.client.force_login(self.manager.user)
        broken_logo = SimpleUploadedFile('spoofed.png', b'not an image', content_type='image/png')
        oversized_logo = logo_upload('wide.png', size=(2049, 10))
        oversized_file = SimpleUploadedFile('large.png', b'x' * (2 * 1024 * 1024 + 1), content_type='image/png')
        for logo in (broken_logo, oversized_logo, oversized_file):
            with self.subTest(logo=logo.name):
                response = self.client.post(self.manage_url, {'network': self.network.pk, 'custom_logo': logo})
                self.assertIn('custom_logo', response.context['form'].errors)
        self.assertFalse(self.location.network_affiliations.exists())

    def test_admin_catalogue_saves_website_and_replaces_logo_with_stable_slug(self):
        self.client.force_login(SuperUserProfileFactory().user)
        network_list = reverse('admin:webapp_network_changelist')
        self.assertContains(self.client.get(reverse('admin:index')), network_list)
        website = 'https://league.example.org/'
        response = self.client.post(reverse('admin:webapp_network_add'), {
            'name': 'National league', 'logo': logo_upload('national.png'), 'website': website,
            'is_active': 'on', '_save': '1',
        })
        self.assertRedirects(response, network_list)
        network = Network.objects.get(name='National league')
        with Image.open(network.logo) as logo:
            self.assertEqual(logo.size, (512, 256))
            self.assertEqual(logo.getpixel((0, 0))[3], 128)

        network_change = reverse('admin:webapp_network_change', args=[network.pk])
        storage = network.logo.storage
        original_name = network.logo.name
        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.post(network_change, {
                'name': 'Renamed league', 'website': website, 'logo': logo_upload('national.png'),
                'is_active': 'on', '_save': '1',
            })
            self.assertTrue(storage.exists(original_name))
        self.assertRedirects(response, network_list)
        network.refresh_from_db()
        self.assertEqual(network.slug, 'national-league')
        self.assertTrue(storage.exists(network.logo.name))
        self.assertFalse(storage.exists(original_name))
        self.assertEqual(network.website, website)

    def test_admin_network_links_to_filtered_location_list(self):
        self.client.force_login(SuperUserProfileFactory().user)
        self.network.is_active = False
        self.network.save(update_fields=['is_active'])
        LocationNetwork.objects.create(location=self.location, network=self.network)
        LocationNetwork.objects.create(location=self.location, network=self.federludo)
        LocationNetwork.objects.create(location=self.other_location, network=self.federludo)

        filtered_url = reverse('admin:webapp_location_changelist', query={
            'network_affiliations__network__id__exact': self.network.pk,
        })
        network_change = reverse('admin:webapp_network_change', args=[self.network.pk])
        self.assertContains(self.client.get(network_change), f'href="{filtered_url}"')
        response = self.client.get(filtered_url)
        self.assertEqual(list(response.context['cl'].result_list), [self.location])
        self.assertNotContains(self.client.get(reverse('admin:index')), '/admin/webapp/locationnetwork/')
        self.assertEqual(self.client.get('/admin/webapp/locationnetwork/').status_code, 404)

    def test_admin_affiliation_inline_can_replace_clear_and_remove_its_logo(self):
        self.client.force_login(SuperUserProfileFactory().user)
        affiliation = LocationNetwork.objects.create(location=self.location, network=self.network, local_name='Local league',
                                                      custom_logo=logo_upload('local.png'))
        change_url = reverse('admin:webapp_location_change', args=[self.location.pk])
        response = self.client.get(change_url)
        self.assertContains(response, 'Local league')
        inline = response.context['inline_admin_formsets'][0]
        self.assertFalse(inline.has_add_permission)
        self.assertIsInstance(inline.formset.forms[0].fields['custom_logo'].widget, AdminFileWidget)
        self.assertNotIn('network', inline.formset.forms[0].fields)
        self.assertNotIn('local_name', inline.formset.forms[0].fields)

        locations_list = reverse('admin:webapp_location_changelist')
        invalid_response = self.post_admin_affiliation(affiliation, {
            'custom_logo': SimpleUploadedFile('invalid.png', b'invalid', content_type='image/png'),
        })
        invalid_form = invalid_response.context['inline_admin_formsets'][0].formset.forms[0]
        self.assertIn('custom_logo', invalid_form.errors)

        storage, original_name = affiliation.custom_logo.storage, affiliation.custom_logo.name
        with self.captureOnCommitCallbacks(execute=True):
            response = self.post_admin_affiliation(affiliation, {
                'custom_logo': logo_upload('local.png'), 'network': self.federludo.pk, 'local_name': 'Wrong name',
            })
            self.assertTrue(storage.exists(original_name))
        self.assertRedirects(response, locations_list)
        affiliation.refresh_from_db()
        self.assertFalse(storage.exists(original_name))
        self.assertEqual(affiliation.network_id, self.network.pk)
        self.assertEqual(affiliation.local_name, 'Local league')

        replacement_name = affiliation.custom_logo.name
        with self.captureOnCommitCallbacks(execute=True):
            response = self.post_admin_affiliation(affiliation, {'custom_logo-clear': 'on'})
        self.assertRedirects(response, locations_list)
        affiliation.refresh_from_db()
        self.assertFalse(affiliation.custom_logo)
        self.assertFalse(storage.exists(replacement_name))

        affiliation.custom_logo = logo_upload('local.png')
        affiliation.save(update_fields=['custom_logo'])
        removed_name = affiliation.custom_logo.name
        with self.captureOnCommitCallbacks(execute=True):
            response = self.post_admin_affiliation(affiliation, {'DELETE': 'on'})
        self.assertRedirects(response, locations_list)
        self.assertFalse(self.location.network_affiliations.exists())
        self.assertFalse(storage.exists(removed_name))

    def test_view_only_affiliation_permission_does_not_allow_inline_changes(self):
        affiliation = LocationNetwork.objects.create(location=self.location, network=self.network, local_name='Read only',
                                                      custom_logo=logo_upload('local.png'))
        staff = UserProfileFactory(user__is_staff=True).user
        staff.user_permissions.set(Permission.objects.filter(content_type__app_label='webapp', codename__in=[
            'view_network', 'view_locationnetwork',
        ]))
        self.client.force_login(staff)
        filtered_url = reverse('admin:webapp_location_changelist', query={
            'network_affiliations__network__id__exact': self.network.pk,
        })
        network_change = reverse('admin:webapp_network_change', args=[self.network.pk])
        self.assertNotContains(self.client.get(network_change), f'href="{filtered_url}"')

        staff.user_permissions.add(Permission.objects.get(content_type__app_label='webapp', codename='change_location'))
        response = self.client.get(reverse('admin:webapp_location_change', args=[self.location.pk]))
        self.assertContains(response, 'Read only')
        self.assertNotContains(response, 'type="file" name="network_affiliations-0-custom_logo"')
        response = self.post_admin_affiliation(affiliation, {
            'custom_logo-clear': 'on', 'custom_logo': logo_upload('other.png'), 'DELETE': 'on',
        })
        self.assertRedirects(response, reverse('admin:webapp_location_changelist'))
        current = LocationNetwork.objects.get(pk=affiliation.pk)
        self.assertEqual(current.custom_logo.name, affiliation.custom_logo.name)
        self.assertTrue(current.custom_logo.storage.exists(current.custom_logo.name))

    def test_admin_rejects_non_web_network_urls(self):
        self.client.force_login(SuperUserProfileFactory().user)
        response = self.client.post(reverse('admin:webapp_network_add'), {
            'name': 'National league', 'website': 'ftp://league.example.org/', 'is_active': 'on', '_save': '1',
        })
        self.assertIn('website', response.context['adminform'].form.errors)
        self.assertFalse(Network.objects.filter(name='National league').exists())
