import uuid
from decimal import Decimal

from django.db import transaction
from django.db.models import Q, Sum
from django.utils import timezone
from django.shortcuts import get_object_or_404
from dateutil.relativedelta import relativedelta
from django_filters.rest_framework import DjangoFilterBackend
from drf_spectacular.utils import extend_schema, extend_schema_view
from rest_framework import generics, permissions, status, filters
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.financials.tasks import process_payout_task

from .serializers import (
    BankAccountSerializer,
    VendorEarningSerializer,
    PayoutSerializer,
    PayoutCreateSerializer,
    EarningsSummarySerializer,
    VendorWalletSerializer,
    WalletTransactionSerializer,
)
from .models import BankAccount, VendorEarning, Payout, VendorWallet, WalletTransaction


class BankAccountListCreateView(generics.ListCreateAPIView):
    serializer_class = BankAccountSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        return BankAccount.objects.filter(user=self.request.user)

    def perform_create(self, serializer):
        serializer.save(user=self.request.user)


class BankAccountDetailView(generics.RetrieveUpdateDestroyAPIView):
    serializer_class = BankAccountSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        return BankAccount.objects.filter(user=self.request.user)


class BankAccountSetDefaultView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request, pk):
        account = get_object_or_404(
            BankAccount, pk=pk, user=request.user)
        BankAccount.objects.filter(
            user=request.user, is_default=True
        ).exclude(pk=pk).update(is_default=False)
        account.is_default = True
        account.save(update_fields=['is_default'])
        return Response({'message': 'Default bank account updated.'})


class EarningsListView(generics.ListAPIView):
    serializer_class = VendorEarningSerializer
    permission_classes = [permissions.IsAuthenticated]
    filter_backends = [DjangoFilterBackend, filters.OrderingFilter]
    filterset_fields = ['status', 'earning_type']
    ordering_fields = ['created_at', 'net_amount']
    ordering = ['-created_at']

    def get_queryset(self):
        return VendorEarning.objects.filter(
            vendor=self.request.user
        ).select_related('order', 'listing', 'listing__category')


class EarningsSummaryView(APIView):
    """Returns earnings metrics from the VendorWallet."""
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        from .models import VendorWallet
        wallet, _ = VendorWallet.objects.get_or_create(
            user=request.user,
            defaults={'currency': 'NGN'}
        )

        # For % change, we still need to query earnings records
        now = timezone.now()
        start_of_this_month = now.replace(
            day=1, hour=0, minute=0, second=0, microsecond=0)
        start_of_last_month = start_of_this_month - relativedelta(months=1)

        qs = VendorEarning.objects.filter(vendor=request.user)

        this_month = qs.filter(
            created_at__gte=start_of_this_month
        ).aggregate(t=Sum('net_amount'))['t'] or Decimal('0')

        last_month = qs.filter(
            created_at__gte=start_of_last_month,
            created_at__lt=start_of_this_month
        ).aggregate(t=Sum('net_amount'))['t'] or Decimal('0')

        def pct_change(current, previous):
            if previous == 0:
                return 100.0 if current > 0 else 0.0
            return round(float((current - previous) / previous * 100), 1)

        return Response({
            'total_revenue': wallet.available_balance + wallet.total_withdrawn,
            'pending_balance': wallet.pending_balance,
            'available_balance': wallet.available_balance,
            'total_withdrawn': wallet.total_withdrawn,
            'revenue_change_percent': pct_change(this_month, last_month),
            'currency': wallet.currency,
        })


class PayoutListCreateView(generics.ListCreateAPIView):
    permission_classes = [permissions.IsAuthenticated]
    filter_backends = [DjangoFilterBackend]
    filterset_fields = ['status']

    def get_serializer_class(self):
        if self.request.method == 'POST':
            return PayoutCreateSerializer
        return PayoutSerializer

    def get_queryset(self):
        return Payout.objects.filter(
            vendor=self.request.user
        ).select_related('bank_account')

    def perform_create(self, serializer):
        from .models import VendorWallet, WalletTransaction
        user = self.request.user

        with transaction.atomic():
            wallet = VendorWallet.objects.select_for_update().get(user=user)

            payout_amount = Decimal(self.request.data.get('amount', 0))
            if wallet.available_balance < payout_amount:
                raise Exception("Insufficient wallet balance for this payout.")

            payout = serializer.save(
                vendor=user,
                reference=f"PAY-{uuid.uuid4().hex[:12].upper()}"
            )

            # Deduct from wallet
            wallet.available_balance -= payout.amount
            wallet.save(update_fields=['available_balance'])

            # Log transaction
            WalletTransaction.objects.create(
                wallet=wallet,
                transaction_type=WalletTransaction.Type.PAYOUT,
                amount=-payout.amount,
                description=f"Payout request {payout.reference}",
                reference_id=str(payout.id)
            )

        # Trigger async transfer
        process_payout_task.delay(payout.id)


class BankListView(APIView):
    """Fetch supported banks from Paystack."""
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        from apps.commerce.paystack import list_banks
        banks = list_banks()
        return Response(banks)


class ResolveAccountView(APIView):
    """Verify a bank account number."""
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        from apps.commerce.paystack import resolve_account
        account_number = request.query_params.get('account_number')
        bank_code = request.query_params.get('bank_code')

        if not account_number or not bank_code:
            return Response(
                {'error': 'account_number and bank_code are required'},
                status=400
            )

        data = resolve_account(account_number, bank_code)
        if data:
            return Response(data)
        return Response(
            {'error': 'Could not resolve account'},
            status=400
        )


class VendorWalletView(generics.RetrieveAPIView):
    """Retrieve current vendor wallet balance and recent transactions."""
    serializer_class = VendorWalletSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_object(self):
        wallet, _ = VendorWallet.objects.get_or_create(
            user=self.request.user,
            defaults={'currency': 'NGN'}
        )
        return wallet


class WalletTransactionListView(generics.ListAPIView):
    """List all wallet transactions for the vendor."""
    serializer_class = WalletTransactionSerializer
    permission_classes = [permissions.IsAuthenticated]
    filter_backends = [DjangoFilterBackend, filters.OrderingFilter]
    filterset_fields = ['transaction_type']
    ordering_fields = ['created_at', 'amount']
    ordering = ['-created_at']

    def get_queryset(self):
        wallet, _ = VendorWallet.objects.get_or_create(user=self.request.user)
        return wallet.transactions.all()

