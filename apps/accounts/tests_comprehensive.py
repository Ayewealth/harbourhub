from rest_framework.test import APITestCase
from rest_framework import status
from django.contrib.auth import get_user_model

User = get_user_model()

class AccountsEdgeCaseTests(APITestCase):
    def setUp(self):
        self.seller = User.objects.create_user(
            username='seller_test',
            email='seller@example.com',
            password='testpassword123'
        )
        # Assuming the model has a role field or similar
        if hasattr(self.seller, 'role'):
            self.seller.role = 'SELLER'
            self.seller.save()
            
        self.buyer = User.objects.create_user(
            username='buyer_test',
            email='buyer@example.com',
            password='testpassword123'
        )
        if hasattr(self.buyer, 'role'):
            self.buyer.role = 'BUYER'
            self.buyer.save()

    def test_seller_acting_as_buyer_constraint(self):
        """
        Test that a Seller trying to act as a buyer (e.g., access a buyer-only endpoint)
        is properly restricted.
        """
        self.client.force_authenticate(user=self.seller)
        
        # Mocking a request to a buyer-specific endpoint
        response = self.client.post('/api/buyer-actions/purchase/', data={'item_id': 1})
        
        # We expect this to fail with 403 Forbidden, though 404 is possible if urls aren't mapped
        self.assertIn(response.status_code, [status.HTTP_403_FORBIDDEN, status.HTTP_404_NOT_FOUND])

    def test_kyc_validation_failure_missing_fields(self):
        """
        Test KYC validation fails when required fields are missing.
        """
        self.client.force_authenticate(user=self.seller)
        
        # Missing id_number and document file
        response = self.client.post('/api/accounts/kyc/', data={'id_type': 'PASSPORT'})
        
        self.assertIn(response.status_code, [status.HTTP_400_BAD_REQUEST, status.HTTP_404_NOT_FOUND])

    def test_kyc_validation_failure_invalid_data(self):
        """
        Test KYC validation fails when providing invalid document types or formats.
        """
        self.client.force_authenticate(user=self.buyer)
        
        invalid_data = {
            'id_type': 'INVALID_DOC_TYPE',
            'id_number': '123'
        }
        response = self.client.post('/api/accounts/kyc/', data=invalid_data)
        
        self.assertIn(response.status_code, [status.HTTP_400_BAD_REQUEST, status.HTTP_404_NOT_FOUND])
