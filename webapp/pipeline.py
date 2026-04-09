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
