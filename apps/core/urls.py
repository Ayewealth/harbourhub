# apps/core/urls.py
from django.urls import path
from .views import GlobalSearchView, UserSearchHistoryView, FeedbackView

urlpatterns = [
    path("", GlobalSearchView.as_view(), name="global-search"),
    path("history/", UserSearchHistoryView.as_view(), name="search-history"),
    path("feedback/", FeedbackView.as_view(), name="page-feedback"),
]
