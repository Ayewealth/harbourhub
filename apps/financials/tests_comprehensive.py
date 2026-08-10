from decimal import Decimal
from rest_framework.test import APITestCase
from rest_framework import status
from django.urls import reverse
from unittest.mock import patch
from django.contrib.auth import get_user_model
from apps.financials.models import VendorWallet, Payout, BankAccount
from apps.store.models import Store
from apps.categories.models import Category

User = get_user_model()

class FinancialsEdgeCaseTests(APITestCase):
    def setUp(self):
        self.seller = User.objects.create_user(
            email="seller@test.com", username="seller1", password="testpassword123", role=User.Role.SELLER
        )
        self.category = Category.objects.create(name="Electronics", slug="electronics")
        self.store = Store.objects.create(user=self.seller, slug="my-store", name="My Store")
        self.store.categories.add(self.category)
        
        self.wallet = VendorWallet.objects.get(user=self.seller)
        self.wallet.available_balance = Decimal('100.00')
        self.wallet.save()
        
        self.bank_account = BankAccount.objects.create(
            user=self.seller,
            bank_name="Test Bank",
            account_number="1234567890",
            account_name="Test Account",
            is_verified=True
        )

        self.client.force_authenticate(user=self.seller)
        
    def test_payout_more_than_balance(self):
        """Test that a user cannot request a payout larger than their available balance."""
        url = reverse('payout-list-create')
        data = {'amount': 150.00, 'bank_account': self.bank_account.id}
        response = self.client.post(url, data, format='json')
        
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.wallet.refresh_from_db()
        self.assertEqual(self.wallet.available_balance, Decimal('100.00'))

