# apps/core/views.py
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status, permissions
from django.db.models import Q

from apps.listings.models import Listing
from apps.categories.models import Category
from django.contrib.auth import get_user_model

from apps.listings.serializers import ListingListSerializer
from apps.categories.serializers import CategorySerializer

User = get_user_model()


class GlobalSearchView(APIView):
    """
    🔍 Global search across listings, categories, and users.
    Example: /api/search/?q=excavator
    """
    permission_classes = [permissions.AllowAny]

    def get(self, request, *args, **kwargs):
        query = request.GET.get("q", "").strip()

        if not query:
            return Response(
                {"error": "Please provide a search query (?q=)"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        results = {}

        # --- Search Listings ---
        listings_qs = Listing.objects.filter(
            Q(title__icontains=query)
            | Q(description__icontains=query)
            | Q(manufacturer__icontains=query)
            | Q(model__icontains=query)
            | Q(location__icontains=query)
        ).filter(status=Listing.Status.PUBLISHED)[:10]

        results["listings"] = ListingSerializer(
            listings_qs, many=True, context={"request": request}
        ).data

        # --- Search Categories ---
        categories_qs = Category.objects.filter(
            Q(name__icontains=query) | Q(description__icontains=query)
        )[:10]

        results["categories"] = CategorySerializer(
            categories_qs, many=True, context={"request": request}
        ).data

        # --- Search Users ---
        users_qs = User.objects.filter(
            Q(username__icontains=query)
            | Q(email__icontains=query)
            | Q(company__icontains=query)
        ).filter(is_active=True)[:10]

        results["users"] = [
            {
                "id": u.id,
                "username": u.username,
                "email": u.email,
                "company": getattr(u, "company", ""),
                "role": u.role,
            }
            for u in users_qs
        ]

        return Response(results, status=status.HTTP_200_OK)
