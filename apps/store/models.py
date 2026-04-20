from django.db import models

from apps.accounts.models import User
from django.utils.translation import gettext_lazy as _
from apps.categories.models import Category
# Create your models here.


class Store(models.Model):
    user = models.OneToOneField(
        User, on_delete=models.CASCADE, limit_choices_to={'role': User.Role.SELLER}, related_name='store', help_text=_('The user who owns the store'))
    slug = models.SlugField(max_length=255, unique=True,
                            help_text=_('The slug of the store'))
    categories = models.ManyToManyField(
        Category, limit_choices_to={'is_active': True}, related_name='stores', help_text=_('The categories of the store'))
    name = models.CharField(
        max_length=255, help_text=_('The name of the store'))
    description = models.TextField(
        blank=True, null=True, help_text=_('The description of the store'))
    banner_image = models.ImageField(
        upload_to='store/banners/', blank=True, null=True, help_text=_('The banner image of the store'))
    logo = models.ImageField(upload_to='store/logos/',
                             blank=True, null=True, help_text=_('The logo of the store'))
    email = models.EmailField(
        max_length=255, blank=True, null=True, help_text=_('The email of the store'))
    phone = models.CharField(
        max_length=20, blank=True, null=True, help_text=_(
            'The phone number of the store'))
    address = models.TextField(
        blank=True, null=True, help_text=_('The address of the store'))
    city = models.CharField(
        max_length=100, blank=True, null=True, help_text=_('The city of the store'))
    state = models.CharField(
        max_length=100, blank=True, null=True, help_text=_('The state of the store'))
    country = models.CharField(
        max_length=100, blank=True, null=True, help_text=_('The country of the store'))
    zip_code = models.CharField(
        max_length=20, blank=True, null=True, help_text=_('The zip code of the store'))
    policy = models.TextField(help_text=_('The policy of the store'))

    is_verified = models.BooleanField(
        default=False, help_text=_('Whether the store is verified'))
    is_active = models.BooleanField(
        default=True, help_text=_('Whether the store is active'))
    is_published = models.BooleanField(
        default=False, help_text=_('Whether the store is published'))
    updated_at = models.DateTimeField(
        auto_now=True, help_text=_('The last updated time of the store'))
    created_at = models.DateTimeField(
        auto_now_add=True, help_text=_('The creation time of the store'))

    def __str__(self):
        return self.name
