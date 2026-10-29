from decimal import Decimal

import factory
from django.utils import timezone

from apps.accounts.models import User
from apps.categories.models import Category
from apps.commerce.models import Cart, CartItem, CheckoutSession, Order, OrderItem, Payment
from apps.financials.models import Payout, VendorEarning, VendorWallet
from apps.listings.models import Listing
from apps.store.models import Store


class UserFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = User
        skip_postgeneration_save = True

    email = factory.Sequence(lambda n: f"user{n}@example.com")
    username = factory.Sequence(lambda n: f"user{n}")
    full_name = "Test User"
    role = User.Role.BUYER

    @factory.post_generation
    def password(self, create, extracted, **kwargs):
        self.set_password(extracted or "TestPass123!")
        if create:
            self.save(update_fields=["password"])


class StoreFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Store

    user = factory.SubFactory(UserFactory, role=User.Role.SELLER)
    name = factory.Sequence(lambda n: f"Store {n}")
    slug = factory.Sequence(lambda n: f"store-{n}")
    policy = "Standard store policy"
    is_active = True
    is_published = True


class CategoryFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Category

    name = factory.Sequence(lambda n: f"Category {n}")
    slug = factory.Sequence(lambda n: f"category-{n}")
    is_active = True


class ListingFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Listing

    user = factory.SelfAttribute("store.user")
    store = factory.SubFactory(StoreFactory)
    category = factory.SubFactory(CategoryFactory)
    title = factory.Sequence(lambda n: f"Listing {n}")
    description = "A test listing"
    listing_type = Listing.Type.SELL
    price = Decimal("1000.00")
    currency = "NGN"
    location = "Lagos"
    contact_name = "Test User"
    contact_email = "seller@example.com"
    status = Listing.Status.PUBLISHED


class CheckoutSessionFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = CheckoutSession

    buyer = factory.SubFactory(UserFactory)
    total_amount = Decimal("1000.00")
    currency = "NGN"


class OrderFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Order

    order_number = factory.Sequence(lambda n: f"ORD-TEST-{n}")
    buyer = factory.SubFactory(UserFactory)
    seller = factory.SelfAttribute("store.user")
    store = factory.SubFactory(StoreFactory)
    checkout_session = factory.SubFactory(CheckoutSessionFactory)
    currency = "NGN"
    subtotal = Decimal("1000.00")
    total_amount = Decimal("1000.00")
    commission_rate = Decimal("5.00")
    commission_amount = Decimal("0.00")
    delivered_at = None
    completed_at = None
    status = Order.Status.PENDING_PAYMENT
    placed_at = factory.LazyFunction(timezone.now)


class OrderItemFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = OrderItem

    order = factory.SubFactory(OrderFactory)
    listing = factory.SubFactory(ListingFactory)
    purchase_type = Order.OrderType.BUY
    quantity = 1
    unit_price = Decimal("1000.00")
    original_currency = "NGN"
    original_unit_price = Decimal("1000.00")
    exchange_rate = Decimal("1.00000000")


class PaymentFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Payment

    checkout_session = factory.SubFactory(CheckoutSessionFactory)
    buyer = factory.SelfAttribute("checkout_session.buyer")
    amount = Decimal("1000.00")
    currency = "NGN"
    reference = factory.Sequence(lambda n: f"PAY-TEST-{n}")
    status = Payment.Status.PENDING


class CartFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Cart

    buyer = factory.SubFactory(UserFactory)


class CartItemFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = CartItem

    cart = factory.SubFactory(CartFactory)
    listing = factory.SubFactory(ListingFactory)
    store = factory.SelfAttribute("listing.store")
    purchase_type = CartItem.PurchaseType.BUY
    quantity = 1
    unit_price = Decimal("1000.00")


class VendorWalletFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = VendorWallet

    user = factory.SelfAttribute("store.user")
    store = factory.SubFactory(StoreFactory)
    currency = "NGN"


class VendorEarningFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = VendorEarning

    vendor = factory.SelfAttribute("store.user")
    store = factory.SubFactory(StoreFactory)
    order = factory.SubFactory(OrderFactory)
    earning_type = VendorEarning.EarningType.BUY
    gross_amount = Decimal("1000.00")
    commission_rate = Decimal("5.00")
    commission_amount = Decimal("50.00")
    net_amount = Decimal("950.00")
    currency = "NGN"
    status = VendorEarning.Status.PENDING
    available_at = factory.LazyFunction(timezone.now)


class PayoutFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Payout

    vendor = factory.SelfAttribute("store.user")
    store = factory.SubFactory(StoreFactory)
    amount = Decimal("100.00")
    currency = "NGN"
    reference = factory.Sequence(lambda n: f"PO-TEST-{n}")
    status = Payout.Status.REQUESTED
