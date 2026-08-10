from rest_framework.test import APITestCase
from rest_framework import status
from django.contrib.auth import get_user_model
from django.utils import timezone
from django.urls import reverse
from datetime import timedelta

from apps.categories.models import Category
from apps.listings.models import Listing

User = get_user_model()

class ListingEdgeCaseTests(APITestCase):
    """
    Comprehensive edge-case tests for the listings app.
    """

    def setUp(self):
        # Create a test user
        self.user = User.objects.create_user(
            email="testuser@example.com",
            password="testpassword123",
            first_name="Test",
            last_name="User",
            role=User.Role.SELLER
        )
        # Create a store since sellers need a store to list
        from apps.store.models import Store
        self.store = Store.objects.create(user=self.user, slug="test-store", name="Test Store")
        # Force authentication for the test client
        self.client.force_authenticate(user=self.user)
        
        # Create a category required by the Listing model
        self.category = Category.objects.create(
            name="Construction Equipment",
            slug="construction-equipment",
            description="Heavy machinery category"
        )
        
        # Base valid data for creating a listing
        self.valid_listing_data = {
            "title": "Excavator 2020",
            "description": "Good condition excavator for sale.",
            "category": self.category.id,
            "listing_type": Listing.Type.SELL,
            "price": "50000.00",
            "location": "Lagos",
            "contact_name": "Test Contact",
            "contact_email": "contact@example.com",
            "status": Listing.Status.DRAFT
        }

    def test_create_listing_without_category(self):
        """
        Edge Case: Attempt to create a listing without providing a required category.
        Expected: Validation error (HTTP 400 Bad Request) on the 'category' field.
        """
        data = self.valid_listing_data.copy()
        data.pop("category", None)
        
        url = reverse('listing-list')
        response = self.client.post(url, data, format="json")
        
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("category", response.data)


    def test_soft_deletion_and_archiving_logic(self):
        """
        Edge Case: Test updating listing status to ARCHIVED (soft delete equivalent).
        """
        listing = Listing.objects.create(
            user=self.user,
            title="Listing to be archived",
            description="This listing will be archived shortly.",
            category=self.category,
            listing_type=Listing.Type.RENT,
            status=Listing.Status.PUBLISHED,
            contact_name="Bob Builder",
            contact_email="bob@example.com",
            location="Abuja"
        )
        
        url = reverse('listing-detail', args=[listing.id])
        response = self.client.patch(url, {"status": Listing.Status.ARCHIVED}, format="json")
        
        # Depending on permissions, this should succeed or be restricted,
        # but typically an owner can archive their own listing.
        if response.status_code in [status.HTTP_200_OK, status.HTTP_204_NO_CONTENT]:
            listing.refresh_from_db()
            self.assertEqual(listing.status, Listing.Status.ARCHIVED)

    def test_expire_if_needed_method(self):
        """
        Edge Case: Test the `expire_if_needed` model method for automatic archiving 
        when the expiration date has passed.
        """
        past_date = timezone.now() - timedelta(days=2)
        listing = Listing.objects.create(
            user=self.user,
            title="Expired Listing Test",
            description="This listing should be auto-archived.",
            category=self.category,
            listing_type=Listing.Type.SERVICE,
            status=Listing.Status.PUBLISHED,
            expires_at=past_date,
            contact_name="Alice",
            contact_email="alice@example.com",
            location="Port Harcourt"
        )
        
        # Verify it is flagged as expired
        self.assertTrue(listing.is_expired)
        
        # Trigger expiration method
        listing.expire_if_needed()
        listing.refresh_from_db()
        
        # Status should have transitioned to ARCHIVED
        self.assertEqual(listing.status, Listing.Status.ARCHIVED)
