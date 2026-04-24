from celery import shared_task


@shared_task
def update_compliance_statuses_task():
    """Auto-update compliance document statuses based on expiry dates."""
    from .models import ComplianceDocument
    from django.utils import timezone

    docs = ComplianceDocument.objects.filter(
        end_date__isnull=False,
        status__in=[
            ComplianceDocument.Status.ACTIVE,
            ComplianceDocument.Status.EXPIRING
        ]
    )
    for doc in docs:
        doc.update_status_by_expiry()
