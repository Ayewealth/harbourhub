from django.db.models.signals import post_save
from django.dispatch import receiver
from apps.store.models import Store
from .models import VendorWallet

@receiver(post_save, sender=Store)
def create_vendor_wallet(sender, instance, created, **kwargs):
    if created:
        VendorWallet.objects.get_or_create(
            user=instance.user,
            store=instance,
            currency='NGN'
        )
