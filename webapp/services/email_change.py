"""Change of an account's email: nothing is saved until the new address confirms."""
from django.conf import settings
from django.contrib.auth.models import User
from django.core import signing
from django.core.exceptions import ValidationError
from django.core.validators import validate_email
from django.db import transaction
from django.urls import reverse
from django.utils.translation import gettext as _

from webapp import emails

SALT = 'webapp.email_change'


def _validate_available(user, email):
    others = User.objects.exclude(pk=user.pk)
    if others.filter(email__iexact=email).exists() or others.filter(username__iexact=email).exists():
        raise ValidationError(_("This email is already in use."))


def request_change(user, new_email):
    """Sends the confirmation link to `new_email`. Raises ValidationError."""
    if not new_email:
        raise ValidationError(_("Email cannot be empty."))
    validate_email(new_email)
    # The email can become the username, which is shorter than the email field.
    if len(new_email) > User._meta.get_field('username').max_length:
        raise ValidationError(_("Enter a valid email address."))
    if new_email == user.email:
        raise ValidationError(_("This is already your email."))
    _validate_available(user, new_email)

    # Binding the current email voids older links once the email changes.
    token = signing.dumps({'user': user.pk, 'old': user.email, 'new': new_email}, salt=SALT)
    link = settings.DOMAIN_URL + reverse('email_change_confirm', kwargs={'token': token})
    emails.send_email_change_confirmation(user.user_profile, new_email, link)


def read_token(user, token):
    """The new email carried by a token valid for `user`, else None."""
    try:
        data = signing.loads(token, salt=SALT, max_age=settings.PASSWORD_RESET_TIMEOUT)
    except signing.BadSignature:
        return None
    if data['user'] != user.pk or data['old'] != user.email:
        return None
    return data['new']


def confirm_change(user, token):
    """Applies the change. Raises ValidationError."""
    new_email = read_token(user, token)
    if new_email is None:
        raise ValidationError(_("Error. Invalid verification code."))
    _validate_available(user, new_email)

    # Only sync username to email for users whose username IS their email
    # (Google and email-registered users). Telegram users keep their own username.
    if user.username == user.email:
        user.username = new_email
    user.email = new_email
    with transaction.atomic():
        user.save(update_fields=['email', 'username'])
        user.user_profile.is_email_verified = True
        user.user_profile.save(update_fields=['is_email_verified'])
