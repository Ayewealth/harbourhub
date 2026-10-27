from django.db import migrations
from django.db.models import F


def forwards(apps, schema_editor):
    """Legacy earnings were considered fully released when marked available.

    Without this, every historical ``available``/``paid_out`` earning would show
    ``released_amount = 0`` and could never be allocated to a payout.
    """
    VendorEarning = apps.get_model("financials", "VendorEarning")

    VendorEarning.objects.filter(
        status__in=("available", "processing", "paid_out"),
        released_amount=0,
    ).update(released_amount=F("net_amount"))

    VendorEarning.objects.filter(
        status="paid_out",
        paid_out_amount=0,
    ).update(paid_out_amount=F("net_amount"))


def backwards(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("financials", "0005_earning_release_fields"),
    ]

    operations = [
        migrations.RunPython(forwards, backwards),
    ]
