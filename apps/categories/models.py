from django.db import models
from django.utils.translation import gettext_lazy as _
from django.utils.text import slugify
from mptt.models import MPTTModel, TreeForeignKey


class Category(MPTTModel):
    """Hierarchical category model using MPTT for nested categories"""

    name = models.CharField(
        max_length=100,
        unique=True,
        db_index=True,   # ✅ improves lookup speed
        help_text=_('Category name')
    )
    slug = models.SlugField(
        max_length=120,   # ✅ slightly longer to avoid collisions
        unique=True,
        db_index=True,
        help_text=_('URL-friendly category name')
    )
    parent = TreeForeignKey(
        'self',
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='children',
        help_text=_('Parent category for nesting')
    )
    description = models.TextField(
        blank=True,
        help_text=_('Category description')
    )
    icon = models.CharField(
        max_length=100,
        blank=True,
        help_text=_('Icon class (CSS) or image path')
    )
    is_active = models.BooleanField(
        default=True,
        help_text=_('Whether this category is active')
    )
    sort_order = models.PositiveIntegerField(
        default=0,
        db_index=True,   # ✅ speeds up ordering
        help_text=_('Sort order for display')
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class MPTTMeta:
        order_insertion_by = ['sort_order', 'name']

    class Meta:
        db_table = 'categories'
        verbose_name = _('Category')
        verbose_name_plural = _('Categories')
        ordering = ['sort_order', 'name']
        indexes = [  # ✅ extra database indexing
            models.Index(fields=['is_active']),
            models.Index(fields=['slug']),
        ]

    def __str__(self):
        return self.get_full_name()

    def get_full_name(self):
        """Get full category path (e.g., 'Equipment > Drilling > Bits')"""
        names = [ancestor.name for ancestor in self.get_ancestors()] + \
            [self.name]
        return ' > '.join(names)

    def get_listing_count(self):
        """Get count of active listings in this category and its descendants"""
        from apps.listings.models import Listing
        category_ids = [self.pk] + \
            list(self.get_descendants().values_list('pk', flat=True))
        return Listing.objects.filter(
            category_id__in=category_ids,
            status=Listing.Status.PUBLISHED
        ).count()

    @property
    def has_children(self):
        return self.children.exists()

    def save(self, *args, **kwargs):
        """Auto-generate slug if missing, ensure uniqueness"""
        if not self.slug:
            base_slug = slugify(self.name)
            slug = base_slug
            counter = 1
            # ✅ make sure slug is unique
            while Category.objects.filter(slug=slug).exclude(pk=self.pk).exists():
                slug = f"{base_slug}-{counter}"
                counter += 1
            self.slug = slug
        super().save(*args, **kwargs)
