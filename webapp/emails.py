from django.conf import settings
from django.urls import reverse
from django.core.mail import send_mail
from django.template.loader import render_to_string

from webapp import messages
from webapp.models import UserProfile


def send_user_email_verification_code(user_profile):
    """
    Sends an email to the user with a verification code for account activation.

    :param user_profile: The UserProfile instance of the user receiving the email.
    """
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
    """
    Sends an email to the admin with a contact message submitted by a user.

    :param cleaned_data: A dictionary containing the name, email, and message from the contact form.
    """
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
    if not user_profile.user.email:
        return
    """
    Sends a notification email to the user about a newly created game table.

    :param user_profile: The UserProfile instance of the user receiving the email.
    :param new_table: The new table instance containing details about the new table.
    """
    table_url = settings.DOMAIN_URL + reverse('table-detail', kwargs={'slug': new_table.slug})

    context = {
        'user_profile': user_profile,
        'title': new_table.title,
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


def send_email_notification_deleted_table(user_profile, deleted_table):
    if not user_profile.user.email:
        return
    """
    Sends a notification email to the user about a deleted game table.

    :param user_profile: The UserProfile instance of the user receiving the email.
    :param new_table: The new table instance containing details about the deleted table.
    """
    if deleted_table.event_id:
        table_url = settings.DOMAIN_URL + reverse('event_detail', kwargs={'slug': deleted_table.event.slug})
        location_name = deleted_table.event.name
    else:
        table_url = settings.DOMAIN_URL + reverse('location-detail', kwargs={'slug': deleted_table.location.slug})
        location_name = deleted_table.location.name

    context = {
        'user_profile': user_profile,
        'title': deleted_table.title,
        'game': deleted_table.game,
        'date': deleted_table.date,
        'location_name': location_name,
        'button_href': table_url,
    }
    text_content = render_to_string('emails/email_notification_deleted_table.html', context=context)
    html_content = render_to_string('emails/email_notification_deleted_table_html.html', context=context)

    send_mail(
        messages.EMAIL_SUBJECT_NOTIFICATION_DELETED_TABLE,
        text_content,
        settings.DEFAULT_FROM_EMAIL,
        [user_profile.user.email],
        html_message=html_content,
    )


def send_batch_notification_new_messages(user_profile, total_unread, table_details):
    if not user_profile.user.email:
        return
    """
    Sends a batch email notification to the user about unread messages.

    :param user_profile: The UserProfile instance of the user receiving the email.
    :param total_unread: The total number of unread messages.
    :param table_details: A list of details about tables with unread messages.
    """
    subject = f"Hai {total_unread} nuovi messaggi non letti"
    context = {
        'user_profile': user_profile,
        'total_unread': total_unread,
        'table_details': table_details,
    }
    text_content = render_to_string('emails/email_batch_notification_new_comments.html', context=context)
    html_content = render_to_string('emails/email_batch_notification_new_comments_html.html', context=context)

    send_mail(
        subject=subject,
        message=text_content,
        from_email=settings.DEFAULT_FROM_EMAIL,
        recipient_list=[user_profile.user.email],
        html_message=html_content,
        fail_silently=False,
    )

