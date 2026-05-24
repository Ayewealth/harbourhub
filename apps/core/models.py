from django.db import models
from django.conf import settings
# Create your models here.


class UserSearch(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='searches'
    )
    query = models.CharField(max_length=255)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'user_searches'
        ordering = ['-created_at']

    def __str__(self):
        return self.query


class Feedback(models.Model):
    """Model to store user feedback for static FAQ/Legal pages."""
    class Choice(models.TextChoices):
        HELPFUL = "helpful", "Helpful"
        NOT_HELPFUL = "not_helpful", "Not Helpful"

    topic = models.CharField(max_length=255)
    feedback = models.CharField(max_length=20, choices=Choice.choices)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="feedbacks"
    )
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "page_feedbacks"
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.topic} - {self.feedback}"
