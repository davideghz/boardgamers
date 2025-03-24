from django.conf import settings
from django.core.mail import send_mail
from django.template.loader import render_to_string

from webapp import messages
from webapp.models import UserProfile


def send_user_email_verification_code(user_profile):
    context = {
        'nickname': user_profile.nickname,
        'button_href': UserProfile.get_activation_link(user_profile.user),
    }
    text_content = render_to_string('emails/email_verification_code.html', context=context)
    html_content = render_to_string('emails/email_verification_code_html.html', context=context)
    send_mail(
        messages.EMAIL_SUBJECT_VERIFICATION_CODE,
        text_content,
        settings.DEFAULT_FROM_EMAIL,
        [user_profile.user.email],
        html_message=html_content,
    )


def send_admin_contact_message(cleaned_data):
    context = {
        'name': cleaned_data.name,
        'email': cleaned_data.email,
        'message': cleaned_data.message,
    }
    text_content = render_to_string('emails/email_contacts.html', context=context)
    html_content = render_to_string('emails/email_contacts_html.html', context=context)
    send_mail(
        messages.EMAIL_SUBJECT_CONTACTS,
        text_content,
        settings.DEFAULT_FROM_EMAIL,
        ['davideghz@gmail.com'],
        html_message=html_content,
    )
