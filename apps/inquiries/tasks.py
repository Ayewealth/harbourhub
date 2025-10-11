# apps/inquiries/tasks.py
from celery import shared_task
from django.template.loader import render_to_string
from django.core.mail import EmailMultiAlternatives
from django.conf import settings
from django.urls import reverse
from django.utils import timezone

from .models import Inquiry, InquiryReply


def _build_full_url(path: str) -> str:
    site = getattr(settings, "SITE_URL", "")
    return (site.rstrip("/") + "/" + path.lstrip("/")) if site else path


@shared_task
def send_inquiry_notification_task(inquiry_id: int):
    """
    Send an email to listing owner notifying them of a new inquiry.
    Renders template: 'inquiries/new_inquiry_email.html'
    """
    try:
        inquiry = Inquiry.objects.select_related(
            'listing', 'to_user', 'from_user').get(pk=inquiry_id)
    except Inquiry.DoesNotExist:
        return

    context = {
        "inquiry": inquiry,
        "site_name": getattr(settings, "SITE_NAME", "Site"),
        "support_email": getattr(settings, "SUPPORT_EMAIL", settings.DEFAULT_FROM_EMAIL),
        "inquiry_url": _build_full_url(reverse("inquiry-detail", args=[inquiry.id])),
        "current_year": timezone.now().year,
    }

    subject = f"New Inquiry: {inquiry.subject} - {context['site_name']}"
    html_body = render_to_string("emails/inquiry_notification.html", context)
    text_body = f"New inquiry about {inquiry.listing.title}. Visit {context['inquiry_url']} to reply."

    to_email = inquiry.to_user.email if inquiry.to_user and inquiry.to_user.email else None
    if not to_email:
        return

    msg = EmailMultiAlternatives(
        subject, text_body, settings.DEFAULT_FROM_EMAIL, [to_email])
    msg.attach_alternative(html_body, "text/html")
    try:
        msg.send(fail_silently=False)
    except Exception:
        # don't re-raise to avoid Celery retry storms; log in production
        pass


@shared_task
def send_reply_notification_task(reply_id: int):
    """
    Send an email to the inquirer notifying them that their inquiry was replied to.
    Renders template: 'emails/reply_notification.html'
    """
    try:
        reply = InquiryReply.objects.select_related(
            'inquiry', 'user').get(pk=reply_id)
    except InquiryReply.DoesNotExist:
        return

    inquiry = reply.inquiry
    # decide recipient: if inquirer is a registered user, use their email, otherwise use contact_email
    to_email = inquiry.from_user.email if inquiry.from_user and inquiry.from_user.email else inquiry.contact_email

    context = {
        "reply": reply,
        "inquiry": inquiry,
        "site_name": getattr(settings, "SITE_NAME", "Site"),
        "support_email": getattr(settings, "SUPPORT_EMAIL", settings.DEFAULT_FROM_EMAIL),
        "conversation_url": _build_full_url(reverse("inquiry-detail", args=[inquiry.id])),
        "current_year": timezone.now().year,
    }

    subject = f"Reply to Your Inquiry - {context['site_name']}"
    html_body = render_to_string("emails/reply_notification.html", context)
    text_body = f"A reply was posted to your inquiry about {inquiry.listing.title}. Visit {context['conversation_url']}."

    if not to_email:
        return

    msg = EmailMultiAlternatives(
        subject, text_body, settings.DEFAULT_FROM_EMAIL, [to_email])
    msg.attach_alternative(html_body, "text/html")
    try:
        msg.send(fail_silently=False)
    except Exception:
        pass
