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
