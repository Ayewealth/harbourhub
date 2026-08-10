from rest_framework.test import APITestCase
from rest_framework import status
from django.urls import reverse
from django.contrib.auth import get_user_model
from django.db.utils import IntegrityError
from apps.listings.models import Listing
from apps.categories.models import Category
from apps.store.models import Store
from apps.reviews.models import ListingReview, StoreReview

User = get_user_model()

class ReviewEdgeCaseTests(APITestCase):
    def setUp(self):
        self.seller = User.objects.create_user(
            email="seller@reviews.com", username="seller_rev", password="testpassword123", role=User.Role.SELLER
        )
        self.buyer = User.objects.create_user(
            email="buyer@reviews.com", username="buyer_rev", password="testpassword123", role=User.Role.BUYER
        )
        self.category = Category.objects.create(name="Tools", slug="tools")
        self.store = Store.objects.create(user=self.seller, slug="review-store", name="Review Store")
        
        self.listing = Listing.objects.create(
            user=self.seller,
            title="Review Listing",
            description="Test review description",
            category=self.category,
            listing_type=Listing.Type.SELL,
            status=Listing.Status.PUBLISHED,
            price='100.00'
        )
        self.client.force_authenticate(user=self.buyer)

    def test_listing_review_rating_bounds(self):
        """Test that ratings must be between 1 and 5."""
        url = reverse('review-listing-list-create')
        data_over = {'listing': self.listing.id, 'rating': 6, 'comment': 'Too good'}
        data_under = {'listing': self.listing.id, 'rating': 0, 'comment': 'Too bad'}
        
        response_over = self.client.post(url, data_over, format='json')
        response_under = self.client.post(url, data_under, format='json')
        
        self.assertEqual(response_over.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response_under.status_code, status.HTTP_400_BAD_REQUEST)

    def test_listing_review_unique_constraint(self):
        """Test that a user cannot review the same listing twice."""
        ListingReview.objects.create(
            listing=self.listing, reviewer=self.buyer, rating=4, comment="Good"
        )
        
        url = reverse('review-listing-list-create')
        data = {'listing': self.listing.id, 'rating': 5, 'comment': 'Wait, it is better'}
        response = self.client.post(url, data, format='json')
        
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
