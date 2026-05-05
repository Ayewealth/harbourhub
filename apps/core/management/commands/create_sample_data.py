import random
import uuid
from decimal import Decimal
from datetime import timedelta

from django.core.management.base import BaseCommand
from django.contrib.auth import get_user_model
from django.db import transaction
from django.utils import timezone
from faker import Faker

from apps.categories.models import Category
from apps.listings.models import Listing, ListingImage, SavedItem
from apps.store.models import Store, StoreActivity
from apps.commerce.models import Cart, CartItem, Order, OrderActivity, Payment, QuoteRequest, Dispute
from apps.financials.models import VendorWallet, VendorEarning, Payout, BankAccount, WalletTransaction
from apps.reviews.models import ListingReview, StoreReview
from apps.accounts.models import VerificationRequest, DeliveryDetail, UserPreference
from apps.inquiries.models import Inquiry

fake = Faker()
User = get_user_model()


class Command(BaseCommand):
    help = "Generate comprehensive sample data for all apps and link them together."

    def add_arguments(self, parser):
        parser.add_argument("--users", type=int, default=30, help="Number of users")
        parser.add_argument("--listings", type=int, default=100, help="Number of listings")
        parser.add_argument("--orders", type=int, default=20, help="Number of orders")
        parser.add_argument("--clean", action="store_true", help="Delete all existing data before creating new sample data")

    @transaction.atomic
    def handle(self, *args, **options):
        self.stdout.write(self.style.NOTICE("🚀 Starting sample data generation..."))

        if options["clean"]:
            self.stdout.write(self.style.WARNING("🧹 Cleaning up existing data..."))
            self.clean_data()

        # Check if DB is already populated (any core data exists)
        has_users = User.objects.exclude(role=User.Role.SUPER_ADMIN).exists()
        has_listings = Listing.objects.exists()
        has_categories = Category.objects.exists()

        if (has_users or has_listings or has_categories) and not options["clean"]:
            self.stdout.write(self.style.WARNING("⚠️ Sample data already exists. Skipping to prevent duplicates."))
            return

        # 1. Categories
        self.create_categories()
        
        # 2. Users (Buyers, Sellers, Providers)
        users = self.create_users(options["users"])
        buyers = [u for u in users if u.role == User.Role.BUYER]
        sellers = [u for u in users if u.role == User.Role.SELLER]
        providers = [u for u in users if u.role == User.Role.SERVICE_PROVIDER]
        admins = [u for u in users if u.is_admin_user]

        # 3. Verification Requests
        self.create_verification_requests(sellers + providers, admins[0] if admins else None)

        # 4. Stores (for Sellers)
        stores = self.create_stores(sellers)

        # 5. Listings
        listings = self.create_listings(options["listings"], sellers, providers)

        # 6. Listing Images
        self.create_listing_images(listings)

        # 7. Inquiries
        self.create_inquiries(listings, buyers)

        # 8. Quote Requests
        quotes = self.create_quote_requests(listings, buyers)

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

        self.stdout.write(self.style.SUCCESS("\n✅ Successfully created comprehensive sample data!"))

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
        self.stdout.write(f"Creating {count} users...")
        users = []
        
        # Ensure at least one admin
        if not User.objects.filter(role=User.Role.SUPER_ADMIN).exists():
            admin = User.objects.create_superuser(
                email="admin@harbourhub.com",
                password="password123",
                username="admin",
                full_name="System Admin",
                role=User.Role.SUPER_ADMIN,
                is_verified=True
            )
            users.append(admin)

        roles = [User.Role.BUYER] * 15 + [User.Role.SELLER] * 10 + [User.Role.SERVICE_PROVIDER] * 5
        random.shuffle(roles)
        
        for i in range(count):
            role = roles[i % len(roles)]
            email = f"user{i+1}@{fake.free_email_domain()}"
            user = User.objects.create_user(
                email=email,
                password="password123",
                username=f"user_{i+1}",
                full_name=fake.name(),
                role=role,
                company=fake.company() if role != User.Role.BUYER else "",
                location=fake.city(),
                phone=fake.phone_number()[:20],
                is_verified=(role == User.Role.BUYER or random.choice([True, False]))
            )
            
            # Preferences
            UserPreference.objects.create(
                user=user,
                interested_categories=[random.randint(1, 10) for _ in range(3)]
            )
            
            # Delivery Details
            DeliveryDetail.objects.create(
                user=user,
                contact_person=user.full_name,
                country="Nigeria",
                state=fake.state(),
                city=fake.city(),
                address=fake.address(),
                phone=user.phone,
                is_default=True
            )
            
            users.append(user)
        return users

    def create_verification_requests(self, vendors, admin):
        self.stdout.write("Creating verification requests...")
        for vendor in vendors:
            req = VerificationRequest.objects.create(
                user=vendor,
                company_name=vendor.company or fake.company(),
                certifications=fake.text(),
                status=random.choice([VerificationRequest.Status.APPROVED, VerificationRequest.Status.PENDING])
            )
            if req.status == VerificationRequest.Status.APPROVED and admin:
                req.approve(admin, notes="Looks good.")

    def create_stores(self, sellers):
        self.stdout.write("Creating stores for sellers...")
        stores = []
        categories = list(Category.objects.all())
        for seller in sellers:
            store = Store.objects.create(
                user=seller,
                name=f"{seller.company or seller.full_name} Store",
                slug=f"store-{uuid.uuid4().hex[:8]}",
                description=fake.paragraph(),
                email=seller.email[:255],
                phone=(seller.phone or fake.phone_number())[:20],
                address=fake.address(),
                is_verified=seller.is_verified,
                is_active=True,
                is_published=True,
                policy=fake.text()
            )
            store.categories.add(*random.sample(categories, k=random.randint(1, 3)))
            stores.append(store)
        return stores

    def create_listings(self, count, sellers, providers):
        self.stdout.write(f"Creating {count} listings...")
        listings = []
        leaf_categories = list(Category.objects.filter(children__isnull=True))
        
        # Combine sellers and providers for listing creation
        for i in range(count):
            owner = random.choice(sellers + providers)
            category = random.choice(leaf_categories)
            
            # Determine listing type
            if owner.role == User.Role.SERVICE_PROVIDER:
                l_type = Listing.Type.SERVICE
            else:
                l_type = random.choice([Listing.Type.SELL, Listing.Type.RENT, Listing.Type.LEASE])
            
            store = getattr(owner, 'store', None)
            
            listing = Listing.objects.create(
                user=owner,
                store=store,
                title=f"{fake.word().capitalize()} {category.name}",
                description=fake.text(max_nb_chars=500),
                category=category,
                listing_type=l_type,
                price=Decimal(random.randint(5000, 500000)),
                currency="NGN",
                price_unit="per day" if l_type in [Listing.Type.RENT, Listing.Type.LEASE] else "total",
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
            ListingImage.objects.create(
                listing=listing,
                is_primary=True,
                sort_order=0
            )

    def create_inquiries(self, listings, buyers):
        self.stdout.write("Creating inquiries for all listings...")
        from apps.inquiries.models import InquiryReply
        
        for listing in listings:
            # Create 1-3 inquiries for EVERY listing
            num_inquiries = random.randint(1, 3)
            for _ in range(num_inquiries):
                buyer = random.choice(buyers)
                if buyer == listing.user: continue
                
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
        rental_listings = [l for l in listings if l.listing_type in [Listing.Type.RENT, Listing.Type.LEASE]]
        quotes = []
        
        for listing in rental_listings:
            # 50% chance for a rental to have a quote
            if random.choice([True, False]):
                buyer = random.choice(buyers)
                if buyer == listing.user: continue
                
                quote = QuoteRequest.objects.create(
                    listing=listing,
                    buyer=buyer,
                    store=listing.store,
                    purchase_type=QuoteRequest.PurchaseType.RENT,
                    quantity=random.randint(1, 3),
                    duration_bucket=random.choice(list(QuoteRequest.DurationBucket.values)),
                    preferred_delivery_date=timezone.now().date() + timedelta(days=random.randint(5, 15)),
                    status=random.choice(list(QuoteRequest.Status.values)),
                    notes=fake.sentence()
                )
                quotes.append(quote)
        return quotes

    def create_saved_items(self, listings, buyers):
        self.stdout.write("Creating saved items...")
        for buyer in buyers:
            saved_listings = random.sample(listings, k=random.randint(0, 5))
            for l in saved_listings:
                SavedItem.objects.get_or_create(user=buyer, listing=l)

    def create_orders(self, listings, buyers, count):
        self.stdout.write(f"Creating {count} orders...")
        orders = []
        for i in range(count):
            buyer = random.choice(buyers)
            listing = random.choice(listings)
            if buyer == listing.user: continue
            
            order_type_map = {
                Listing.Type.SELL: Order.OrderType.BUY,
                Listing.Type.RENT: Order.OrderType.HIRE,
                Listing.Type.LEASE: Order.OrderType.LEASE,
                Listing.Type.SERVICE: Order.OrderType.BUY
            }
            
            total = listing.price or Decimal('10000.00')
            order = Order.objects.create(
                order_number=f"ORD-{uuid.uuid4().hex[:12].upper()}",
                order_type=order_type_map.get(listing.listing_type, Order.OrderType.BUY),
                buyer=buyer,
                seller=listing.user,
                listing=listing,
                store=listing.store,
                total_amount=total,
                status=random.choice([Order.Status.PAID, Order.Status.FULFILLED, Order.Status.PENDING_PAYMENT]),
                placed_at=timezone.now() - timedelta(days=random.randint(1, 30)),
                delivery_address=fake.address()
            )
            
            OrderActivity.objects.create(
                order=order,
                event_type=OrderActivity.EventType.ORDER_PLACED,
                message="Sample order placed."
            )
            
            if order.status in [Order.Status.PAID, Order.Status.FULFILLED]:
                # Create Payment
                Payment.objects.create(
                    order=order,
                    buyer=buyer,
                    amount=total,
                    reference=f"PAY-{uuid.uuid4().hex[:16].upper()}",
                    status=Payment.Status.SUCCESS,
                    paid_at=order.placed_at + timedelta(minutes=10)
                )
                OrderActivity.objects.create(
                    order=order,
                    event_type=OrderActivity.EventType.PAYMENT_CONFIRMED,
                    message="Sample payment confirmed."
                )
                
                if order.status == Order.Status.FULFILLED:
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
                
            # Ensure Wallet
            wallet, _ = VendorWallet.objects.get_or_create(
                user=order.seller,
                store=order.store,
                defaults={'currency': order.currency}
            )
            
            # Create Bank Account if missing
            bank, _ = BankAccount.objects.get_or_create(
                user=order.seller,
                defaults={
                    'account_name': order.seller.full_name,
                    'account_number': fake.bban()[:10],
                    'bank_name': 'Sample Bank PLC'
                }
            )
            
            # Create Earning
            earning = VendorEarning.objects.create(
                vendor=order.seller,
                store=order.store,
                order=order,
                listing=order.listing,
                earning_type=order.order_type,
                gross_amount=order.total_amount,
                status=VendorEarning.Status.AVAILABLE if order.status == Order.Status.FULFILLED else VendorEarning.Status.PENDING
            )
            
            if earning.status == VendorEarning.Status.AVAILABLE:
                wallet.available_balance += earning.net_amount
            else:
                wallet.pending_balance += earning.net_amount
            wallet.save()

    def create_reviews(self, orders, buyers):
        self.stdout.write("Creating reviews...")
        for order in orders:
            if order.status != Order.Status.FULFILLED:
                continue
            
            # Listing Review
            ListingReview.objects.get_or_create(
                listing=order.listing,
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
            # Create 3-7 notifications for every user
            for _ in range(random.randint(3, 7)):
                n_type = random.choice(list(Notification.NotificationType.values))
                Notification.objects.create(
                    recipient=user,
                    notification_type=n_type,
                    title=f"Sample {n_type.replace('_', ' ').title()}",
                    message=fake.sentence(),
                    priority=random.choice(list(Notification.Priority.values)),
                    is_read=random.choice([True, False, False])
                )
