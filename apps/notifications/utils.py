import logging
from typing import Optional

logger = logging.getLogger(__name__)


def create_notification(
    recipient,
    notification_type: str,
    title: str,
    message: str,
    priority: str = 'medium',
    action_url: str = '',
    action_label: str = '',
    related_object_type: str = '',
    related_object_id: Optional[int] = None,
):
    """
    Create a notification for a user.
    Safe to call anywhere — catches all exceptions so it
    never breaks the main flow.
    """
    try:
        from .models import Notification
        notif = Notification.objects.create(
            recipient=recipient,
            notification_type=notification_type,
            title=title,
            message=message,
            priority=priority,
            action_url=action_url,
            action_label=action_label,
            related_object_type=related_object_type,
            related_object_id=related_object_id,
        )
        return notif
    except Exception as exc:
        logger.exception("Failed to create notification: %s", exc)
        return None


# ─── Convenience helpers ────────────────────────────────────────────────────

def notify_order_placed(order):
    """Notify vendor that a new order was placed."""
    create_notification(
        recipient=order.seller,
        notification_type='order_placed',
        title='New Order Received',
        message=(
            f"Order #{order.order_number} has been placed "
            f"for {order.listing.title if order.listing else 'your product'}."
        ),
        priority='high',
        action_url=f"/vendor/orders/{order.id}",
        action_label="View Order",
        related_object_type='order',
        related_object_id=order.id,
    )


def notify_order_paid(order):
    """Notify both buyer and vendor when payment is confirmed."""
    # Notify buyer
    create_notification(
        recipient=order.buyer,
        notification_type='payment_success',
        title='Payment Confirmed',
        message=(
            f"Your payment for order #{order.order_number} "
            f"was successful. Funds are held in escrow."
        ),
        priority='high',
        action_url=f"/orders/{order.id}",
        action_label="View Order",
        related_object_type='order',
        related_object_id=order.id,
    )
    # Notify vendor
    create_notification(
        recipient=order.seller,
        notification_type='order_paid',
        title='Payment Received',
        message=(
            f"Payment for order #{order.order_number} has been "
            f"confirmed. Please prepare the order for shipment."
        ),
        priority='high',
        action_url=f"/vendor/orders/{order.id}",
        action_label="View Order",
        related_object_type='order',
        related_object_id=order.id,
    )


def notify_order_shipped(order):
    """Notify buyer that order has been shipped."""
    create_notification(
        recipient=order.buyer,
        notification_type='order_shipped',
        title='Order Shipped',
        message=(
            f"Your order #{order.order_number} has been shipped. "
            f"Tracking ID: {order.tracking_id or 'Not available yet'}."
        ),
        priority='medium',
        action_url=f"/orders/{order.id}",
        action_label="Track Order",
        related_object_type='order',
        related_object_id=order.id,
    )


def notify_order_delivered(order):
    """Notify buyer that order has been delivered."""
    create_notification(
        recipient=order.buyer,
        notification_type='order_delivered',
        title='Order Delivered',
        message=(
            f"Your order #{order.order_number} has been delivered. "
            f"Please confirm receipt."
        ),
        priority='high',
        action_url=f"/orders/{order.id}",
        action_label="Confirm Delivery",
        related_object_type='order',
        related_object_id=order.id,
    )


def notify_order_cancelled(order, cancelled_by):
    """Notify both parties when an order is cancelled."""
    other = order.seller if cancelled_by == order.buyer else order.buyer
    create_notification(
        recipient=other,
        notification_type='order_cancelled',
        title='Order Cancelled',
        message=f"Order #{order.order_number} has been cancelled.",
        priority='high',
        action_url=f"/orders/{order.id}",
        action_label="View Order",
        related_object_type='order',
        related_object_id=order.id,
    )


def notify_quote_received(quote):
    """Notify vendor of new quote request."""
    create_notification(
        recipient=quote.listing.user,
        notification_type='quote_received',
        title='New Quote Request',
        message=(
            f"{quote.buyer.get_full_name() or quote.buyer.email} "
            f"requested a quote for {quote.listing.title}."
        ),
        priority='high',
        action_url=f"/vendor/quotes/{quote.id}",
        action_label="View Quote",
        related_object_type='quote',
        related_object_id=quote.id,
    )


def notify_quote_responded(quote):
    """Notify buyer that vendor responded to quote."""
    create_notification(
        recipient=quote.buyer,
        notification_type='quote_responded',
        title='Quote Response Received',
        message=(
            f"The vendor has responded to your quote request "
            f"for {quote.listing.title}."
        ),
        priority='high',
        action_url=f"/quotes/{quote.id}",
        action_label="View Quote",
        related_object_type='quote',
        related_object_id=quote.id,
    )


def notify_new_inquiry(inquiry):
    """Notify listing owner of new inquiry."""
    create_notification(
        recipient=inquiry.to_user,
        notification_type='new_inquiry',
        title='New Inquiry',
        message=(
            f"{inquiry.contact_name} sent an inquiry about "
            f"{inquiry.listing.title}."
        ),
        priority='medium',
        action_url=f"/inquiries/{inquiry.id}",
        action_label="View Inquiry",
        related_object_type='inquiry',
        related_object_id=inquiry.id,
    )


def notify_inquiry_replied(inquiry):
    """Notify inquirer that their inquiry was replied to."""
    create_notification(
        recipient=inquiry.from_user,
        notification_type='inquiry_replied',
        title='Inquiry Reply Received',
        message=(
            f"You have a new reply to your inquiry about "
            f"{inquiry.listing.title}."
        ),
        priority='medium',
        action_url=f"/inquiries/{inquiry.id}",
        action_label="View Reply",
        related_object_type='inquiry',
        related_object_id=inquiry.id,
    )


def notify_new_review(review, target_user):
    """Notify vendor/seller of a new review."""
    create_notification(
        recipient=target_user,
        notification_type='new_review',
        title='New Review',
        message=(
            f"You received a {review.rating}-star review."
        ),
        priority='low',
        related_object_type='review',
        related_object_id=review.id,
    )


def notify_payout_processed(payout):
    """Notify vendor that payout was processed."""
    create_notification(
        recipient=payout.vendor,
        notification_type='payout_processed',
        title='Payout Successful',
        message=(
            f"Your payout of {payout.currency} "
            f"{payout.amount:,.2f} has been processed successfully."
        ),
        priority='high',
        action_url="/financials/payouts",
        action_label="View Payouts",
        related_object_type='payout',
        related_object_id=payout.id,
    )


def notify_payout_failed(payout):
    """Notify vendor that payout failed."""
    create_notification(
        recipient=payout.vendor,
        notification_type='payout_failed',
        title='Payout Failed',
        message=(
            f"Your payout of {payout.currency} "
            f"{payout.amount:,.2f} failed. "
            f"Reason: {payout.failure_reason or 'Unknown error'}."
        ),
        priority='high',
        action_url="/financials/payouts",
        action_label="View Payouts",
        related_object_type='payout',
        related_object_id=payout.id,
    )


def notify_verification_approved(user):
    create_notification(
        recipient=user,
        notification_type='verification_approved',
        title='Verification Approved',
        message="Your account has been verified successfully.",
        priority='high',
        action_url="/store",
        action_label="View Store",
    )


def notify_verification_rejected(user, notes=''):
    create_notification(
        recipient=user,
        notification_type='verification_rejected',
        title='Verification Rejected',
        message=(
            f"Your verification request was rejected. "
            f"{f'Reason: {notes}' if notes else ''}"
        ),
        priority='high',
    )


def notify_rental_reminder(order, days_left: int):
    """Notify buyer that rental is ending soon."""
    create_notification(
        recipient=order.buyer,
        notification_type='rental_reminder',
        title='Rental Ending Soon',
        message=(
            f"Your rental for order #{order.order_number} "
            f"ends in {days_left} day(s). "
            f"Consider extending if needed."
        ),
        priority='high',
        action_url=f"/orders/{order.id}",
        action_label="Extend Rental",
        related_object_type='order',
        related_object_id=order.id,
    )
