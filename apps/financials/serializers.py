from rest_framework import serializers
from .models import BankAccount, VendorEarning, Payout, VendorWallet, WalletTransaction


class BankAccountSerializer(serializers.ModelSerializer):
    class Meta:
        model = BankAccount
        fields = (
            'id', 'account_name', 'account_number',
            'bank_name', 'bank_code', 'is_default',
            'is_verified', 'created_at',
        )
        read_only_fields = ('id', 'is_verified', 'created_at')

    def validate_account_number(self, value):
        if not value.isdigit():
            raise serializers.ValidationError(
                "Account number must contain only digits.")
        if len(value) != 10:
            raise serializers.ValidationError(
                "Account number must be 10 digits.")
        return value


class BankAccountSetDefaultSerializer(serializers.Serializer):
    pass  # no body needed


class VendorEarningSerializer(serializers.ModelSerializer):
    listing_title = serializers.CharField(
        source='listing.title', read_only=True)
    listing_thumbnail = serializers.SerializerMethodField()
    listing_category = serializers.CharField(
        source='listing.category.name', read_only=True)
    order_number = serializers.CharField(
        source='order.order_number', read_only=True)

    class Meta:
        model = VendorEarning
        fields = (
            'id', 'order', 'order_number', 'listing',
            'listing_title', 'listing_thumbnail', 'listing_category',
            'earning_type', 'gross_amount', 'commission_rate',
            'commission_amount', 'net_amount', 'currency',
            'status', 'available_at', 'created_at',
        )
        read_only_fields = fields

    def get_listing_thumbnail(self, obj):
        if obj.listing:
            primary = obj.listing.images.filter(is_primary=True).first()
            if primary:
                request = self.context.get('request')
                return request.build_absolute_uri(
                    primary.image.url) if request else primary.image.url
        return None


class PayoutSerializer(serializers.ModelSerializer):
    bank_account_details = BankAccountSerializer(
        source='bank_account', read_only=True)
    destination = serializers.CharField(
        source='bank_account.bank_name', read_only=True)
    account_number = serializers.CharField(
        source='bank_account.account_number', read_only=True)

    class Meta:
        model = Payout
        fields = (
            'id', 'amount', 'currency', 'status',
            'bank_account', 'bank_account_details',
            'destination', 'account_number',
            'reference', 'failure_reason', 'receipt_url',
            'processed_at', 'created_at',
        )
        read_only_fields = (
            'id', 'status', 'reference', 'failure_reason',
            'receipt_url', 'processed_at', 'created_at',
        )


class PayoutCreateSerializer(serializers.ModelSerializer):
    class Meta:
        model = Payout
        fields = ('amount', 'bank_account')

    def validate_bank_account(self, value):
        user = self.context['request'].user
        if value.user != user:
            raise serializers.ValidationError(
                "Bank account does not belong to you.")
        return value

    def validate_amount(self, value):
        if value <= 0:
            raise serializers.ValidationError(
                "Amount must be greater than zero.")
        return value

    def validate(self, attrs):
        user = self.context['request'].user
        # Check wallet available balance
        try:
            wallet = VendorWallet.objects.get(user=user)
        except VendorWallet.DoesNotExist:
            raise serializers.ValidationError("Wallet not found.")

        if attrs['amount'] > wallet.available_balance:
            raise serializers.ValidationError(
                f"Insufficient balance. Available: {wallet.available_balance}")
        return attrs


class EarningsSummarySerializer(serializers.Serializer):
    total_revenue = serializers.DecimalField(max_digits=14, decimal_places=2)
    pending_balance = serializers.DecimalField(
        max_digits=14, decimal_places=2)
    available_balance = serializers.DecimalField(
        max_digits=14, decimal_places=2)
    total_paid_out = serializers.DecimalField(
        max_digits=14, decimal_places=2)
    revenue_change_percent = serializers.FloatField()
    pending_change_percent = serializers.FloatField()
    currency = serializers.CharField()


class WalletTransactionSerializer(serializers.ModelSerializer):
    transaction_type_display = serializers.CharField(
        source='get_transaction_type_display', read_only=True)

    class Meta:
        model = WalletTransaction
        fields = (
            'id', 'transaction_type', 'transaction_type_display',
            'amount', 'description', 'reference_id', 'created_at'
        )


class VendorWalletSerializer(serializers.ModelSerializer):
    transactions = WalletTransactionSerializer(many=True, read_only=True)

    class Meta:
        model = VendorWallet
        fields = (
            'id', 'pending_balance', 'available_balance',
            'total_withdrawn', 'currency', 'updated_at',
            'transactions'
        )
