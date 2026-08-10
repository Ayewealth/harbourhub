from django.contrib.auth import get_user_model
from django.db.utils import IntegrityError
from django.test import TestCase

from apps.store.models import Store, ShippingProfile

User = get_user_model()

class ComprehensiveStoreTests(TestCase):
    def setUp(self):
        self.seller = User.objects.create_user(
            email="seller@test.com", username="seller1", password="testpassword123", role=User.Role.SELLER
        )
        self.buyer = User.objects.create_user(
            email="buyer@test.com", username="buyer1", password="testpassword123", role=User.Role.BUYER
        )

    def test_store_creation_success(self):
        """Test a seller can successfully create a store."""
        store = Store.objects.create(
            user=self.seller,
            slug="my-cool-store",
            name="My Cool Store",
            policy="No returns"
        )
        self.assertEqual(store.name, "My Cool Store")
        self.assertEqual(store.is_verified, False)
        self.assertEqual(store.is_published, False)

    def test_one_to_one_constraint_violation(self):
        """Test that a seller cannot create multiple stores."""
        Store.objects.create(
            user=self.seller,
            slug="store-one",
            name="Store One",
            policy="Policy 1"
        )
        with self.assertRaises(IntegrityError):
            Store.objects.create(
                user=self.seller,
                slug="store-two",
                name="Store Two",
                policy="Policy 2"
            )

    def test_shipping_profile_edge_cases(self):
        """Test shipping profile logic such as free shipping thresholds."""
        store = Store.objects.create(
            user=self.seller,
            slug="seller-store",
            name="Seller Store"
        )
        profile = ShippingProfile.objects.create(
            store=store,
            zone_name="Lagos",
            carrier_name="DHL",
            delivery_time_min=1,
            delivery_time_max=3,
            flat_rate_cost=1500.00,
            free_shipping_threshold=50000.00
        )
        self.assertEqual(store.shipping_profiles.count(), 1)
        
        # Deactivate
        profile.is_active = False
        profile.save()
        
        self.assertFalse(store.shipping_profiles.first().is_active)
