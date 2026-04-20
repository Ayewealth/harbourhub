from django.urls import path

from .views import (
    StoreListCreateView,
    StoreRetrieveUpdateDestroyView,
    TopVendorsListView,
    StorePublishView,
    StoreUnpublishView
)

urlpatterns = [
    path("", StoreListCreateView.as_view(), name="store-list-create"),
    path("top/", TopVendorsListView.as_view(), name="store-top-vendors"),
    path("<slug:slug>/", StoreRetrieveUpdateDestroyView.as_view(), name="store-detail"),
    path("<slug:slug>/publish/", StorePublishView.as_view(), name="store-publish"),
    path("<slug:slug>/unpublish/",
         StoreUnpublishView.as_view(), name="store-unpublish"),
]
