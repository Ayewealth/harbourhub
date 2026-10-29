import random
from decimal import Decimal
from datetime import timedelta

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.contrib.auth import get_user_model
from django.db import transaction
from django.utils import timezone
from faker import Faker

from apps.categories.models import Category
from apps.listings.models import Listing, ListingImage, SavedItem
from apps.store.models import Store, StoreActivity
from apps.commerce.models import (
    Cart, CartItem, CheckoutSession, Order, OrderItem, OrderActivity, Payment,
    QuoteRequest, Dispute,
)
from apps.financials.models import (
    VendorWallet, VendorEarning, Payout, BankAccount, WalletTransaction,
)
from apps.financials.services import accrue_earning, money, release_earning
from apps.reviews.models import ListingReview, StoreReview
from apps.accounts.models import VerificationRequest, DeliveryDetail, UserPreference
from apps.inquiries.models import Inquiry

fake = Faker()
User = get_user_model()

# Fixed seed so repeated runs pick the same owners, categories, and statuses.
SAMPLE_SEED = 20261029
ORDER_NUMBER_PREFIX = "ORD-SAMPLE-"


class Command(BaseCommand):
    help = "Generate comprehensive sample data for all apps and link them together."

    def add_arguments(self, parser):
        parser.add_argument("--users", type=int, default=30, help="Number of users")
        parser.add_argument("--listings", type=int, default=100, help="Number of listings")
        parser.add_argument("--orders", type=int, default=20, help="Number of orders")
        parser.add_argument(
            "--clean",
            action="store_true",
            help="Delete all existing data before creating new sample data (requires --force)",
        )
        parser.add_argument(
            "--force",
            action="store_true",
            help="Run even when SEED_SAMPLE_DATA is disabled, and allow --clean",
        )

    @transaction.atomic
    def handle(self, *args, **options):
        force = options["force"]
        if options["clean"] and not force:
            raise CommandError(
                "--clean deletes every seeded business record and requires --force."
            )
        if not (settings.SEED_SAMPLE_DATA or force):
            raise CommandError(
                "Sample data seeding is disabled. Set SEED_SAMPLE_DATA=true or pass --force."
            )

        random.seed(SAMPLE_SEED)
        fake.seed_instance(SAMPLE_SEED)

        self.stdout.write(self.style.NOTICE("Starting sample data generation..."))

        if options["clean"]:
            self.stdout.write(self.style.WARNING("Cleaning up existing data..."))
            self.clean_data()

        # 1. Categories
        self.create_categories()

        # 2. Users (Buyers, Sellers, Providers)
        users = self.create_users(options["users"])
        buyers = [u for u in users if u.role == User.Role.BUYER]
        sellers = [u for u in users if u.role == User.Role.SELLER]
        providers = [u for u in users if u.role == User.Role.SERVICE_PROVIDER]
        admins = [u for u in users if u.is_admin_user]

        # 3. Verification Requests
        self.create_verification_requests(
            sellers + providers, admins[0] if admins else None)

        # 4. Stores. The store is the authoritative vendor in P2, so every
        # seller and service provider needs one before they can list or sell.
        self.create_stores(sellers + providers)

        # 5. Listings
        listings = self.create_listings(
            options["listings"], sellers, providers)

        # 6. Listing Images
        self.create_listing_images(listings)

        # 7. Inquiries
        self.create_inquiries(listings, buyers)

        # 8. Quote Requests
        self.create_quote_requests(listings, buyers)

        # 9. Saved Items
        self.create_saved_items(listings, buyers)

        # 10. Orders & Payments
        orders = self.create_orders(listings, buyers, options["orders"])

        # 11. Financials (Earnings & Wallets)
        self.create_financials(orders)

        # 12. Reviews
        self.create_reviews(orders, buyers)

        # 13. Notifications
        self.create_notifications(users)

        self.stdout.write(self.style.SUCCESS(
            "Sample data generation completed successfully!"))

    def clean_data(self):
        """Wipe core business data."""
        from apps.notifications.models import Notification
        Notification.objects.all().delete()
        from apps.inquiries.models import InquiryReply
        InquiryReply.objects.all().delete()
        StoreReview.objects.all().delete()
        ListingReview.objects.all().delete()
        WalletTransaction.objects.all().delete()
        VendorEarning.objects.all().delete()
        Payout.objects.all().delete()
        VendorWallet.objects.all().delete()
        Payment.objects.all().delete()
        OrderActivity.objects.all().delete()
        Order.objects.all().delete()
        CartItem.objects.all().delete()
        Cart.objects.all().delete()
        QuoteRequest.objects.all().delete()
        Inquiry.objects.all().delete()
        ListingImage.objects.all().delete()
        SavedItem.objects.all().delete()
        Listing.objects.all().delete()
        StoreActivity.objects.all().delete()
        Store.objects.all().delete()
        VerificationRequest.objects.all().delete()
        Category.objects.all().delete()
        # Keep admins, delete other users
        User.objects.exclude(role=User.Role.SUPER_ADMIN).delete()

    def create_categories(self):
        self.stdout.write("Creating categories...")
        categories_structure = {
            "Drilling Equipment": ["Drill Bits", "Drill Pipes", "Mud Pumps"],
            "Marine Vessels": ["Tugboats", "Barges", "Supply Vessels"],
            "Production Equipment": ["Pumps", "Separators", "Compressors"],
            "Safety Equipment": ["Fire Safety", "Gas Detection", "PPE"],
            "Services": ["Maintenance", "Transportation", "Inspection"],
        }
        for parent_name, children in categories_structure.items():
            parent, _ = Category.objects.get_or_create(
                name=parent_name,
                defaults={"description": fake.sentence(), "is_active": True}
            )
            for child_name in children:
                Category.objects.get_or_create(
                    name=child_name, parent=parent,
                    defaults={"description": fake.sentence(), "is_active": True}
                )

    def create_users(self, count):
        self.stdout.write(f"Ensuring {count} sample users...")
        users = []

        # Ensure at least one admin
        admin = User.objects.filter(role=User.Role.SUPER_ADMIN).first()
        if admin is None:
            admin = User.objects.create_superuser(
                email="admin@harbourhub.com",
                password="password123",
                username="admin",
                full_name="System Admin",
                role=User.Role.SUPER_ADMIN,
                is_verified=True
            )
        users.append(admin)

        roles = [User.Role.BUYER] * 15 + \
            [User.Role.SELLER] * 10 + [User.Role.SERVICE_PROVIDER] * 5
        random.shuffle(roles)

        for i in range(count):
            users.append(
                self._sample_user(f"user_{i + 1}", roles[i % len(roles)]))

        # The generators below need at least one vendor of each role.
        if not any(u.role == User.Role.SELLER for u in users):
            users.append(
                self._sample_user("user_sample_seller", User.Role.SELLER))
        if not any(u.role == User.Role.SERVICE_PROVIDER for u in users):
            users.append(
                self._sample_user("user_sample_provider", User.Role.SERVICE_PROVIDER))

        return users

    def _sample_user(self, username, role):
        """Return the user with ``username``, creating it and its profile once."""
        user = User.objects.filter(username=username).first()
        if user is not None:
            return user

        user = User.objects.create_user(
            email=f"{username}@sample.harbourhub.com",
            password="password123",
            username=username,
            full_name=fake.name(),
            role=role,
            company=fake.company() if role != User.Role.BUYER else "",
            location=fake.city(),
            phone=fake.phone_number()[:20],
            is_verified=(role == User.Role.BUYER or random.choice([True, False]))
        )

        # Preferences
        UserPreference.objects.get_or_create(
            user=user,
            defaults={
                "interested_categories": [random.randint(1, 10) for _ in range(3)]
            }
        )

        # Delivery Details
        DeliveryDetail.objects.get_or_create(
            user=user,
            is_default=True,
            defaults={
                "contact_person": user.full_name,
                "country": "Nigeria",
                "state": fake.state(),
                "city": fake.city(),
                "address": fake.address(),
                "phone": user.phone,
            }
        )
        return user

    def create_verification_requests(self, vendors, admin):
        self.stdout.write("Creating verification requests...")
        for vendor in vendors:
            if VerificationRequest.objects.filter(user=vendor).exists():
                continue
            req = VerificationRequest.objects.create(
                user=vendor,
                company_name=vendor.company or fake.company(),
                certifications=fake.text(),
                status=random.choice(
                    [VerificationRequest.Status.APPROVED,
                     VerificationRequest.Status.PENDING])
            )
            if req.status == VerificationRequest.Status.APPROVED and admin:
                req.approve(admin, notes="Looks good.")

    def create_stores(self, vendors):
        self.stdout.write("Creating stores for vendors...")
        stores = []
        categories = list(Category.objects.all())
        for vendor in vendors:
            store, created = Store.objects.get_or_create(
                user=vendor,
                defaults={
                    "name": f"{vendor.company or vendor.full_name} Store",
                    "slug": f"store-{vendor.username}"[:255],
                    "description": fake.paragraph(),
                    "email": vendor.email[:255],
                    "phone": (vendor.phone or fake.phone_number())[:20],
                    "address": fake.address(),
                    "is_verified": vendor.is_verified,
                    "is_active": True,
                    "is_published": True,
                    "policy": fake.text()
                }
            )
            if created and categories:
                store.categories.add(
                    *random.sample(
                        categories, k=min(random.randint(1, 3), len(categories)))
                )
            stores.append(store)
        return stores

    def create_listings(self, count, sellers, providers):
        self.stdout.write(f"Creating {count} listings...")
        listings = []
        leaf_categories = list(Category.objects.filter(children__isnull=True))
        owners = sellers + providers

        if not owners or not leaf_categories:
            self.stdout.write(self.style.WARNING(
                "Skipping listings: no vendors or categories available."))
            return listings

        for i in range(count):
            # Index-based selection keeps the natural key stable even though the
            # random stream differs between a first and a repeated run.
            owner = owners[i % len(owners)]
            category = leaf_categories[i % len(leaf_categories)]

            # Determine listing type
            if owner.role == User.Role.SERVICE_PROVIDER:
                l_type = Listing.Type.SERVICE
            else:
                l_type = random.choice(
                    [Listing.Type.SELL, Listing.Type.RENT, Listing.Type.LEASE])

            # Deterministic title keeps repeated runs idempotent.
            title = f"{category.name} Listing {i + 1}"
            listing = Listing.objects.filter(title=title).first()
            if listing is None:
                listing = Listing.objects.create(
                    user=owner,
                    store=owner.store,
                    title=title,
                    description=fake.text(max_nb_chars=500),
                    category=category,
                    listing_type=l_type,
                    price=Decimal(random.randint(5000, 500000)),
                    currency="NGN",
                    price_unit="per day" if l_type in [
                        Listing.Type.RENT, Listing.Type.LEASE] else "total",
                    location=fake.city(),
                    country="Nigeria",
                    status=Listing.Status.PUBLISHED,
                    manufacturer=fake.company() if l_type != Listing.Type.SERVICE else "",
                    model=f"XP-{random.randint(100, 999)}",
                    condition=random.choice(["new", "excellent", "good"]) if l_type != Listing.Type.SERVICE else ""
                )
            listings.append(listing)
        return listings

    def create_listing_images(self, listings):
        self.stdout.write("Creating listing images (placeholder records)...")
        for listing in listings:
            # We don't have real images to upload, so we just create records
            # In a real scenario, you'd use a default image path
            ListingImage.objects.get_or_create(
                listing=listing,
                sort_order=0,
                defaults={"is_primary": True},
            )

    def create_inquiries(self, listings, buyers):
        self.stdout.write("Creating inquiries for all listings...")
        from apps.inquiries.models import InquiryReply

        if not buyers:
            self.stdout.write(self.style.WARNING(
                "Skipping inquiries: no buyers available."))
            return

        for listing in listings:
            if listing.inquiries.exists():
                continue

            candidates = [b for b in buyers if b != listing.user]
            if not candidates:
                continue

            # Create 1-3 inquiries for EVERY listing
            num_inquiries = random.randint(1, 3)
            for _ in range(num_inquiries):
                buyer = random.choice(candidates)

                inquiry = Inquiry.objects.create(
                    listing=listing,
                    from_user=buyer,
                    to_user=listing.user,
                    subject=random.choice([
                        f"Technical specs for {listing.title}",
                        f"Availability of {listing.title}",
                        f"Pricing inquiry: {listing.title}",
                        f"Shipping to {fake.city()}"
                    ]),
                    message=fake.paragraph(nb_sentences=3),
                    contact_name=buyer.full_name,
                    contact_email=buyer.email,
                    status=random.choice(list(Inquiry.Status.values)),
                    is_urgent=random.choice([True, False, False, False])
                )

                # Create a reply for 50% of inquiries
                if random.choice([True, False]):
                    InquiryReply.objects.create(
                        inquiry=inquiry,
                        user=listing.user,
                        message=f"Hello {buyer.full_name}, thank you for your interest in {listing.title}. " + fake.sentence()
                    )

                    # Occasionally buyer replies back
                    if random.choice([True, False, False]):
                        InquiryReply.objects.create(
                            inquiry=inquiry,
                            user=buyer,
                            message="Thank you for the quick response! " + fake.sentence()
                        )

    def create_quote_requests(self, listings, buyers):
        self.stdout.write("Creating quote requests for rental listings...")
        rental_listings = [
            l for l in listings
            if l.listing_type in [Listing.Type.RENT, Listing.Type.LEASE]
        ]
        quotes = []

        if not buyers:
            return quotes

        for index, listing in enumerate(rental_listings):
            if QuoteRequest.objects.filter(listing=listing).exists():
                continue

            # Deterministic: every other rental gets a quote, so a repeated run
            # cannot decide differently once the random stream shifts.
            if index % 2:
                continue

            buyer = random.choice(buyers)
            if buyer == listing.user:
                continue

            quote = QuoteRequest.objects.create(
                listing=listing,
                buyer=buyer,
                store=listing.store,
                purchase_type=QuoteRequest.PurchaseType.RENT,
                quantity=random.randint(1, 3),
                duration_bucket=random.choice(
                    list(QuoteRequest.DurationBucket.values)),
                preferred_delivery_date=timezone.now().date() + timedelta(
                    days=random.randint(5, 15)),
                status=random.choice(list(QuoteRequest.Status.values)),
                notes=fake.sentence()
            )
            quotes.append(quote)
        return quotes

    def create_saved_items(self, listings, buyers):
        self.stdout.write("Creating saved items...")
        if not listings:
            return
        for index, buyer in enumerate(buyers):
            # Deterministic picks: a repeated run must select the same rows.
            if index % 3 == 0:
                continue
            picks = [
                listings[(index + offset) % len(listings)]
                for offset in range(min(2, len(listings)))
            ]
            for listing in picks:
                SavedItem.objects.get_or_create(user=buyer, listing=listing)

    def create_orders(self, listings, buyers, count):
        self.stdout.write(f"Creating {count} orders...")
        orders = []
        sellable = [l for l in listings if l.store_id]

        if not sellable or not buyers:
            self.stdout.write(self.style.WARNING(
                "Skipping orders: no sellable listings or buyers available."))
            return orders

        order_type_map = {
            Listing.Type.SELL: Order.OrderType.BUY,
            Listing.Type.RENT: Order.OrderType.HIRE,
            Listing.Type.LEASE: Order.OrderType.LEASE,
            Listing.Type.SERVICE: Order.OrderType.BUY
        }

        for i in range(count):
            order_number = f"{ORDER_NUMBER_PREFIX}{i + 1:04d}"
            existing = Order.objects.filter(order_number=order_number).first()
            if existing is not None:
                orders.append(existing)
                continue

            buyer = random.choice(buyers)
            listing = random.choice(sellable)
            if buyer == listing.user:
                continue

            order_type = order_type_map.get(
                listing.listing_type, Order.OrderType.BUY)
            unit_price = money(listing.price or Decimal("10000.00"))
            quantity = 1
            duration_days = (
                random.randint(3, 14)
                if order_type in (Order.OrderType.HIRE, Order.OrderType.LEASE)
                else None
            )
            # Commission is charged on goods only; delivery passes through.
            subtotal = money(unit_price * quantity * (duration_days or 1))
            delivery_fee = (
                money(random.randint(0, 5000))
                if order_type == Order.OrderType.BUY
                else money(0)
            )
            total = money(subtotal + delivery_fee)
            status = random.choice(
                [Order.Status.PAID, Order.Status.FULFILLED,
                 Order.Status.PENDING_PAYMENT])
            paid = status in (Order.Status.PAID, Order.Status.FULFILLED)
            rate = listing.store.commission_rate if paid else money(0)
            commission = (
                money(subtotal * rate / Decimal("100")) if paid else money(0)
            )
            placed_at = timezone.now() - timedelta(days=random.randint(1, 30))

            order = Order.objects.create(
                order_number=order_number,
                buyer=buyer,
                seller=listing.user,
                store=listing.store,
                currency="NGN",
                subtotal=subtotal,
                delivery_fee=delivery_fee,
                total_amount=total,
                escrow_fee=money(0),
                commission_rate=rate,
                commission_amount=commission,
                status=status,
                placed_at=placed_at
            )

            rental_start = (
                placed_at.date() + timedelta(days=2) if duration_days else None
            )
            OrderItem.objects.create(
                order=order,
                purchase_type=order_type,
                listing=listing,
                quantity=quantity,
                unit_price=unit_price,
                original_currency=listing.currency,
                original_unit_price=unit_price,
                exchange_rate=Decimal("1.00000000"),
                duration_days=duration_days,
                rental_start_date=rental_start,
                rental_end_date=(
                    rental_start + timedelta(days=duration_days)
                    if rental_start else None
                ),
            )

            OrderActivity.objects.create(
                order=order,
                event_type=OrderActivity.EventType.ORDER_PLACED,
                message="Sample order placed."
            )

            if paid:
                checkout = CheckoutSession.objects.create(
                    buyer=buyer,
                    total_amount=total,
                    currency="NGN",
                )
                order.checkout_session = checkout
                order.save(update_fields=['checkout_session'])

                # Create Payment
                Payment.objects.create(
                    checkout_session=checkout,
                    buyer=buyer,
                    amount=total,
                    currency="NGN",
                    reference=f"PAY-{order_number}",
                    status=Payment.Status.SUCCESS,
                    paid_at=placed_at + timedelta(minutes=10)
                )
                OrderActivity.objects.create(
                    order=order,
                    event_type=OrderActivity.EventType.PAYMENT_CONFIRMED,
                    message="Sample payment confirmed."
                )

                if status == Order.Status.FULFILLED:
                    OrderActivity.objects.create(
                        order=order,
                        event_type=OrderActivity.EventType.SHIPPED,
                        message="Items have been shipped."
                    )
                    OrderActivity.objects.create(
                        order=order,
                        event_type=OrderActivity.EventType.DELIVERED,
                        message="Items delivered successfully."
                    )

                    # Randomly create a dispute for 10% of fulfilled orders
                    if random.random() < 0.1:
                        Dispute.objects.create(
                            order=order,
                            buyer=buyer,
                            reason="Item not as described",
                            description="The equipment received has some wear and tear not mentioned in the listing.",
                            status=Dispute.Status.OPEN
                        )

            orders.append(order)
        return orders

    def create_financials(self, orders):
        self.stdout.write("Creating financial records (wallets & earnings)...")
        for order in orders:
            if order.status not in [Order.Status.PAID, Order.Status.FULFILLED]:
                continue
            if not order.store_id:
                continue

            # Create Bank Account if missing
            BankAccount.objects.get_or_create(
                user=order.seller,
                store=order.store,
                defaults={
                    'account_name': order.seller.get_full_name(),
                    'account_number': f"00{random.randint(10000000, 99999999)}",
                    'bank_name': 'Sample Bank PLC'
                }
            )

            # One earning per order; commission/net are written explicitly.
            earning = accrue_earning(order)
            if earning is None:
                continue

            if order.status == Order.Status.FULFILLED:
                # Fulfilled sample orders have already cleared their hold.
                if earning.first_release_at and earning.first_release_at > timezone.now():
                    earning.first_release_at = (
                        order.placed_at or timezone.now()) + timedelta(days=7)
                    earning.available_at = earning.first_release_at
                    earning.save(
                        update_fields=["first_release_at", "available_at"])
                release_earning(
                    earning, earning.net_amount - earning.released_amount)

    def create_reviews(self, orders, buyers):
        self.stdout.write("Creating reviews...")
        for order in orders:
            if order.status != Order.Status.FULFILLED:
                continue

            first_item = order.items.first()
            if not first_item or not first_item.listing_id:
                continue

            # Listing Review
            ListingReview.objects.get_or_create(
                listing=first_item.listing,
                reviewer=order.buyer,
                defaults={
                    'rating': random.randint(3, 5),
                    'comment': fake.sentence()
                }
            )

            # Store Review
            if order.store:
                StoreReview.objects.get_or_create(
                    store=order.store,
                    reviewer=order.buyer,
                    defaults={
                        'rating': random.randint(4, 5),
                        'comment': fake.sentence()
                    }
                )

    def create_notifications(self, users):
        self.stdout.write("Creating sample notifications...")
        from apps.notifications.models import Notification

        for user in users:
            if Notification.objects.filter(recipient=user).exists():
                continue

            # Create 3-7 notifications for every user
            for _ in range(random.randint(3, 7)):
                n_type = random.choice(
                    list(Notification.NotificationType.values))
                Notification.objects.create(
                    recipient=user,
                    notification_type=n_type,
                    title=f"Sample {n_type.replace('_', ' ').title()}",
                    message=fake.sentence(),
                    priority=random.choice(list(Notification.Priority.values)),
                    is_read=random.choice([True, False, False])
                )
