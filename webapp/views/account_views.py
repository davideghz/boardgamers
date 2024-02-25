from django.shortcuts import render


def index(request, template_name='accounts/account_index.html'):
    user = request.user

    return render(request, template_name, {
        'user': user,
    })


def edit_profile(request, template_name='accounts/account_edit_profile.html'):
    user = request.user

    return render(request, template_name, {
        'user': user,
    })


def locations(request, template_name='accounts/account_locations.html'):
    user = request.user

    return render(request, template_name, {
        'user': user,
    })


def tables(request, template_name='accounts/account_tables.html'):
    user = request.user

    return render(request, template_name, {
        'user': user,
    })


def notifications(request, template_name='accounts/account_notifications.html'):
    user = request.user

    return render(request, template_name, {
        'user': user,
    })
