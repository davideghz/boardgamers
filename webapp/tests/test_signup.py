from unittest.mock import patch

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse
from django_recaptcha.fields import ReCaptchaField

from webapp.models import UserProfile

PASSWORD = 'xK9#mQ2$vL7pZw'


@patch.object(ReCaptchaField, 'validate', lambda self, value: None)
class SignupViewTest(TestCase):
    def _post(self, follow=False, **overrides):
        data = {
            'email': 'mario@example.com',
            'password1': PASSWORD,
            'password2': PASSWORD,
            'nickname': 'mario',
            'address': 'Via Roma 1, Milano',
            'city': 'Milano',
            'latitude': '45.4642',
            'longitude': '9.1900',
            'g-recaptcha-response': 'token',
            **overrides,
        }
        return self.client.post(reverse('signup'), data, follow=follow)

    def test_creates_user_with_email_as_username(self):
        response = self._post()

        self.assertRedirects(response, reverse('login'))
        user = User.objects.get()
        self.assertEqual(user.email, 'mario@example.com')
        self.assertEqual(user.username, 'mario@example.com')
        self.assertTrue(user.check_password(PASSWORD))

    def test_login_page_confirms_the_signup(self):
        response = self._post(follow=True)

        confirmation = list(response.context['messages'])
        self.assertEqual(len(confirmation), 1)
        self.assertContains(response, str(confirmation[0]))

    def test_saves_city_and_coordinates_on_the_profile(self):
        self._post()

        profile = UserProfile.objects.get()
        self.assertEqual(profile.city, 'Milano')
        self.assertEqual(profile.latitude, '45.4642')
        self.assertEqual(profile.longitude, '9.1900')
        self.assertAlmostEqual(profile.point.y, 45.4642)
        self.assertAlmostEqual(profile.point.x, 9.19)

    def test_rejects_blank_email(self):
        for email in ('', '   '):
            with self.subTest(email=email):
                response = self._post(email=email)

                self.assertEqual(response.status_code, 200)
                self.assertIn('email', response.context['form'].errors)
                self.assertFalse(User.objects.exists())

    def test_rolls_back_the_user_if_the_profile_cannot_be_saved(self):
        with patch.object(UserProfile, 'save', side_effect=RuntimeError):
            with self.assertRaises(RuntimeError):
                self._post()

        self.assertFalse(User.objects.exists())

    def test_form_markup_requires_email_and_submits_coordinates(self):
        content = self.client.get(reverse('signup')).content.decode()

        email_start = content.index('name="email"')
        self.assertIn('required', content[email_start:content.index('>', email_start)])

        # Hidden inputs only get submitted when they sit in the signup form.
        signup_form = content.rindex('<form', 0, email_start)
        for name in ('city', 'latitude', 'longitude'):
            field = content.index(f'name="{name}"')
            self.assertEqual(content.rindex('<form', 0, field), signup_form)
            self.assertNotIn('</form>', content[signup_form:field])
