from django.urls import path
from .views import (
    SupportTicketListCreateView,
    SupportTicketDetailView,
    MarkTicketResolvedView,
    SupportTicketSummaryView,
)

urlpatterns = [
    path('', SupportTicketListCreateView.as_view(),
         name='ticket-list-create'),
    path('summary/', SupportTicketSummaryView.as_view(),
         name='ticket-summary'),
    path('<int:pk>/', SupportTicketDetailView.as_view(),
         name='ticket-detail'),
    path('<int:pk>/resolve/', MarkTicketResolvedView.as_view(),
         name='ticket-resolve'),
]
