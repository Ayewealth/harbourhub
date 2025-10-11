# listings/serializers.py
from rest_framework import serializers
from django.db import transaction
from django.utils import timezone
from drf_spectacular.utils import extend_schema_field

from .models import Listing, ListingImage, ListingDocument, ListingView
from apps.categories.models import Category
from apps.accounts.models import User


CURRENCY_SYMBOLS = {
    "NGN": "₦",
    "USD": "$",
    "EUR": "€",
    # add others as needed
}


def _unset_other_featured_for_user(user, exclude_pk=None):
    """
    Utility to unset other featured listings for a user.
    Uses a single DB UPDATE for performance and atomicity (should be called inside a transaction).
    """
    qs = Listing.objects.filter(user=user, featured=True)
    if exclude_pk:
        qs = qs.exclude(pk=exclude_pk)
    qs.update(featured=False)


class ListingImageSerializer(serializers.ModelSerializer):
    class Meta:
        model = ListingImage
        fields = ("id", "image", "caption", "is_primary", "sort_order")

    def validate_image(self, value):
        if value.size > 10 * 1024 * 1024:
            raise serializers.ValidationError("Image file too large (> 10MB)")
        allowed_types = ["image/jpeg", "image/png", "image/webp"]
        content_type = getattr(value, "content_type", None)
        if content_type and content_type not in allowed_types:
            raise serializers.ValidationError(
                "Unsupported image type. Only JPEG, PNG, and WebP are allowed."
            )
        return value


class ListingDocumentSerializer(serializers.ModelSerializer):
    class Meta:
        model = ListingDocument
        fields = ("id", "document", "name", "description",
                  "file_size", "created_at")
        read_only_fields = ("file_size", "created_at")

    def validate_document(self, value):
        if value.size > 50 * 1024 * 1024:
            raise serializers.ValidationError(
                "Document file too large (> 50MB)")
        allowed_types = [
            "application/pdf",
            "application/msword",
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            "application/vnd.ms-excel",
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            "text/plain",
            "image/jpeg",
            "image/png",
        ]
        content_type = getattr(value, "content_type", None)
        if content_type and content_type not in allowed_types:
            raise serializers.ValidationError(
                "Unsupported file type. Only PDF, DOC, DOCX, XLS, XLSX, TXT, and images are allowed."
            )
        return value


class ListingListSerializer(serializers.ModelSerializer):
    category_name = serializers.CharField(
        source="category.name", read_only=True)
    category_full_name = serializers.CharField(
        source="category.get_full_name", read_only=True)
    owner_name = serializers.CharField(
        source="user.get_full_name", read_only=True)
    owner_company = serializers.CharField(
        source="user.company", read_only=True)
    primary_image = serializers.SerializerMethodField()
    location_display = serializers.SerializerMethodField()
    currency_symbol = serializers.SerializerMethodField()

    class Meta:
        model = Listing
        fields = (
            "id", "title", "description", "category", "category_name", "category_full_name",
            "listing_type", "price", "currency", "currency_symbol", "price_unit", "negotiable",
            "location", "location_display", "country", "city",
            "contact_name", "contact_email", "contact_phone",
            "manufacturer", "model", "year", "condition",
            "status", "featured", "views_count", "inquiries_count",
            "owner_name", "owner_company", "primary_image",
            "created_at", "updated_at", "published_at",
        )
        read_only_fields = ("views_count", "inquiries_count",
                            "created_at", "updated_at", "published_at")

    @extend_schema_field(serializers.URLField(allow_null=True))
    def get_primary_image(self, obj):
        primary_image = obj.images.filter(is_primary=True).first()
        if primary_image:
            request = self.context.get("request")
            return request.build_absolute_uri(primary_image.image.url) if request else primary_image.image.url
        return None

    @extend_schema_field(serializers.CharField())
    def get_location_display(self, obj):
        parts = [p for p in [obj.city, obj.state_province, obj.country] if p]
        return ", ".join(parts) if parts else obj.location

    @extend_schema_field(serializers.CharField())
    def get_currency_symbol(self, obj):
        return CURRENCY_SYMBOLS.get(obj.currency, obj.currency)


class ListingDetailSerializer(serializers.ModelSerializer):
    category_name = serializers.CharField(
        source="category.name", read_only=True)
    category_full_name = serializers.CharField(
        source="category.get_full_name", read_only=True)
    owner = serializers.SerializerMethodField()
    images = ListingImageSerializer(many=True, read_only=True)
    documents = ListingDocumentSerializer(many=True, read_only=True)
    location_display = serializers.SerializerMethodField()
    currency_symbol = serializers.SerializerMethodField()

    class Meta:
        model = Listing
        fields = (
            "id", "title", "description", "category", "category_name", "category_full_name",
            "listing_type", "price", "currency", "currency_symbol", "price_unit", "negotiable",
            "location", "location_display", "country", "state_province", "city",
            "contact_name", "contact_email", "contact_phone",
            "manufacturer", "model", "year", "condition", "service_area",
            "status", "featured", "views_count", "inquiries_count",
            "owner", "images", "documents",
            "created_at", "updated_at", "published_at", "expires_at"
        )
        read_only_fields = ("views_count", "inquiries_count",
                            "created_at", "updated_at", "published_at")

    @extend_schema_field(serializers.DictField())
    def get_owner(self, obj):
        return {
            "id": obj.user.id,
            "name": obj.user.get_full_name(),
            "company": obj.user.company,
            "role": obj.user.role,
            "is_verified": obj.user.is_verified,
            "date_joined": obj.user.date_joined,
        }

    @extend_schema_field(serializers.CharField())
    def get_location_display(self, obj):
        parts = [p for p in [obj.city, obj.state_province, obj.country] if p]
        return ", ".join(parts) if parts else obj.location

    @extend_schema_field(serializers.CharField())
    def get_currency_symbol(self, obj):
        return CURRENCY_SYMBOLS.get(obj.currency, obj.currency)


class ListingCreateUpdateSerializer(serializers.ModelSerializer):
    """
    Creator/updater serializer.
    Owners can set featured=True; when featured=True we unset any other featured listings
    for that owner automatically.
    """
    images_data = serializers.ListField(child=serializers.ImageField(
    ), write_only=True, required=False, allow_empty=True)
    documents_data = serializers.ListField(
        child=serializers.FileField(), write_only=True, required=False, allow_empty=True)

    class Meta:
        model = Listing
        fields = (
            "title", "description", "category", "listing_type",
            "price", "currency", "price_unit", "negotiable",
            "location", "country", "state_province", "city",
            "contact_name", "contact_email", "contact_phone",
            "manufacturer", "model", "year", "condition", "service_area",
            "status", "featured", "expires_at", "images_data", "documents_data"
        )

    def validate_category(self, value):
        if not value.is_active:
            raise serializers.ValidationError(
                "Selected category is not active.")
        return value

    def validate_listing_type(self, value):
        user = self.context["request"].user
        if value == Listing.Type.SERVICE and not user.is_service_provider:
            raise serializers.ValidationError(
                "Only service providers can create service listings.")
        if value in [Listing.Type.SELL, Listing.Type.RENT, Listing.Type.LEASE] and not user.is_seller:
            raise serializers.ValidationError(
                "Only sellers can create equipment listings.")
        return value

    def validate_price(self, value):
        if value is not None and value < 0:
            raise serializers.ValidationError("Price cannot be negative.")
        return value

    def validate(self, attrs):
        request = self.context.get("request")
        if self.instance:
            if "featured" in attrs and request.user != self.instance.user:
                raise serializers.ValidationError(
                    "You can only change featured flag for your own listings.")
        if attrs.get("listing_type") == Listing.Type.SERVICE and not attrs.get("service_area"):
            attrs["service_area"] = attrs.get("location", "")
        return attrs

    @transaction.atomic
    def create(self, validated_data):
        images_data = validated_data.pop("images_data", [])
        documents_data = validated_data.pop("documents_data", [])
        request = self.context.get("request")
        owner = request.user
        validated_data["user"] = owner
        featured_flag = validated_data.pop("featured", False)

        listing = Listing.objects.create(**validated_data)
        self._create_images(listing, images_data)
        self._create_documents(listing, documents_data)

        if featured_flag:
            listing.featured = True
            listing.save(update_fields=["featured"])
            _unset_other_featured_for_user(owner, exclude_pk=listing.pk)

        return listing

    @transaction.atomic
    def update(self, instance, validated_data):
        images_data = validated_data.pop("images_data", None)
        documents_data = validated_data.pop("documents_data", None)
        featured_flag = validated_data.get("featured", None)

        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        instance.save()

        if featured_flag:
            _unset_other_featured_for_user(
                instance.user, exclude_pk=instance.pk)

        if images_data is not None:
            instance.images.all().delete()
            self._create_images(instance, images_data)

        if documents_data is not None:
            instance.documents.all().delete()
            self._create_documents(instance, documents_data)

        return instance

    def _create_images(self, listing, images_data):
        for i, image_data in enumerate(images_data):
            ListingImage.objects.create(
                listing=listing, image=image_data, is_primary=(i == 0), sort_order=i
            )

    def _create_documents(self, listing, documents_data):
        for doc_data in documents_data:
            ListingDocument.objects.create(
                listing=listing, document=doc_data, name=getattr(
                    doc_data, "name", "")
            )


class ListingStatusUpdateSerializer(serializers.ModelSerializer):
    """
    Admin/status serializer. If 'featured' is toggled here, we also unset other featured
    listings for that owner to keep consistent behavior.
    """
    admin_notes = serializers.CharField(write_only=True, required=False)

    class Meta:
        model = Listing
        fields = ("status", "featured", "admin_notes")

    def update(self, instance, validated_data):
        admin_notes = validated_data.pop("admin_notes", "")
        featured_flag = validated_data.get("featured", None)

        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        instance.save()

        if featured_flag:
            _unset_other_featured_for_user(
                instance.user, exclude_pk=instance.pk)

        if "status" in validated_data:
            from admin_panel.models import AdminActionLog
            AdminActionLog.log_action(
                admin_user=self.context["request"].user,
                action_type=f"listing_{validated_data['status']}",
                description=f"Changed listing status for {instance.id} to {validated_data['status']}",
                content_object=instance,
                extra_data={"admin_notes": admin_notes},
            )
        return instance


class MyListingSerializer(serializers.ModelSerializer):
    category_name = serializers.CharField(
        source="category.name", read_only=True)
    primary_image = serializers.SerializerMethodField()
    images_count = serializers.SerializerMethodField()
    documents_count = serializers.SerializerMethodField()
    currency_symbol = serializers.SerializerMethodField()

    class Meta:
        model = Listing
        fields = (
            "id", "title", "category_name", "listing_type", "price", "currency", "currency_symbol",
            "location", "status", "featured", "views_count", "inquiries_count",
            "primary_image", "images_count", "documents_count",
            "created_at", "updated_at", "published_at", "expires_at"
        )

    @extend_schema_field(serializers.URLField(allow_null=True))
    def get_primary_image(self, obj):
        primary_image = obj.images.filter(is_primary=True).first()
        if primary_image:
            request = self.context.get("request")
            return request.build_absolute_uri(primary_image.image.url) if request else primary_image.image.url
        return None

    @extend_schema_field(serializers.IntegerField())
    def get_images_count(self, obj):
        return obj.images.count()

    @extend_schema_field(serializers.IntegerField())
    def get_documents_count(self, obj):
        return obj.documents.count()

    @extend_schema_field(serializers.CharField())
    def get_currency_symbol(self, obj):
        return CURRENCY_SYMBOLS.get(obj.currency, obj.currency)
