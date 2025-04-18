from django.conf import settings
from django.urls import reverse
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
        'name': cleaned_data.get('name'),
        'email': cleaned_data.get('email'),
        'message': cleaned_data.get('message'),
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


def send_notification_new_table(user_profile, new_table):
    table_url = settings.DOMAIN_URL + reverse('table-detail', kwargs={'slug': new_table.slug})

    context = {
        'user_profile': user_profile,
        'game': new_table.game,
        'date': new_table.date,
        'time': new_table.time,
        'location_name': new_table.location.name if new_table.location else "Location non disponibile",
        'button_href': table_url,
    }
    text_content = render_to_string('emails/email_notification_new_table.html', context=context)
    html_content = render_to_string('emails/email_notification_new_table_html.html', context=context)

    send_mail(
        messages.EMAIL_SUBJECT_NOTIFICATION_NEW_TABLE,
        text_content,
        settings.DEFAULT_FROM_EMAIL,
        [user_profile.user.email],
        html_message=html_content,
    )
