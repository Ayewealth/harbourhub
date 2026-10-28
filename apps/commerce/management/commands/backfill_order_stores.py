from django.core.management.base import BaseCommand
from django.db import transaction

from apps.commerce.models import Order


class Command(BaseCommand):
    help = "Derive Order.store from its item's listing or its seller's store."

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true")

    def handle(self, *args, **options):
        dry_run = options["dry_run"]
        unresolved = []

        for order in Order.objects.filter(store__isnull=True).select_related(
            "seller"
        ):
            store = None
            item = order.items.select_related("listing__store").first()
            if item and item.listing and item.listing.store_id:
                store = item.listing.store
            elif getattr(order.seller, "store", None):
                store = order.seller.store

            if store is None:
                unresolved.append(order.order_number)
                continue

            self.stdout.write(
                f"{order.order_number}: store -> {store.pk} ({store.name})"
            )
            if not dry_run:
                with transaction.atomic():
                    Order.objects.filter(
                        pk=order.pk, store__isnull=True
                    ).update(store=store, seller=store.user)

        if unresolved:
            self.stderr.write(
                "Unresolved orders (fix manually, then re-run): "
                + ", ".join(unresolved)
            )
        else:
            self.stdout.write(
                self.style.SUCCESS("All orders have a store.")
            )
