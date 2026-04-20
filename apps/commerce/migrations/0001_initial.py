import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("listings", "0005_listing_store"),
        ("store", "0001_initial"),
    ]

    operations = [
        migrations.CreateModel(
            name="QuoteRequest",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("purchase_type", models.CharField(max_length=10)),
                ("quantity", models.PositiveIntegerField(default=1)),
                ("duration_bucket", models.CharField(blank=True, max_length=32)),
                ("preferred_delivery_date", models.DateField(blank=True, null=True)),
                ("delivery_location", models.CharField(blank=True, max_length=500)),
                ("notes", models.TextField(blank=True)),
                ("status", models.CharField(db_index=True, default="pending", max_length=20)),
                ("created_at", models.DateTimeField(auto_now_add=True, db_index=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "buyer",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="quote_requests",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "listing",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="quote_requests",
                        to="listings.listing",
                    ),
                ),
                (
                    "store",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="quote_requests",
                        to="store.store",
                    ),
                ),
            ],
            options={
                "db_table": "quote_requests",
                "ordering": ["-created_at"],
            },
        ),
        migrations.CreateModel(
            name="Order",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("order_number", models.CharField(db_index=True, max_length=40, unique=True)),
                ("order_type", models.CharField(db_index=True, max_length=16)),
                ("currency", models.CharField(default="NGN", max_length=3)),
                ("total_amount", models.DecimalField(decimal_places=2, max_digits=14)),
                ("status", models.CharField(db_index=True, default="draft", max_length=32)),
                ("placed_at", models.DateTimeField(blank=True, db_index=True, null=True)),
                ("extra", models.JSONField(blank=True, default=dict)),
                ("created_at", models.DateTimeField(auto_now_add=True, db_index=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "buyer",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="orders_as_buyer",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "listing",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="orders",
                        to="listings.listing",
                    ),
                ),
                (
                    "quote_request",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="orders",
                        to="commerce.quoterequest",
                    ),
                ),
                (
                    "seller",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="orders_as_seller",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "store",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="orders",
                        to="store.store",
                    ),
                ),
            ],
            options={
                "db_table": "commerce_orders",
                "ordering": ["-created_at"],
            },
        ),
        migrations.AddIndex(
            model_name="quoterequest",
            index=models.Index(fields=["status", "-created_at"], name="quote_req_status_created_idx"),
        ),
        migrations.AddIndex(
            model_name="order",
            index=models.Index(
                fields=["order_type", "-placed_at"], name="commerce_ordertype_placed_idx"
            ),
        ),
        migrations.AddIndex(
            model_name="order",
            index=models.Index(fields=["-created_at"], name="commerce_order_created_idx"),
        ),
    ]
