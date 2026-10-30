from rest_framework.test import APITestCase
from rest_framework import status
from django.urls import reverse
from django.contrib.auth import get_user_model
from apps.categories.models import Category

User = get_user_model()

class CategoryEdgeCaseTests(APITestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser(
            email="admin@cats.com", username="admin_cats", password="testpassword123"
        )
        self.buyer = User.objects.create_user(
            email="buyer@cats.com", username="buyer_cats", password="testpassword123", role=User.Role.BUYER
        )

    def test_category_unique_slug_generation(self):
        """Test that categories with the same name generate unique slugs."""
        cat1 = Category.objects.create(name="Test Cat")
        cat2 = Category.objects.create(name="Test-Cat")
        
        self.assertEqual(cat1.slug, "test-cat")
        self.assertEqual(cat2.slug, "test-cat-1")

    def test_category_admin_only_creation(self):
        """Test that regular users cannot create categories."""
        self.client.force_authenticate(user=self.buyer)
        url = reverse('category-admin-list')
        data = {'name': 'Machinery'}
        response = self.client.post(url, data, format='json')
        
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        
        # Verify admin can create
        self.client.force_authenticate(user=self.admin)
        response = self.client.post(url, data, format='json')
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
