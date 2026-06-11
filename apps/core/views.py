# apps/core/views.py
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status, permissions, serializers
from django.db.models import Q
from drf_spectacular.utils import extend_schema, OpenApiParameter

from apps.listings.models import Listing
from apps.categories.models import Category
from django.contrib.auth import get_user_model

from apps.listings.serializers import ListingListSerializer
from apps.categories.serializers import CategorySerializer

User = get_user_model()


class GlobalSearchUserSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    username = serializers.CharField()
    email = serializers.EmailField()
    company = serializers.CharField()
    role = serializers.CharField()


class GlobalSearchResponseSerializer(serializers.Serializer):
    listings = ListingListSerializer(many=True)
    categories = CategorySerializer(many=True)
    users = GlobalSearchUserSerializer(many=True)


class GlobalSearchView(APIView):
    """
    🔍 Global search across listings, categories, and users.
    Example: /api/search/?q=excavator
    """
    permission_classes = [permissions.AllowAny]

    @extend_schema(
        parameters=[
            OpenApiParameter(name="q", type=str, location=OpenApiParameter.QUERY,
                             description="Search query (min 2 characters)", required=True),
        ],
        responses={200: GlobalSearchResponseSerializer},
    )
    def get(self, request, *args, **kwargs):
        query = request.GET.get("q", "").strip()

        if not query or len(query) < 2:
            return Response(
                {"error": "Search query must be at least 2 characters."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Save search for authenticated users
        if request.user.is_authenticated:
            try:
                from apps.core.models import UserSearch
                UserSearch.objects.create(user=request.user, query=query)
            except Exception:
                pass  # don't break search if save fails

        listings_qs = Listing.objects.filter(
            Q(title__icontains=query) | Q(description__icontains=query)
            | Q(manufacturer__icontains=query) | Q(model__icontains=query)
            | Q(location__icontains=query)
        ).filter(
            status=Listing.Status.PUBLISHED,
            store__is_published=True,
            store__is_active=True,
        ).select_related('category', 'user', 'store').prefetch_related('images')[:10]

        categories_qs = Category.objects.filter(
            Q(name__icontains=query) | Q(description__icontains=query)
        )[:10]

        users_qs = User.objects.filter(
            Q(username__icontains=query) | Q(company__icontains=query)
        ).filter(
            is_active=True,
            role__in=[User.Role.SELLER,
                      User.Role.SERVICE_PROVIDER]  # vendors only
        )[:10]

        return Response({
            "listings": ListingListSerializer(listings_qs, many=True, context={"request": request}).data,
            "categories": CategorySerializer(categories_qs, many=True, context={"request": request}).data,
            "users": [
                {"id": u.id, "username": u.username, "company": getattr(
                    u, "company", ""), "role": u.role}
                for u in users_qs
            ],
        }, status=status.HTTP_200_OK)


class UserSearchHistoryView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        """Get current user's search history"""
        from apps.core.models import UserSearch
        searches = UserSearch.objects.filter(
            user=request.user
        ).values('id', 'query', 'created_at')[:20]
        return Response(list(searches))

    def delete(self, request):
        """Clear current user's search history"""
        from apps.core.models import UserSearch
        UserSearch.objects.filter(user=request.user).delete()
        return Response({'message': 'Search history cleared'})


from rest_framework.throttling import SimpleRateThrottle
from apps.core.models import Feedback

class FeedbackThrottle(SimpleRateThrottle):
    scope = 'feedback'
    rate = '10/min'

    def get_cache_key(self, request, view):
        return self.cache_format % {
            'scope': self.scope,
            'ident': self.get_ident(request)
        }


class FeedbackView(APIView):
    """
    POST /api/feedback/
    Submit page feedback (Helpful / Not Helpful) from static pages.
    """
    permission_classes = [permissions.AllowAny]
    throttle_classes = [FeedbackThrottle]

    def post(self, request):
        topic = request.data.get("topic")
        feedback_val = request.data.get("feedback")

        if not topic:
            return Response(
                {"error": "topic field is required."},
                status=status.HTTP_400_BAD_REQUEST
            )

        if not feedback_val:
            return Response(
                {"error": "feedback field is required."},
                status=status.HTTP_400_BAD_REQUEST
            )

        # Normalize feedback
        feedback_val = str(feedback_val).strip().lower()
        if feedback_val not in ["helpful", "not_helpful"]:
            return Response(
                {"error": "Invalid feedback value. Must be 'helpful' or 'not_helpful'."},
                status=status.HTTP_400_BAD_REQUEST
            )

        # Get IP Address
        x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
        if x_forwarded_for:
            ip = x_forwarded_for.split(',')[0].strip()
        else:
            ip = request.META.get('REMOTE_ADDR')

        user = request.user if request.user.is_authenticated else None

        Feedback.objects.create(
            topic=topic,
            feedback=feedback_val,
            user=user,
            ip_address=ip
        )

        return Response({"status": "received"}, status=status.HTTP_201_CREATED)
