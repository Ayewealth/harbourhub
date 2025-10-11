# apps/listings/signals.py
from django.db.models.signals import post_save
from django.dispatch import receiver
from .models import ListingImage


@receiver(post_save, sender=ListingImage)
def ensure_single_primary_image(sender, instance, created, **kwargs):
    if instance.is_primary:
        # unset other images
        sender.objects.filter(listing=instance.listing, is_primary=True).exclude(
            pk=instance.pk).update(is_primary=False)
