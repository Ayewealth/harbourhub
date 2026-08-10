import uuid
from decimal import Decimal
from django.contrib.auth import get_user_model
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APITestCase
from rest_framework import status
from unittest.mock import patch

from apps.commerce.models import Cart, CartItem, CheckoutSession, Order, OrderItem, Payment
from apps.listings.models import Listing
from apps.categories.models import Category
from apps.store.models import Store
from apps.accounts.models import DeliveryDetail

User = get_user_model()

class ComprehensiveCommerceTests(APITestCase):
    def setUp(self):
        # 1. Users
        self.buyer = User.objects.create_user(
            email="buyer@test.com", username="buyer", password="testpassword123", role=User.Role.BUYER
        )
        self.seller1 = User.objects.create_user(
            email="seller1@test.com", username="seller1", password="testpassword123", role=User.Role.SELLER
        )
        self.seller2 = User.objects.create_user(
            email="seller2@test.com", username="seller2", password="testpassword123", role=User.Role.SELLER
        )

        # 2. Stores
        self.store1 = Store.objects.create(name="Store One", user=self.seller1, slug="store-one")
        self.store2 = Store.objects.create(name="Store Two", user=self.seller2, slug="store-two")

        # 3. Category & Listings
        self.category = Category.objects.create(name="Equipment", slug="equip")
        self.listing_buy = Listing.objects.create(
            user=self.seller1, store=self.store1, category=self.category,
            title="Buy Item", description="Buy this", listing_type="sell",
            price=Decimal('10000.00'), currency="NGN", status="published"
        )
        self.listing_rent = Listing.objects.create(
            user=self.seller2, store=self.store2, category=self.category,
            title="Rent Item", description="Rent this", listing_type="rent",
            price=Decimal('5000.00'), currency="NGN", status="published"
        )

        # 4. Delivery Detail
        self.delivery = DeliveryDetail.objects.create(
            user=self.buyer, contact_person="John Doe", address="123 Main St",
            city="Lagos", state="LA", phone="08012345678"
        )

    def test_mixed_cart_checkout_split_orders(self):
        """Test that checking out a cart with multiple vendors splits the orders correctly."""
        self.client.force_authenticate(user=self.buyer)
        
        # Build Cart
        cart = Cart.objects.create(buyer=self.buyer)
        CartItem.objects.create(
            cart=cart, listing=self.listing_buy, store=self.store1, purchase_type=CartItem.PurchaseType.BUY,
            quantity=2, unit_price=self.listing_buy.price, delivery_detail=self.delivery
        )
        CartItem.objects.create(
            cart=cart, listing=self.listing_rent, store=self.store2, purchase_type=CartItem.PurchaseType.RENT,
            quantity=1, unit_price=self.listing_rent.price, duration_days=3, delivery_detail=self.delivery
        )

        # Ensure cart logic subtotal is correct
        # Buy: 2 * 10000 = 20000
        # Rent: 1 * 5000 * 3 days = 15000
        # Total cart should evaluate to 35000

        with patch('apps.commerce.views.initialize_transaction') as mock_paystack:
            mock_paystack.return_value = {
                'authorization_url': 'https://checkout.paystack.com/mock',
                'access_code': 'mock_code'
            }
            
            data = {
                'cart_item_ids': [item.id for item in cart.items.all()],
                'terms_accepted': True
            }
            url = reverse('checkout')
            response = self.client.post(url, data, format='json')

            print("MIXED CHECKOUT RESPONSE:", response.data)
            self.assertEqual(response.status_code, status.HTTP_201_CREATED)
            self.assertEqual(len(response.data['orders']), 2)  # Split by vendor!

            # Validate DB
            self.assertEqual(CartItem.objects.count(), 0)  # Cart cleared
            self.assertEqual(CheckoutSession.objects.count(), 1)
            self.assertEqual(Order.objects.count(), 2)
            self.assertEqual(OrderItem.objects.count(), 2)
            self.assertEqual(Payment.objects.count(), 1)

            payment = Payment.objects.first()
            self.assertEqual(payment.authorization_url, 'https://checkout.paystack.com/mock')
            
            # The grand total (35000 + 5% escrow (1750) = 36750.00)
            self.assertEqual(payment.amount, Decimal('36750.00'))

    def test_checkout_paystack_failure_rollback(self):
        """Test that if Paystack fails to initialize, the transaction rolls back."""
        self.client.force_authenticate(user=self.buyer)
        cart = Cart.objects.create(buyer=self.buyer)
        CartItem.objects.create(
            cart=cart, listing=self.listing_buy, store=self.store1, purchase_type=CartItem.PurchaseType.BUY,
            quantity=1, unit_price=self.listing_buy.price, delivery_detail=self.delivery
        )

        with patch('apps.commerce.views.initialize_transaction') as mock_paystack:
            mock_paystack.return_value = None  # SIMULATE FAILURE
            
            data = {
                'cart_item_ids': [item.id for item in cart.items.all()],
                'terms_accepted': True
            }
            url = reverse('checkout')
            response = self.client.post(url, data, format='json')

            self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
            print("ROLLBACK RESPONSE:", response.data)
            self.assertIn("Failed to initialize payment gateway", str(response.data))

            # Ensure nothing was created and cart is NOT deleted!
            self.assertEqual(CartItem.objects.count(), 1)
            self.assertEqual(Order.objects.count(), 0)
            self.assertEqual(Payment.objects.count(), 0)

    def test_retry_payment_success(self):
        """Test retrying a pending payment."""
        self.client.force_authenticate(user=self.buyer)
        
        session = CheckoutSession.objects.create(buyer=self.buyer, total_amount=Decimal('10000.00'), currency='NGN')
        payment = Payment.objects.create(
            checkout_session=session, buyer=self.buyer, amount=Decimal('10000.00'),
            currency='NGN', reference='OLD-REF', status=Payment.Status.PENDING, authorization_url=''
        )

        with patch('apps.commerce.views.initialize_transaction') as mock_paystack:
            mock_paystack.return_value = {
                'authorization_url': 'https://checkout.paystack.com/new',
                'access_code': 'new_code'
            }
            
            url = reverse('retry-payment', kwargs={'session_id': session.id})
            response = self.client.post(url)
            
            self.assertEqual(response.status_code, status.HTTP_200_OK)
            self.assertEqual(response.data['authorization_url'], 'https://checkout.paystack.com/new')
            
            payment.refresh_from_db()
            self.assertEqual(payment.authorization_url, 'https://checkout.paystack.com/new')
            self.assertNotEqual(payment.reference, 'OLD-REF')

    def test_retry_payment_already_paid(self):
        """Test retrying a payment that is already successful fails."""
        self.client.force_authenticate(user=self.buyer)
        
        session = CheckoutSession.objects.create(buyer=self.buyer, total_amount=Decimal('10000.00'), currency='NGN')
        Payment.objects.create(
            checkout_session=session, buyer=self.buyer, amount=Decimal('10000.00'),
            currency='NGN', reference='PAID-REF', status=Payment.Status.SUCCESS
        )

        url = reverse('retry-payment', kwargs={'session_id': session.id})
        response = self.client.post(url)
        
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("already successful", response.data['message'])

    def test_payment_verify_webhook_updates_order(self):
        """Test that successfully verifying a payment sets orders to PAID."""
        self.client.force_authenticate(user=self.buyer)
        
        session = CheckoutSession.objects.create(buyer=self.buyer, total_amount=Decimal('10000.00'), currency='NGN')
        payment = Payment.objects.create(
            checkout_session=session, buyer=self.buyer, amount=Decimal('10000.00'),
            currency='NGN', reference='REF-VERIFY', status=Payment.Status.PENDING
        )
        order = Order.objects.create(
            order_number="ORD-TEST", buyer=self.buyer, seller=self.seller1,
            checkout_session=session, currency="NGN", status=Order.Status.PENDING_PAYMENT,
            total_amount=Decimal('10000.00')
        )

        with patch('apps.commerce.views.verify_transaction') as mock_verify:
            mock_verify.return_value = {'status': 'success'}
            
            url = reverse('payment-verify', kwargs={'reference': 'REF-VERIFY'})
            response = self.client.get(url)
            
            self.assertEqual(response.status_code, status.HTTP_200_OK)
            
            payment.refresh_from_db()
            order.refresh_from_db()
            
            self.assertEqual(payment.status, Payment.Status.SUCCESS)
            self.assertEqual(order.status, Order.Status.PAID)
