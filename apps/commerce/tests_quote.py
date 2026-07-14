from decimal import Decimal
from django.contrib.auth import get_user_model
from django.urls import reverse
from rest_framework.test import APITestCase
from rest_framework import status
from unittest.mock import patch

from apps.accounts.models import DeliveryDetail
from apps.categories.models import Category
from apps.commerce.models import QuoteRequest, Cart, CartItem
from apps.listings.models import Listing
from apps.store.models import Store

User = get_user_model()

class QuoteAndCartTests(APITestCase):
    def setUp(self):
        self.buyer = User.objects.create_user(
            email="buyer2@harbourhubglobal.com",
            username="buyer2",
            password="testpassword123",
            role=User.Role.BUYER
        )
        self.seller = User.objects.create_user(
            email="seller2@harbourhubglobal.com",
            username="seller2",
            password="testpassword123",
            role=User.Role.SELLER
        )
        
        self.delivery_detail = DeliveryDetail.objects.create(
            user=self.buyer,
            contact_person="John Buyer",
            phone="+2348012345678",
            address="123 Test St",
            city="Lagos",
            state="Lagos",
            country="Nigeria"
        )
        
        self.category = Category.objects.create(name="Test Category", slug="test-category")
        self.store = Store.objects.create(user=self.seller, name="Seller Store", slug="seller-store")
        
        self.listing = Listing.objects.create(
            user=self.seller,
            title="Test Listing",
            description="A test listing",
            category=self.category,
            listing_type=Listing.Type.SELL,
            price=Decimal("100.00"),
            currency="USD",
            location="Lagos, Nigeria",
            contact_name="Seller",
            contact_email="seller2@harbourhubglobal.com",
            status=Listing.Status.PUBLISHED,
            store=self.store
        )
        
        self.quote_url = reverse("quote-list-create")

    def test_create_quote_saves_delivery_detail(self):
        """Test that creating a quote successfully saves the delivery detail."""
        self.client.force_authenticate(user=self.buyer)
        payload = {
            "listing": self.listing.id,
            "store": self.store.id,
            "purchase_type": "buy",
            "quantity": 2,
            "delivery_detail": self.delivery_detail.id,
            "notes": "Please deliver ASAP"
        }
        
        response = self.client.post(self.quote_url, payload)
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        
        quote = QuoteRequest.objects.last()
        self.assertEqual(quote.delivery_detail.id, self.delivery_detail.id)
        self.assertEqual(quote.standard_price, Decimal("200.00")) # 100 * 2

    @patch("apps.core.currency.get_exchange_rates")
    def test_currency_conversion_on_quote_serializer(self, mock_get_rates):
        """Test that the currency converter correctly pivots off USD = 1.0."""
        # Mock exchange rates
        mock_get_rates.return_value = {
            "USD": 1.0,
            "NGN": 1500.0
        }
        
        # Create a quote first
        quote = QuoteRequest.objects.create(
            listing=self.listing,
            buyer=self.buyer,
            store=self.store,
            purchase_type="buy",
            quantity=1,
            standard_price=Decimal("100.00"),
            status=QuoteRequest.Status.PENDING,
            adjustments=[{"name": "Discount", "amount": "10.00", "type": "subtraction"}]
        )
        # standard_price = 100
        # total_quote_price = 90 (after adjustment)
        
        self.client.force_authenticate(user=self.buyer)
        # Request with NGN currency preference
        response = self.client.get(f"{self.quote_url}{quote.id}/", HTTP_HH_CURRENCY="NGN")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        
        # Since base is USD and rate is 1500:
        # standard_price (100 USD) -> 150,000 NGN
        # total_quote_price (90 USD) -> 135,000 NGN
        self.assertEqual(response.data["currency"], "NGN")
        self.assertEqual(response.data["standard_price"], 150000.0)
        self.assertEqual(response.data["total_quote_price"], 135000.0)

    def test_move_quote_to_cart_without_quoted_price_body(self):
        """Test that move-to-cart endpoint works without requiring a quoted_price body."""
        quote = QuoteRequest.objects.create(
            listing=self.listing,
            buyer=self.buyer,
            store=self.store,
            purchase_type="buy",
            quantity=2,
            standard_price=Decimal("200.00"),
            status=QuoteRequest.Status.RESPONDED, # Must be responded to convert
            adjustments=[{"name": "Shipping", "amount": "50.00", "type": "addition"}]
        )
        # total_quote_price = 250.00
        
        self.client.force_authenticate(user=self.buyer)
        url = reverse("quote-move-to-cart", kwargs={"pk": quote.pk})
        
        # We send an empty body to ensure it does not throw 500
        response = self.client.post(url, {})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        
        # Verify cart item was created
        cart = Cart.objects.get(buyer=self.buyer)
        cart_item = CartItem.objects.get(cart=cart, listing=self.listing)
        
        # Unit price remains original listing price
        self.assertEqual(cart_item.unit_price, Decimal("100.00"))
        # Locked subtotal should be the total_quote_price (250.00)
        self.assertEqual(cart_item.locked_subtotal, Decimal("250.00"))
        
        # Verify quote status changed
        quote.refresh_from_db()
        self.assertEqual(quote.status, QuoteRequest.Status.CONVERTED)
