from django.contrib.auth import get_user_model
from webapp.models import UserProfile
from django.contrib.gis.geos import Point

User = get_user_model()


def create_user_profile(backend, user, response, *args, **kwargs):
    """ Create UserProfile after social login """
    if not UserProfile.objects.filter(user=user).exists():
        profile = UserProfile.objects.create(
            user=user,
            nickname=user.email.split('@')[0],  # set nickname from email
            address='Change Me :)',
            city='',
            latitude='45.47506920000001',
            longitude='9.2483908',
            point=Point(45.47506920000001, 9.2483908, srid=4326),
            is_email_verified=True  # Force True
        )
        profile.save()


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
