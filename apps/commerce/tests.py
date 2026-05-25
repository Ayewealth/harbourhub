from django.contrib.auth import get_user_model
from django.urls import reverse
from rest_framework.test import APITestCase
from rest_framework import status
from apps.commerce.models import Order

User = get_user_model()

class OrderInvoicePDFTests(APITestCase):
    def setUp(self):
        # Create users with correct roles and emails
        self.buyer = User.objects.create_user(
            email="buyer@harbourhubglobal.com",
            username="buyer",
            password="testpassword123",
            role=User.Role.BUYER
        )
        self.seller = User.objects.create_user(
            email="seller@harbourhubglobal.com",
            username="seller",
            password="testpassword123",
            role=User.Role.SELLER
        )
        self.other_user = User.objects.create_user(
            email="other@harbourhubglobal.com",
            username="other",
            password="testpassword123",
            role=User.Role.BUYER
        )
        self.admin_user = User.objects.create_superuser(
            email="admin@harbourhubglobal.com",
            username="admin",
            password="testpassword123"
        )

        # Create a dummy order
        self.order = Order.objects.create(
            order_number="HH-2026-987654",
            order_type=Order.OrderType.BUY,
            buyer=self.buyer,
            seller=self.seller,
            currency="NGN",
            total_amount=150000.00,
            subtotal=140000.00,
            delivery_fee=8000.00,
            escrow_fee=2000.00,
            status=Order.Status.PAID,
            delivery_address="12 Shoreline Drive, Lagos, Nigeria",
            delivery_contact_name="John Doe",
            delivery_contact_phone="+2348012345678"
        )

        # URL for download
        self.url = reverse("order-invoice-pdf", kwargs={"pk": self.order.pk})

    def test_anonymous_user_cannot_download_invoice(self):
        """Anonymous users must receive 401 Unauthorized."""
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_non_participating_user_cannot_download_invoice(self):
        """Users who are not the buyer, seller, or staff must receive 403 Forbidden."""
        self.client.force_authenticate(user=self.other_user)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_buyer_can_download_invoice(self):
        """The buyer must be allowed to download the PDF invoice."""
        self.client.force_authenticate(user=self.buyer)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response["content-type"], "application/pdf")
        self.assertTrue(response["Content-Disposition"].startswith("attachment; filename="))
        self.assertIn("invoice_", response["Content-Disposition"])
        self.assertTrue(len(response.content) > 0)

    def test_seller_can_download_invoice(self):
        """The seller must be allowed to download the PDF invoice."""
        self.client.force_authenticate(user=self.seller)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response["content-type"], "application/pdf")
        self.assertTrue(response["Content-Disposition"].startswith("attachment; filename="))
        self.assertTrue(len(response.content) > 0)

    def test_admin_can_download_invoice(self):
        """Staff/Superusers must be allowed to download the PDF invoice."""
        self.client.force_authenticate(user=self.admin_user)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response["content-type"], "application/pdf")
        self.assertTrue(response["Content-Disposition"].startswith("attachment; filename="))
        self.assertTrue(len(response.content) > 0)

    def test_not_found_order(self):
        """Downloading an invoice for a non-existent order must return 404."""
        self.client.force_authenticate(user=self.buyer)
        url = reverse("order-invoice-pdf", kwargs={"pk": 999999})
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
