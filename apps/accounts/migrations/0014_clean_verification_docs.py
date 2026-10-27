from django.db import migrations

BUSINESS_TYPES = {
    "sole_proprietorship",
    "partnership",
    "limited_liability",
    "corporation",
    "ngo",
}


def forwards(apps, schema_editor):
    VerificationRequest = apps.get_model("accounts", "VerificationRequest")
    fields = ("business_license", "government_id", "insurance_certificate")
    for row in VerificationRequest.objects.all().iterator():
        changed = []
        for field in fields:
            value = getattr(row, field).name if getattr(row, field) else ""
            if value in BUSINESS_TYPES:
                setattr(row, field, "")
                changed.append(field)
        if changed:
            row.save(update_fields=changed)


def backwards(apps, schema_editor):
    # The removed values were never real document paths; do not restore them.
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0013_verification_business_type"),
    ]

    operations = [
        migrations.RunPython(forwards, backwards),
    ]
