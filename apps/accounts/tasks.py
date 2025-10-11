# apps/accounts/tasks.py
import logging
from celery import shared_task
from django.conf import settings
from django.utils import timezone
from django.core.mail import send_mail

from .models import PasswordResetToken, User, VerificationRequest
from .emails import EmailService

logger = logging.getLogger(__name__)


@shared_task(bind=True, max_retries=3, default_retry_delay=10)
def send_welcome_email_task(self, user_id):
    try:
        user = User.objects.get(pk=user_id)
        EmailService.send_welcome_email(user)
        logger.info("Sent welcome email to %s", user.email)
    except User.DoesNotExist:
        logger.warning(
            "send_welcome_email_task: user %s does not exist", user_id)
    except Exception as exc:
        logger.exception("send_welcome_email_task failed: %s", exc)
        raise self.retry(exc=exc)


@shared_task(bind=True, max_retries=3, default_retry_delay=10)
def send_password_reset_email_task(self, reset_token_id):
    try:
        token = PasswordResetToken.objects.get(pk=reset_token_id)
        EmailService.send_password_reset_email(token.user, token)
        logger.info("Sent password reset email to %s", token.user.email)
    except PasswordResetToken.DoesNotExist:
        logger.warning(
            "send_password_reset_email_task: token %s does not exist", reset_token_id)
    except Exception as exc:
        logger.exception("send_password_reset_email_task failed: %s", exc)
        raise self.retry(exc=exc)


@shared_task(bind=True, max_retries=3, default_retry_delay=10)
def send_password_reset_confirmation_email_task(self, user_id):
    try:
        user = User.objects.get(pk=user_id)
        EmailService.send_password_reset_confirmation_email(user)
        logger.info("Sent password reset confirmation to %s", user.email)
    except User.DoesNotExist:
        logger.warning(
            "send_password_reset_confirmation_email_task: user %s not found", user_id)
    except Exception as exc:
        logger.exception(
            "send_password_reset_confirmation_email_task failed: %s", exc)
        raise self.retry(exc=exc)


@shared_task
def notify_admins_verification_request(request_id, user_email):
    """Notify admins when a new verification request is submitted."""
    try:
        verification_request = VerificationRequest.objects.get(id=request_id)
        subject = "New Verification Request Submitted"
        message = (
            f"A new service provider verification request was submitted by {user_email}.\n\n"
            f"Company: {verification_request.company_name}\n"
            f"Status: {verification_request.status}\n\n"
            f"View in admin panel for review."
        )

        admin_emails = list(User.objects.filter(
            is_staff=True).values_list('email', flat=True))
        if admin_emails:
            send_mail(subject, message,
                      settings.DEFAULT_FROM_EMAIL, admin_emails)

        return f"Sent notification to {len(admin_emails)} admin(s)"
    except VerificationRequest.DoesNotExist:
        return "Verification request not found"
