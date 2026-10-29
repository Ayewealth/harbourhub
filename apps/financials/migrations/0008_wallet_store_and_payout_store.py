import django.db.models.deletion
from django.db import migrations, models


def backfill_wallets(apps, schema_editor):
    """Attach every wallet to its owner's store and create missing ones."""
    Store = apps.get_model("store", "Store")
    VendorWallet = apps.get_model("financials", "VendorWallet")

    unresolved = []

    # A legacy wallet created with ``user`` only is attached to that user's
    # store (a user owns at most one store).
    for wallet in VendorWallet.objects.filter(store__isnull=True).iterator():
        store = Store.objects.filter(user_id=wallet.user_id).first()
        if store is None:
            unresolved.append(f"wallet {wallet.pk} has no store for its user")
            continue
        wallet.store_id = store.pk
        wallet.save(update_fields=["store"])

    # Every store must own exactly one wallet.
    for store in Store.objects.all().iterator():
        if VendorWallet.objects.filter(store_id=store.pk).exists():
            continue
        if VendorWallet.objects.filter(user_id=store.user_id).exists():
            unresolved.append(
                f"store {store.pk} user {store.user_id} already has a wallet "
                "on another store"
            )
            continue
        VendorWallet.objects.create(
            store_id=store.pk,
            user_id=store.user_id,
            currency="NGN",
        )

    if unresolved:
        raise RuntimeError(
            "Cannot make VendorWallet.store non-null; unresolved rows: "
            + "; ".join(unresolved)
        )


def backfill_payouts(apps, schema_editor):
    """Every payout belongs to the vendor's store."""
    Payout = apps.get_model("financials", "Payout")
    Store = apps.get_model("store", "Store")

    unresolved = []
    for payout in Payout.objects.filter(store__isnull=True).iterator():
        store = Store.objects.filter(user_id=payout.vendor_id).first()
        if store is None:
            unresolved.append(f"payout {payout.pk} has no store")
            continue
        payout.store_id = store.pk
        payout.save(update_fields=["store"])

    if unresolved:
        raise RuntimeError(
            "Cannot make Payout.store non-null; unresolved rows: "
            + "; ".join(unresolved)
        )


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("financials", "0007_earning_tranches"),
        ("store", "0006_remove_store_user_role_limit"),
    ]

    operations = [
        migrations.RunPython(backfill_wallets, noop),
        migrations.AlterField(
            model_name="vendorwallet",
            name="store",
            field=models.OneToOneField(
                on_delete=django.db.models.deletion.CASCADE,
                related_name="wallet",
                to="store.store",
            ),
        ),
        migrations.RunPython(backfill_payouts, noop),
        migrations.AlterField(
            model_name="payout",
            name="store",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.PROTECT,
                related_name="payouts",
                to="store.store",
            ),
        ),
    ]
