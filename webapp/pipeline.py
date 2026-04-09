import random
import string

from django.contrib.auth import get_user_model
from social_django.models import UserSocialAuth
from webapp.models import UserProfile
from django.contrib.gis.geos import Point

User = get_user_model()


def create_user_profile(backend, user, response, *args, **kwargs):
    """ Create UserProfile after social login """
    if not UserProfile.objects.filter(user=user).exists():
        if backend.name == 'telegram':
            tg_username = response.get('username', '')
            first = response.get('first_name', '')
            last = response.get('last_name', '')
            base = tg_username or ' '.join(filter(None, [first, last])) or 'user'
            suffix = ''.join(random.choices(string.digits, k=4))
            nickname = f"{base}_{suffix}"
        else:
            nickname = user.email.split('@')[0]

        UserProfile.objects.create(
            user=user,
            nickname=nickname,
            address='Change Me :)',
            city='',
            latitude='45.47506920000001',
            longitude='9.2483908',
            point=Point(45.47506920000001, 9.2483908, srid=4326),
            is_email_verified=True,
        )


def validate_social_connect(strategy, backend, user, social, *args, **kwargs):
    """
    Guard against conflicts during a connect flow (authenticated user linking a social account).
    Runs after social_user, which populates `social` and may override `user`.

    Case 1: the social UID is already linked to a different account → error.
    Case 2: connecting Google whose email is already registered to another account → error.

    Returns an HttpResponse redirect on conflict; do_complete() returns it directly.
    """
    request = strategy.request
    if not request or not request.user.is_authenticated:
        return  # login/signup flow — no checks needed

    from django.contrib import messages as django_messages
    from django.shortcuts import redirect
    from django.utils.translation import gettext as _

    # Case 1: social UID already linked to a different user
    if social and social.user_id != request.user.pk:
        django_messages.error(
            request,
            _("This %(provider)s account is already linked to a different user.")
            % {'provider': backend.name.replace('-', ' ').title()},
        )
        return redirect('user-profile-edit')

    # Case 2: Google email taken by another account
    if backend.name == 'google-oauth2' and not request.user.email:
        google_email = kwargs.get('details', {}).get('email', '')
        if google_email and User.objects.filter(email=google_email).exclude(pk=request.user.pk).exists():
            django_messages.error(
                request,
                _("The Google email address is already associated with another account."),
            )
            return redirect('user-profile-edit')


def safe_associate_user(backend, uid, user, social, *args, **kwargs):
    """
    Like social_core.pipeline.social_auth.associate_user, but if the social UID
    is already linked to a different user (race condition / double-submit), log in
    the already-linked user instead of raising AuthAlreadyAssociated.
    """
    if social and social.user != user:
        # The social account is linked to a different user — use that user.
        return {'user': social.user, 'social': social}

    if not social:
        try:
            social = UserSocialAuth.objects.get(provider=backend.name, uid=str(uid))
            return {'user': social.user, 'social': social}
        except UserSocialAuth.DoesNotExist:
            pass

    # Delegate to the standard step.
    from social_core.pipeline.social_auth import associate_user as _associate_user
    return _associate_user(backend, uid, user, social, *args, **kwargs)


def copy_email_from_google_if_missing(backend, user, response, *args, **kwargs):
    """
    When connecting Google to an account with no email (e.g. Telegram-only user),
    copy the Google email to the user record.
    Runs after user_details, which skips email because it's in the protected list.
    """
    if backend.name != 'google-oauth2':
        return
    if not user or user.email:
        return
    email = response.get('email', '')
    if email and not User.objects.filter(email=email).exclude(pk=user.pk).exists():
        user.email = email
        user.save(update_fields=['email'])


def save_language_from_state(backend, user, response, *args, **kwargs):
    """
    Salva la lingua preferita dell'utente dalla sessione.
    La lingua viene salvata nella sessione dalla view auth_with_language
    prima di avviare il flusso OAuth.
    """
    request = kwargs.get('request')
    if request:
        language = request.session.pop('social_auth_language', None)

        if language:
            # Refresh per gestire profili appena creati nel pipeline
            try:
                profile = UserProfile.objects.get(user=user)
                profile.preferred_language = language
                profile.save(update_fields=['preferred_language'])
            except UserProfile.DoesNotExist:
                pass
