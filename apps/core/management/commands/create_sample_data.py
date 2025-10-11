from django.core.management.base import BaseCommand
from django.contrib.auth import get_user_model
from django.db import transaction
from apps.categories.models import Category
from apps.listings.models import Listing
from apps.inquiries.models import Inquiry
from decimal import Decimal
import random
from faker import Faker

fake = Faker()
User = get_user_model()


class Command(BaseCommand):
    help = "Generate sample data for development (users, categories, listings, inquiries)"

    def add_arguments(self, parser):
        parser.add_argument("--users", type=int, default=20,
                            help="Number of users")
        parser.add_argument("--listings", type=int,
                            default=50, help="Number of listings")
        parser.add_argument("--inquiries", type=int,
                            default=100, help="Number of inquiries")

    @transaction.atomic
    def handle(self, *args, **options):
        self.stdout.write(self.style.NOTICE("Creating sample data..."))

        self.create_categories()
        users = self.create_users(options["users"])
        listings = self.create_listings(options["listings"], users)
        self.create_inquiries(options["inquiries"], users, listings)

        self.stdout.write(self.style.SUCCESS(
            "✅ Successfully created sample data!"))

    # --------------------------------------------------------------------
    def create_categories(self):
        """Create sample categories"""
        categories_structure = {
            "Drilling Equipment": ["Drill Bits", "Drill Pipes", "Mud Pumps"],
            "Marine Vessels": ["Tugboats", "Barges", "Supply Vessels"],
            "Production Equipment": ["Pumps", "Separators", "Compressors"],
            "Safety Equipment": ["Fire Safety", "Gas Detection", "PPE"],
            "Services": ["Maintenance", "Transportation", "Inspection"],
        }

        for parent_name, children in categories_structure.items():
            parent, _ = Category.objects.get_or_create(
                name=parent_name, defaults={
                    "description": fake.sentence(), "is_active": True}
            )
            for child_name in children:
                Category.objects.get_or_create(
                    name=child_name,
                    parent=parent,
                    defaults={"description": fake.sentence(),
                              "is_active": True},
                )

        self.stdout.write(self.style.SUCCESS("✅ Categories created"))

    # --------------------------------------------------------------------
    def create_users(self, count):
        """Create test users"""
        roles = [User.Role.BUYER, User.Role.SELLER, User.Role.SERVICE_PROVIDER]
        users = []

        # Admin
        if not User.objects.filter(email="harbourhub2025@gmail.com").exists():
            admin = User.objects.create_superuser(
                email="harbourhub2025@gmail.com",
                password="admin123",
                username="admin",
                first_name="Super",
                last_name="Admin",
                role=User.Role.SUPER_ADMIN,
                is_verified=True,
            )
            users.append(admin)
            self.stdout.write(
                "Admin user created: harbourhub2025@gmail.com / admin123")

        for i in range(count):
            role = random.choice(roles)
            email = f"user{i+1}@mailinator.com"
            if not User.objects.filter(email=email).exists():
                user = User.objects.create_user(
                    email=email,
                    password="password123",
                    username=f"user{i+1}",
                    first_name=fake.first_name(),
                    last_name=fake.last_name(),
                    role=role,
                    company=fake.company() if role != User.Role.BUYER else "",
                    location=fake.city(),
                    phone=fake.phone_number(),
                    is_verified=random.choice([True, False]),
                )
                users.append(user)

        self.stdout.write(self.style.SUCCESS(f"✅ {len(users)} users created"))
        return users

    # --------------------------------------------------------------------
    def create_listings(self, count, users):
        """Create sample listings"""
        listings = []
        categories = list(Category.objects.filter(
            is_active=True, children__isnull=True))

        if not categories:
            self.stdout.write(self.style.WARNING(
                "⚠️ No leaf categories found, skipping listings"))
            return []

        listing_types = [Listing.Type.SELL,
                         Listing.Type.RENT, Listing.Type.SERVICE]
        conditions = ["new", "excellent", "good", "fair"]
        manufacturers = ["Caterpillar", "NOV", "Halliburton", "Schlumberger"]

        sellers = [u for u in users if u.can_create_listings]

        for i in range(count):
            seller = random.choice(sellers)
            category = random.choice(categories)
            l_type = random.choice(listing_types)

            if seller.role == User.Role.SERVICE_PROVIDER:
                l_type = Listing.Type.SERVICE

            listing = Listing.objects.create(
                user=seller,
                title=f"{random.choice(manufacturers)} {category.name} {i+1}",
                description=fake.paragraph(nb_sentences=3),
                category=category,
                listing_type=l_type,
                price=Decimal(random.randint(1000, 100000)
                              ) if l_type != Listing.Type.SERVICE else None,
                currency="USD",
                price_unit="per day" if l_type == Listing.Type.RENT else "total",
                negotiable=random.choice([True, False]),
                location=fake.city(),
                country=fake.country(),
                state_province=fake.state(),
                city=fake.city(),
                contact_name=f"{seller.first_name} {seller.last_name}",
                contact_email=seller.email,
                contact_phone=seller.phone or fake.phone_number(),
                manufacturer=random.choice(
                    manufacturers) if l_type != Listing.Type.SERVICE else "",
                model=f"Model-{i+1}" if l_type != Listing.Type.SERVICE else "",
                year=random.randint(
                    2010, 2024) if l_type != Listing.Type.SERVICE else None,
                condition=random.choice(
                    conditions) if l_type != Listing.Type.SERVICE else "",
                service_area="Global" if l_type == Listing.Type.SERVICE else "",
                status=Listing.Status.PUBLISHED,
                featured=random.choice([True, False, False]),
            )
            listings.append(listing)

        self.stdout.write(self.style.SUCCESS(
            f"✅ {len(listings)} listings created"))
        return listings

    # --------------------------------------------------------------------
    def create_inquiries(self, count, users, listings):
        """Create random inquiries from buyers to sellers"""
        buyers = [u for u in users if u.role == User.Role.BUYER]
        published_listings = [
            l for l in listings if l.status == Listing.Status.PUBLISHED]

        if not buyers or not published_listings:
            self.stdout.write(self.style.WARNING(
                "⚠️ Skipping inquiries (no buyers or listings)"))
            return

        for i in range(count):
            buyer = random.choice(buyers)
            listing = random.choice(published_listings)

            if buyer == listing.user:
                continue

            Inquiry.objects.create(
                listing=listing,
                from_user=buyer,
                to_user=listing.user,
                subject=f"Inquiry about {listing.title}",
                message=f"Hello, I’m interested in {listing.title}. Please provide details.",
                contact_name=f"{buyer.first_name} {buyer.last_name}",
                contact_email=buyer.email,
                contact_phone=buyer.phone or fake.phone_number(),
                contact_company=buyer.company or fake.company(),
                status=random.choice(list(Inquiry.Status.values)),
                is_urgent=random.choice([True, False, False]),
            )

        self.stdout.write(self.style.SUCCESS(f"✅ {count} inquiries created"))
