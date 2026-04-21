from django.urls import path
from .views import (
    NotificationListView,
    NotificationCountView,
    NotificationMarkReadView,
    NotificationMarkAllReadView,
    NotificationDeleteView,
    NotificationClearAllView,
)

urlpatterns = [
    path('', NotificationListView.as_view(), name='notification-list'),
    path('count/', NotificationCountView.as_view(),
         name='notification-count'),
    path('<int:pk>/read/', NotificationMarkReadView.as_view(),
         name='notification-mark-read'),
    path('read-all/', NotificationMarkAllReadView.as_view(),
         name='notification-mark-all-read'),
    path('<int:pk>/', NotificationDeleteView.as_view(),
         name='notification-delete'),
    path('clear/', NotificationClearAllView.as_view(),
         name='notification-clear-all'),
]
