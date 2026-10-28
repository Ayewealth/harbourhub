from decimal import Decimal

import django.db.models.deletion
from django.db import migrations, models


def backfill_and_guard(apps, schema_editor):
    Order = apps.get_model("commerce", "Order")
    unresolved = []

    for order in Order.objects.filter(store__isnull=True).iterator():
        item = (
            order.items.select_related("listing__store").first()
            if hasattr(order, "items")
            else None
        )
        store_id = None
        if item is not None and item.listing_id is not None:
            store_id = item.listing.store_id
        if store_id is None:
            try:
                store_id = order.seller.store_id
            except Exception:
                store_id = None
        if store_id is None:
            unresolved.append(order.order_number)
            continue
        order.store_id = store_id
        order.save(update_fields=["store"])

    if unresolved:
        raise RuntimeError(
            "Cannot make Order.store non-null; unresolved orders: "
            + ", ".join(unresolved)
        )


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("commerce", "0011_refund_model"),
        ("store", "0006_remove_store_user_role_limit"),
    ]

    operations = [
        migrations.AddField(
            model_name="order",
            name="commission_rate",
            field=models.DecimalField(
                decimal_places=2, default=Decimal("0.00"), max_digits=5
            ),
        ),
        migrations.AddField(
            model_name="order",
            name="commission_amount",
            field=models.DecimalField(
                decimal_places=2, default=Decimal("0.00"), max_digits=14
            ),
        ),
        migrations.AddField(
            model_name="order",
            name="shipped_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="order",
            name="delivered_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="order",
            name="completed_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="order",
            name="cancelled_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="order",
            name="cancellation_reason",
            field=models.TextField(blank=True),
        ),
        migrations.AddField(
            model_name="orderitem",
            name="original_currency",
            field=models.CharField(default="NGN", max_length=3),
        ),
        migrations.AddField(
            model_name="orderitem",
            name="original_unit_price",
            field=models.DecimalField(
                blank=True, decimal_places=2, max_digits=14, null=True
            ),
        ),
        migrations.AddField(
            model_name="orderitem",
            name="exchange_rate",
            field=models.DecimalField(
                decimal_places=8,
                default=Decimal("1.00000000"),
                help_text="NGN per unit of original_currency at checkout",
                max_digits=18,
            ),
        ),
        migrations.RunPython(backfill_and_guard, noop),
        migrations.AlterField(
            model_name="order",
            name="store",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.PROTECT,
                related_name="orders",
                to="store.store",
            ),
        ),
    ]
