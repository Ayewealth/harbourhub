from django.db import models as dj_models
from django.db.models import Count, Q, Avg, Sum, F
from django.utils import timezone
from datetime import timedelta
from rest_framework.viewsets import ViewSet
from rest_framework.response import Response
from rest_framework.decorators import action
from rest_framework.permissions import IsAdminUser
from drf_spectacular.utils import extend_schema, extend_schema_field
from django.core.cache import cache

from django.contrib.auth import get_user_model
from apps.listings.models import Listing
from apps.inquiries.models import Inquiry
from apps.categories.models import Category

from .serializers import (
    AnalyticsOverviewSerializer,
    UserAnalyticsSerializer,
    ListingAnalyticsSerializer,
    ConversionAnalyticsSerializer,
    CategorySummarySerializer,
)

User = get_user_model()


class AnalyticsViewSet(ViewSet):
    """Comprehensive analytics and reporting system."""
    permission_classes = [IsAdminUser]
    serializer_class = AnalyticsOverviewSerializer

    @extend_schema(
        summary="Get platform statistics",
        description="Comprehensive platform statistics for the admin dashboard.",
        responses=AnalyticsOverviewSerializer,
    )
    def list(self, request):
        """Get comprehensive platform statistics."""
        if getattr(self, "swagger_fake_view", False):
            return Response({})  # Safe for schema generation

        cached_data = cache.get("analytics:overview_snapshot")
        if cached_data:
            return Response(cached_data)

        now = timezone.now()
        last_30_days = now - timedelta(days=30)
        last_7_days = now - timedelta(days=7)

        user_stats = self._get_user_statistics(last_30_days, last_7_days)
        listing_stats = self._get_listing_statistics(last_30_days, last_7_days)
        inquiry_stats = self._get_inquiry_statistics(last_30_days, last_7_days)
        category_stats = self._get_category_statistics()
        business_stats = self._get_business_statistics(last_30_days)

        payload = {
            "user_stats": user_stats,
            "listing_stats": listing_stats,
            "inquiry_stats": inquiry_stats,
            "category_stats": category_stats,
            "business_stats": business_stats,
            "generated_at": now,
        }

        cache.set("analytics:overview_snapshot", payload, 300)
        serializer = AnalyticsOverviewSerializer(
            payload, context={"request": request})
        return Response(serializer.data)

    # ───────────────────────────────
    # USER ANALYTICS
    # ───────────────────────────────
    @extend_schema(
        summary="Get user analytics",
        description="Provides user growth, role distribution, and top users.",
        responses=UserAnalyticsSerializer,
    )
    @action(detail=False, methods=["get"])
    def user_analytics(self, request):
        """User-based analytics (growth, distribution, top users)."""
        if getattr(self, "swagger_fake_view", False):
            return Response({})

        user_growth = (
            User.objects.extra(
                select={"month": "date_trunc('month', date_joined)"})
            .values("month")
            .annotate(count=Count("id"))
            .order_by("month")
        )

        role_distribution = User.objects.values("role").annotate(
            count=Count("id"),
            active_count=Count(
                "id", filter=Q(last_login__gte=timezone.now() - timedelta(days=30))
            ),
        )

        top_users = (
            User.objects.annotate(
                listings_count=Count("listings"),
                inquiries_sent_count=Count("sent_inquiries"),
                inquiries_received_count=Count("received_inquiries"),
            )
            .order_by("-listings_count")[:10]
        )

        return Response(
            {
                "user_growth": list(user_growth),
                "role_distribution": list(role_distribution),
                "top_users": UserAnalyticsSerializer(
                    top_users, many=True, context={"request": request}
                ).data,
            }
        )

    # ───────────────────────────────
    # LISTING ANALYTICS
    # ───────────────────────────────
    @extend_schema(
        summary="Get listing analytics",
        description="Returns listing performance metrics, trends, and category data.",
        responses=ListingAnalyticsSerializer,
    )
    @action(detail=False, methods=["get"])
    def listing_analytics(self, request):
        """Listing analytics (performance, trends, categories)."""
        if getattr(self, "swagger_fake_view", False):
            return Response({})

        listing_performance = Listing.objects.aggregate(
            avg_views=Avg("views_count"),
            avg_inquiries=Avg("inquiries_count"),
            total_views=Sum("views_count"),
            total_inquiries=Sum("inquiries_count"),
        )

        popular_categories = (
            Category.objects.annotate(
                listing_count=Count(
                    "listings", filter=Q(listings__status=Listing.Status.PUBLISHED)
                )
            )
            .order_by("-listing_count")[:10]
        )

        listing_trends = (
            Listing.objects.annotate(
                month=dj_models.functions.TruncMonth("created_at"))
            .values("listing_type", "month")
            .annotate(count=Count("id"))
            .order_by("month", "listing_type")
        )

        geographic_distribution = (
            Listing.objects.values("country")
            .annotate(count=Count("id"))
            .order_by("-count")[:20]
        )

        serializer = ListingAnalyticsSerializer(
            {
                "performance_metrics": listing_performance,
                "popular_categories": CategorySummarySerializer(
                    popular_categories, many=True, context={"request": request}
                ).data,
                "listing_trends": list(listing_trends),
                "geographic_distribution": list(geographic_distribution),
            }
        )
        return Response(serializer.data)

    # ───────────────────────────────
    # CONVERSION ANALYTICS
    # ───────────────────────────────
    @extend_schema(
        summary="Get conversion analytics",
        description="Computes conversion and inquiry response metrics.",
        responses=ConversionAnalyticsSerializer,
    )
    @action(detail=False, methods=["get"])
    def conversion_analytics(self, request):
        """Conversion and response rate metrics."""
        if getattr(self, "swagger_fake_view", False):
            return Response({})

        listings_with_stats = (
            Listing.objects.exclude(views_count=0)
            .annotate(conversion_rate=F("inquiries_count") * 100.0 / F("views_count"))
            .aggregate(
                avg_conversion_rate=Avg("conversion_rate"),
                total_conversions=Sum("inquiries_count"),
                total_views=Sum("views_count"),
            )
        )

        response_stats = Inquiry.objects.aggregate(
            total_inquiries=Count("id"),
            read_inquiries=Count(
                "id",
                filter=Q(
                    status__in=[Inquiry.Status.READ, Inquiry.Status.REPLIED]
                ),
            ),
            replied_inquiries=Count("id", filter=Q(
                status=Inquiry.Status.REPLIED)),
        )

        total_inquiries = response_stats.get("total_inquiries") or 0
        if total_inquiries > 0:
            response_stats["read_rate"] = (
                response_stats["read_inquiries"] / total_inquiries
            ) * 100
            response_stats["reply_rate"] = (
                response_stats["replied_inquiries"] / total_inquiries
            ) * 100
        else:
            response_stats["read_rate"] = 0
            response_stats["reply_rate"] = 0

        serializer = ConversionAnalyticsSerializer(
            {
                "conversion_metrics": listings_with_stats,
                "response_metrics": response_stats,
            },
            context={"request": request},
        )

        return Response(serializer.data)

    # ───────────────────────────────
    # INTERNAL HELPERS
    # ───────────────────────────────
    def _get_user_statistics(self, last_30_days, last_7_days):
        return {
            "total_users": User.objects.count(),
            "active_users_30d": User.objects.filter(
                last_login__gte=last_30_days
            ).count(),
            "new_users_30d": User.objects.filter(
                date_joined__gte=last_30_days
            ).count(),
            "new_users_7d": User.objects.filter(date_joined__gte=last_7_days).count(),
            "verified_users": User.objects.filter(is_verified=True).count(),
            "users_by_role": dict(User.objects.values_list("role").annotate(Count("role"))),
            "inactive_users": User.objects.filter(is_active=False).count(),
        }

    def _get_listing_statistics(self, last_30_days, last_7_days):
        return {
            "total_listings": Listing.objects.count(),
            "published_listings": Listing.objects.filter(
                status=Listing.Status.PUBLISHED
            ).count(),
            "new_listings_30d": Listing.objects.filter(
                created_at__gte=last_30_days
            ).count(),
            "new_listings_7d": Listing.objects.filter(
                created_at__gte=last_7_days
            ).count(),
            "featured_listings": Listing.objects.filter(featured=True).count(),
            "listings_by_type": dict(
                Listing.objects.values_list("listing_type").annotate(
                    Count("listing_type")
                )
            ),
            "listings_by_status": dict(
                Listing.objects.values_list("status").annotate(Count("status"))
            ),
            "avg_views_per_listing": Listing.objects.aggregate(
                Avg("views_count")
            )["views_count__avg"]
            or 0,
            "total_views": Listing.objects.aggregate(Sum("views_count"))[
                "views_count__sum"
            ]
            or 0,
        }

    def _get_inquiry_statistics(self, last_30_days, last_7_days):
        return {
            "total_inquiries": Inquiry.objects.count(),
            "new_inquiries_30d": Inquiry.objects.filter(
                created_at__gte=last_30_days
            ).count(),
            "new_inquiries_7d": Inquiry.objects.filter(
                created_at__gte=last_7_days
            ).count(),
            "inquiries_by_status": dict(
                Inquiry.objects.values_list("status").annotate(Count("status"))
            ),
            "urgent_inquiries": Inquiry.objects.filter(is_urgent=True).count(),
            "spam_inquiries": Inquiry.objects.filter(
                status=Inquiry.Status.SPAM
            ).count(),
            "avg_response_time_hours": self._calculate_avg_response_time(),
        }

    def _get_category_statistics(self):
        return {
            "total_categories": Category.objects.count(),
            "active_categories": Category.objects.filter(is_active=True).count(),
            "categories_with_listings": Category.objects.filter(
                listings__isnull=False
            )
            .distinct()
            .count(),
            "top_categories": list(
                Category.objects.annotate(
                    listing_count=Count(
                        "listings",
                        filter=Q(listings__status=Listing.Status.PUBLISHED),
                    )
                )
                .order_by("-listing_count")[:5]
                .values("name", "listing_count")
            ),
        }

    def _get_business_statistics(self, last_30_days):
        return {
            "active_transactions_30d": Inquiry.objects.filter(
                created_at__gte=last_30_days,
                status__in=[Inquiry.Status.REPLIED, Inquiry.Status.CLOSED],
            ).count(),
            "marketplace_activity_score": self._calculate_activity_score(),
            "user_engagement_rate": self._calculate_engagement_rate(last_30_days),
        }

    def _calculate_avg_response_time(self) -> float:
        responded_inquiries = Inquiry.objects.filter(replied_at__isnull=False).annotate(
            response_time=dj_models.F("replied_at") - dj_models.F("created_at")
        )
        if responded_inquiries.exists():
            avg_seconds = responded_inquiries.aggregate(avg_time=Avg("response_time"))[
                "avg_time"
            ].total_seconds()
            return avg_seconds / 3600
        return 0.0

    def _calculate_activity_score(self) -> float:
        now = timezone.now()
        last_week = now - timedelta(days=7)
        new_listings = Listing.objects.filter(
            created_at__gte=last_week).count()
        new_inquiries = Inquiry.objects.filter(
            created_at__gte=last_week).count()
        active_users = User.objects.filter(last_login__gte=last_week).count()
        score = min(100, (new_listings * 2) +
                    (new_inquiries * 1.5) + (active_users * 0.5))
        return round(score, 2)

    def _calculate_engagement_rate(self, since_date) -> float:
        total_users = User.objects.filter(date_joined__lt=since_date).count()
        if total_users == 0:
            return 0.0
        active_users = User.objects.filter(
            date_joined__lt=since_date, last_login__gte=since_date
        ).count()
        return round((active_users / total_users) * 100, 2)
