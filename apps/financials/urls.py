from django.urls import path
from .views import (
    BankAccountListCreateView,
    BankAccountDetailView,
    BankAccountSetDefaultView,
    EarningsListView,
    EarningsSummaryView,
    PayoutListCreateView,
    BankListView,
    ResolveAccountView,
    VendorWalletView,
    WalletTransactionListView,
)

urlpatterns = [
    # Bank accounts
    path('bank-accounts/', BankAccountListCreateView.as_view(),
         name='bank-account-list-create'),
    path('bank-accounts/<int:pk>/', BankAccountDetailView.as_view(),
         name='bank-account-detail'),
    path('bank-accounts/<int:pk>/set-default/',
         BankAccountSetDefaultView.as_view(),
         name='bank-account-set-default'),
    path('banks/', BankListView.as_view(), name='bank-list'),
    path('banks/resolve/', ResolveAccountView.as_view(),
         name='bank-resolve'),

    # Earnings
    path('earnings/', EarningsListView.as_view(), name='earnings-list'),
    path('earnings/summary/', EarningsSummaryView.as_view(),
         name='earnings-summary'),

    # Payouts
    path('payouts/', PayoutListCreateView.as_view(), name='payout-list-create'),

    # Wallet
    path('wallet/', VendorWalletView.as_view(), name='wallet-detail'),
    path('wallet/transactions/', WalletTransactionListView.as_view(), name='wallet-transactions'),
]
