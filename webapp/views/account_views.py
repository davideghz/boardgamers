from django.shortcuts import render


def index(request, template_name='accounts/account-index.html'):
    user = request.user

    return render(request, template_name, {
        'user': user,
    })
