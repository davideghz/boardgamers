from django.contrib.auth.decorators import login_required
from django.shortcuts import render

from webapp.forms import UserProfileForm


@login_required
def index(request, template_name='accounts/account_index.html'):
    user = request.user

    return render(request, template_name, {
        'user': user,
    })


@login_required
def edit_profile(request, template_name='accounts/account_edit_profile.html'):
    user = request.user
    form = UserProfileForm

    return render(request, template_name, {
        'user': user,
        'form': form
    })


@login_required
def locations(request, template_name='accounts/account_locations.html'):
    user = request.user
    locations = user.user_profile.locations.all()

    return render(request, template_name, {
        'user': user,
        'locations': locations,
    })


@login_required
def tables(request, template_name='accounts/account_tables.html'):
    user = request.user
    created_tables = user.user_profile.created_tables.all()
    joined_tables = user.user_profile.joined_tables.all()

    return render(request, template_name, {
        'user': user,
        'created_tables': created_tables,
        'joined_tables': joined_tables,
    })


@login_required
def notifications(request, template_name='accounts/account_notifications.html'):
    user = request.user

    return render(request, template_name, {
        'user': user,
    })
