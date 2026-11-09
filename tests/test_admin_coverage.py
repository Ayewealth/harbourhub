import pytest
from django.contrib import admin

from apps.accounts.models import (
    DeliveryDetail, PasswordResetToken, UserPreference, UserSession, UserTwoFactor,
    VerificationRequest,
)
from apps.admin_panel.models import (
    AdminProfile, JobListing, PlatformConfig, RolePermission,
)
from apps.commerce.models import (
    Cart, CartItem, CheckoutSession, Dispute, Order, OrderActivity, OrderItem,
    Payment, QuoteRequest, Refund, RentalExtension, WebhookEvent,
)
from apps.compliance.models import ComplianceDocument
from apps.core.models import Feedback
from apps.financials.models import (
    BankAccount, Payout, PayoutAllocation, VendorEarning, VendorWallet,
    WalletTransaction,
)
from apps.listings.models import SavedItem
from apps.messaging.models import Conversation, Message
from apps.notifications.models import (
    Notification, NotificationDelivery, NotificationPreference, PushSubscription,
)
from apps.support.models import SupportTicket

MODELS = [
    Order, OrderItem, OrderActivity, CheckoutSession, Payment, Cart, CartItem,
    QuoteRequest, RentalExtension, WebhookEvent, Refund, Dispute,
    BankAccount, VendorEarning, Payout, VendorWallet, WalletTransaction,
    PayoutAllocation,
    Notification, NotificationPreference, NotificationDelivery, PushSubscription,
    SupportTicket, ComplianceDocument, Conversation, Message,
    PasswordResetToken, VerificationRequest, DeliveryDetail, UserPreference,
    UserTwoFactor, UserSession,
    RolePermission, AdminProfile, PlatformConfig, JobListing,
    SavedItem, Feedback,
]


@pytest.mark.parametrize("model", MODELS, ids=lambda model: model.__name__)
def test_model_is_registered_in_the_admin(model):
    assert admin.site.is_registered(model)
