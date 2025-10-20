# accounts/emails.py
"""
Email handling for user authentication and notifications
"""
from django.core.mail import send_mail, EmailMultiAlternatives
from django.template.loader import render_to_string
from django.conf import settings
from django.utils import timezone
from django.urls import reverse
import logging

logger = logging.getLogger(__name__)


class EmailService:
    """Service class for handling email operations"""

    @staticmethod
    def send_welcome_email(user):
        """Send welcome email to new user"""
        if not settings.SEND_WELCOME_EMAIL:
            return False

        try:
            subject = f"Welcome to {settings.SITE_NAME}!"

            # Context for template
            context = {
                'user': user,
                'site_name': settings.SITE_NAME,
                'site_url': settings.SITE_URL,
                'login_url': f"{settings.SITE_URL}/",
                'support_email': settings.SUPPORT_EMAIL,
                'current_year': timezone.now().year,
            }

            # Render HTML template
            html_content = render_to_string('emails/welcome.html', context)

            # Create email
            email = EmailMultiAlternatives(
                subject=subject,
                body=f"Welcome to {settings.SITE_NAME}!\n\nYour account has been successfully created.",
                from_email=settings.DEFAULT_FROM_EMAIL,
                to=[user.email],
            )
            email.attach_alternative(html_content, "text/html")

            # Send email
            email.send()

            logger.info(f"Welcome email sent to {user.email}")
            return True

        except Exception as e:
            logger.error(
                f"Failed to send welcome email to {user.email}: {str(e)}")
            return False

    @staticmethod
    def send_otp_email(email, code, purpose="registration", ttl_minutes=30):
        """Send OTP email for registration or login"""
        try:
            if purpose == "registration":
                subject = f"Your {settings.SITE_NAME} Registration Code"
                template_name = "emails/otp_registration.html"
            else:
                subject = f"Your {settings.SITE_NAME} Login Code"
                template_name = "emails/otp_login.html"

            context = {
                "code": code,
                "purpose": purpose,
                "site_name": settings.SITE_NAME,
                "site_url": settings.SITE_URL,
                "ttl_minutes": ttl_minutes,
                "support_email": settings.SUPPORT_EMAIL,
                "current_year": timezone.now().year,
            }

            html_content = render_to_string(template_name, context)
            text_content = f"""
            Your {settings.SITE_NAME} {purpose.capitalize()} Code

            Code: {code}
            This code expires in {ttl_minutes} minutes.
            If you did not request this code, please ignore this email.
            """

            email_msg = EmailMultiAlternatives(
                subject=subject,
                body=text_content,
                from_email=settings.DEFAULT_FROM_EMAIL,
                to=[email],
            )
            email_msg.attach_alternative(html_content, "text/html")
            email_msg.send()

            logger.info(f"OTP email ({purpose}) sent to {email}")
            return True

        except Exception as e:
            logger.error(f"Failed to send OTP email to {email}: {str(e)}")
            return False

    @staticmethod
    def send_password_reset_email(user, reset_token):
        """Send password reset email"""
        try:
            subject = f"Reset Your {settings.SITE_NAME} Password"

            # Generate reset URL
            reset_url = f"{settings.SITE_URL}/reset-password?token={reset_token.token}"

            # Context for template
            context = {
                'user': user,
                'site_name': settings.SITE_NAME,
                'site_url': settings.SITE_URL,
                'reset_url': reset_url,
                'reset_token': reset_token.token,
                'expiry_hours': 24,
                'support_email': settings.SUPPORT_EMAIL,
                'current_year': timezone.now().year,
            }

            # Render HTML template
            html_content = render_to_string(
                'emails/password_reset.html', context)

            # Plain text fallback
            text_content = f"""
            Reset Your {settings.SITE_NAME} Password
            
            We received a request to reset your password.
            
            To reset your password, click the link below:
            {reset_url}
            
            This link will expire in 24 hours for security purposes.
            
            If you didn't request this password reset, please ignore this email.
            
            Need help? Contact our support team at {settings.SUPPORT_EMAIL}
            """

            # Create email
            email = EmailMultiAlternatives(
                subject=subject,
                body=text_content,
                from_email=settings.DEFAULT_FROM_EMAIL,
                to=[user.email],
            )
            email.attach_alternative(html_content, "text/html")

            # Send email
            email.send()

            logger.info(f"Password reset email sent to {user.email}")
            return True

        except Exception as e:
            logger.error(
                f"Failed to send password reset email to {user.email}: {str(e)}")
            return False

    @staticmethod
    def send_password_reset_confirmation_email(user):
        """Send password reset confirmation email"""
        try:
            subject = f"Password Reset Successful - {settings.SITE_NAME}"

            # Context for template
            context = {
                'user': user,
                'site_name': settings.SITE_NAME,
                'site_url': settings.SITE_URL,
                'login_url': f"{settings.SITE_URL}/login/",
                'reset_date': timezone.now().strftime('%B %d, %Y'),
                'reset_time': timezone.now().strftime('%I:%M %p'),
                'support_email': settings.SUPPORT_EMAIL,
                'security_email': getattr(settings, 'SECURITY_EMAIL', settings.SUPPORT_EMAIL),
                'current_year': timezone.now().year,
            }

            # Render HTML template
            html_content = render_to_string(
                'emails/password_reset_confirmation.html', context)

            # Plain text fallback
            text_content = f"""
            Password Reset Successful - {settings.SITE_NAME}
            
            Your password has been successfully updated.
            
            Your {settings.SITE_NAME} account password was successfully changed on {context['reset_date']} at {context['reset_time']}.
            
            If you didn't make this change, please contact our security team immediately at {context['security_email']}
            
            You can now log in with your new password at: {context['login_url']}
            """

            # Create email
            email = EmailMultiAlternatives(
                subject=subject,
                body=text_content,
                from_email=settings.DEFAULT_FROM_EMAIL,
                to=[user.email],
            )
            email.attach_alternative(html_content, "text/html")

            # Send email
            email.send()

            logger.info(
                f"Password reset confirmation email sent to {user.email}")
            return True

        except Exception as e:
            logger.error(
                f"Failed to send password reset confirmation email to {user.email}: {str(e)}")
            return False

    @staticmethod
    def send_inquiry_notification_email(inquiry):
        """Send notification email when inquiry is received"""
        if not settings.SEND_INQUIRY_NOTIFICATIONS:
            return False

        try:
            subject = f"New Inquiry: {inquiry.subject}"

            # Context for template
            context = {
                'inquiry': inquiry,
                'listing': inquiry.listing,
                'site_name': settings.SITE_NAME,
                'site_url': settings.SITE_URL,
                'inquiry_url': f"{settings.SITE_URL}/dashboard/inquiries/{inquiry.id}/",
                'support_email': settings.SUPPORT_EMAIL,
                'current_year': timezone.now().year,
            }

            # Render HTML template
            html_content = render_to_string(
                'emails/inquiry_received.html', context)

            # Plain text fallback
            text_content = f"""
            New Inquiry: {inquiry.subject}
            
            Hello {inquiry.to_user.first_name},
            
            You have received a new inquiry for your listing: {inquiry.listing.title}
            
            From: {inquiry.contact_name} ({inquiry.contact_email})
            Company: {inquiry.contact_company}
            
            Message:
            {inquiry.message}
            
            You can view and reply to this inquiry at: {context['inquiry_url']}
            """

            # Create email
            email = EmailMultiAlternatives(
                subject=subject,
                body=text_content,
                from_email=settings.DEFAULT_FROM_EMAIL,
                to=[inquiry.to_user.email],
            )
            email.attach_alternative(html_content, "text/html")

            # Send email
            email.send()

            logger.info(
                f"Inquiry notification email sent to {inquiry.to_user.email}")
            return True

        except Exception as e:
            logger.error(
                f"Failed to send inquiry notification email: {str(e)}")
            return False
