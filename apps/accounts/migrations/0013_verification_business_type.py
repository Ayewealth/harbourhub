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
    for row in VerificationRequest.objects.all().iterator():
        marker = (row.additional_info or "").strip()
        if marker in BUSINESS_TYPES:
            row.business_type = marker
            row.additional_info = ""
            row.save(update_fields=["business_type", "additional_info"])


def backwards(apps, schema_editor):
    # The business type is now a first-class column; leave it in place.
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0012_verification_document_fields"),
    ]

    operations = [
        migrations.RunPython(forwards, backwards),
    ]
