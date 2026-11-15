from io import BytesIO
from tempfile import TemporaryDirectory

from django.core.files.uploadedfile import SimpleUploadedFile
from django.db.models import ProtectedError
from django.test import TestCase, override_settings
from django.urls import reverse
from PIL import Image

from webapp.factories import LocationFactory, SuperUserProfileFactory, UserProfileFactory
from webapp.models import LocationNetwork, Network


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

    def test_manager_adds_edits_and_removes_affiliation(self):
        self.client.force_login(self.manager.user)
        manage_index = self.client.get(reverse('location-manage', args=[self.location.slug]))
        self.assertContains(manage_index, self.manage_url)
        add_response = self.client.post(self.manage_url, {'network': self.network.pk, 'local_name': 'TdG Vicenza'})
        self.assertRedirects(add_response, self.manage_url)
        affiliation = self.location.network_affiliations.get(network=self.network)
        self.assertEqual(affiliation.local_name, 'TdG Vicenza')

        edit_url = reverse('location-edit-network', args=[self.location.slug, affiliation.pk])
        response = self.client.post(edit_url, {'local_name': ' TdG VI ', 'custom_logo': logo_upload('local.png')})
        self.assertRedirects(response, self.manage_url)
        affiliation.refresh_from_db()
        self.assertEqual(affiliation.local_name, 'TdG VI')
        with Image.open(affiliation.custom_logo) as logo:
            self.assertEqual(logo.size, (512, 256))
            self.assertEqual(logo.getpixel((0, 0))[3], 128)

        response = self.client.post(edit_url, {'local_name': '', 'custom_logo-clear': 'on'})
        self.assertRedirects(response, self.manage_url)
        affiliation.refresh_from_db()
        self.assertEqual(affiliation.display_name, self.network.name)
        self.assertFalse(affiliation.custom_logo)

        remove_url = reverse('location-remove-network', args=[self.location.slug, affiliation.pk])
        self.assertEqual(self.client.get(remove_url).status_code, 405)
        self.assertRedirects(self.client.post(remove_url), self.manage_url)
        self.assertFalse(self.location.network_affiliations.exists())

    def test_owner_can_declare_two_networks_without_creating_duplicates(self):
        self.client.force_login(self.owner.user)
        for network in (self.network, self.federludo):
            self.assertRedirects(self.client.post(self.manage_url, {'network': network.pk}), self.manage_url)
        response = self.client.post(self.manage_url, {'network': self.network.pk})
        self.assertIn('network', response.context['form'].errors)
        self.assertCountEqual(self.location.networks.all(), [self.network, self.federludo])

    def test_permissions_apply_to_mutations_and_to_the_specific_location(self):
        affiliation = LocationNetwork.objects.create(location=self.location, network=self.network)
        edit_url = reverse('location-edit-network', args=[self.location.slug, affiliation.pk])
        remove_url = reverse('location-remove-network', args=[self.location.slug, affiliation.pk])
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

    def test_admin_catalogue_logo_slug_and_affiliation_moderation(self):
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

        affiliation = LocationNetwork.objects.create(location=self.location, network=network, local_name='Local league',
                                                      custom_logo='location-network-logos/local.png')
        network_change = reverse('admin:webapp_network_change', args=[network.pk])
        affiliation_list = reverse('admin:webapp_locationnetwork_changelist', query={'network__id__exact': network.pk})
        self.assertContains(self.client.get(network_change), affiliation_list)
        self.assertContains(self.client.get(affiliation_list), 'Local league')

        response = self.client.post(network_change, {
            'name': 'Renamed league', 'website': website, 'is_active': 'on', '_save': '1',
        })
        self.assertRedirects(response, network_list)
        network.refresh_from_db()
        self.assertEqual(network.slug, 'national-league')
        self.assertTrue(network.logo)
        self.assertEqual(network.website, website)

        affiliation_change = reverse('admin:webapp_locationnetwork_change', args=[affiliation.pk])
        response = self.client.post(affiliation_change, {'custom_logo-clear': 'on', '_save': '1'})
        self.assertRedirects(response, reverse('admin:webapp_locationnetwork_changelist'))
        affiliation.refresh_from_db()
        self.assertFalse(affiliation.custom_logo)
        self.assertEqual(affiliation.local_name, 'Local league')

    def test_admin_rejects_non_web_network_urls(self):
        self.client.force_login(SuperUserProfileFactory().user)
        response = self.client.post(reverse('admin:webapp_network_add'), {
            'name': 'National league', 'website': 'ftp://league.example.org/', 'is_active': 'on', '_save': '1',
        })
        self.assertIn('website', response.context['adminform'].form.errors)
        self.assertFalse(Network.objects.filter(name='National league').exists())
