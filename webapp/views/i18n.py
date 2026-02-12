from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_POST
from django.views.i18n import set_language
from webapp.models import UserProfile


@require_POST
def custom_set_language(request):
    """
    Custom view to set language.
    Updates UserProfile if user is authenticated, then calls original set_language.
    """
    if request.user.is_authenticated:
        # Update user profile language
        lang_code = request.POST.get('language')
        if lang_code:
            try:
                profile = request.user.user_profile
                profile.preferred_language = lang_code
                profile.save(update_fields=['preferred_language'])
            except UserProfile.DoesNotExist:
                pass

    # Call original Django set_language view
    return set_language(request)
