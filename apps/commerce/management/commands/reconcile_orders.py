from decimal import Decimal

from django.core.management.base import BaseCommand

from apps.commerce.models import Order
from apps.financials.models import VendorEarning, VendorWallet


class Command(BaseCommand):
    help = "Repair pre-P0 orders, stores, and earnings without deleting data."

    def add_arguments(self, parser):
        parser.add_argument(
            "--apply", action="store_true", help="Write changes.")
        parser.add_argument(
            "--dry-run", action="store_true", help="Print changes only.")

    def handle(self, *args, **options):
        apply = options["apply"]
        if not apply:
            self.stdout.write(
                self.style.WARNING("DRY RUN — pass --apply to write."))

        changed = {"orders": 0, "earnings": 0, "wallets": 0, "fees": 0}

        for order in Order.objects.all().iterator():
            updates = []
            item = order.items.select_related("listing__store").first()
            if (
                item
                and not order.store_id
                and item.listing
                and item.listing.store_id
            ):
                order.store_id = item.listing.store_id
                updates.append("store")
            if order.store_id and order.store.user_id != order.seller_id:
                order.seller_id = order.store.user_id
                updates.append("seller")
            if order.status == Order.Status.PENDING_PAYMENT and order.escrow_fee:
                order.total_amount = max(
                    order.total_amount - order.escrow_fee, Decimal("0.00"))
                order.escrow_fee = Decimal("0.00")
                updates.extend(["total_amount", "escrow_fee"])
                changed["fees"] += 1
            if updates:
                changed["orders"] += 1
                self.stdout.write(
                    f"Order {order.pk}: {', '.join(sorted(set(updates)))}")
                if apply:
                    order.save(update_fields=sorted(set(updates)))

        for earning in VendorEarning.objects.filter(
            order__isnull=False
        ).select_related("order", "vendor", "store").iterator():
            order = earning.order
            if order.status not in (
                Order.Status.PAID, Order.Status.FULFILLED,
            ):
                continue
            if order.currency != "NGN":
                continue
            _, created = VendorWallet.objects.get_or_create(
                user=earning.vendor,
                store=earning.store,
                defaults={"currency": earning.currency},
            )
            if created:
                changed["wallets"] += 1
                self.stdout.write(
                    f"Wallet created for "
                    f"{earning.vendor_id}/{earning.store_id}")

        if apply:
            self.stdout.write(self.style.SUCCESS(f"Applied: {changed}"))
        else:
            self.stdout.write(self.style.WARNING(f"Would apply: {changed}"))
