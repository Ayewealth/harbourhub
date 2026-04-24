from django.urls import path
from .views import (
    ComplianceDocumentListCreateView,
    ComplianceDocumentDetailView,
    VerifyComplianceDocumentView,
    ComplianceSummaryView,
)

urlpatterns = [
    path('', ComplianceDocumentListCreateView.as_view(),
         name='compliance-list-create'),
    path('summary/', ComplianceSummaryView.as_view(),
         name='compliance-summary'),
    path('<int:pk>/', ComplianceDocumentDetailView.as_view(),
         name='compliance-detail'),
    path('<int:pk>/verify/', VerifyComplianceDocumentView.as_view(),
         name='compliance-verify'),
]
