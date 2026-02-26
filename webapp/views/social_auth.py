from social_django.views import auth as social_auth_view


def auth_with_language(request, backend):
    """
    Wrapper attorno alla view auth di social_django.
    Salva la lingua corrente nella sessione prima di avviare il flusso OAuth,
    così il pipeline può recuperarla dopo il callback.
    """
    lang = request.GET.get('lang')
    if lang:
        request.session['social_auth_language'] = lang
    return social_auth_view(request, backend)
