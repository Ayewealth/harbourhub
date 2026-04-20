# apps/core/urls.py
from django.urls import path
from .views import GlobalSearchView, UserSearchHistoryView

urlpatterns = [
    path("", GlobalSearchView.as_view(), name="global-search"),
    path("history/", UserSearchHistoryView.as_view(), name="search-history"),
]
