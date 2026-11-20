from decimal import Decimal, InvalidOperation

from drf_spectacular.utils import (
    OpenApiParameter,
    extend_schema,
    inline_serializer,
)
from rest_framework import serializers
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from .currency import (
    CURRENCY_SYMBOLS,
    SUPPORTED_CURRENCIES,
    CurrencyRateUnavailable,
    convert_money,
    get_rate_snapshot,
)


class CurrencyRatesView(APIView):
    """The rates the server converts with, and an optional conversion.

    The frontend should call this instead of holding its own rate table, so a
    displayed price and a stored price come from the same snapshot.

    ``GET /currency/rates/``
    ``GET /currency/rates/?from=NGN&to=USD&amount=100``
    """

    permission_classes = [AllowAny]
    authentication_classes = []

    @extend_schema(
        summary="Current exchange rates",
        description=(
            "USD-based rates from the same snapshot the server uses for "
            "stored money, with source and fetch time. Pass `from`, `to`, and "
            "`amount` to have the server perform the conversion."
        ),
        parameters=[
            OpenApiParameter("from", str, description="Source currency, e.g. NGN."),
            OpenApiParameter("to", str, description="Target currency, e.g. USD."),
            OpenApiParameter("amount", str, description="Amount to convert."),
        ],
        responses={
            200: inline_serializer(
                name="CurrencyRatesResponse",
                fields={
                    "base": serializers.CharField(),
                    "source": serializers.CharField(),
                    "fetched_at": serializers.CharField(allow_null=True),
                    "stale": serializers.BooleanField(),
                    "rates": serializers.DictField(
                        child=serializers.FloatField()
                    ),
                    "symbols": serializers.DictField(
                        child=serializers.CharField()
                    ),
                    "supported": serializers.ListField(
                        child=serializers.CharField()
                    ),
                    "conversion": serializers.DictField(allow_null=True),
                },
            ),
            400: inline_serializer(
                name="CurrencyRatesError",
                fields={"error": serializers.CharField()},
            ),
        },
    )
    def get(self, request):
        snapshot = get_rate_snapshot()
        payload = {
            "base": snapshot["base"],
            "source": snapshot["source"],
            "fetched_at": snapshot["fetched_at"],
            "stale": snapshot["stale"],
            "rates": snapshot["rates"],
            "symbols": CURRENCY_SYMBOLS,
            "supported": list(SUPPORTED_CURRENCIES),
            "conversion": None,
        }

        source = request.query_params.get("from")
        target = request.query_params.get("to")
        amount = request.query_params.get("amount")

        if source or target or amount:
            if not (source and target and amount is not None):
                return Response(
                    {"error": "from, to, and amount are required together."},
                    status=400,
                )
            try:
                value = Decimal(str(amount))
            except (InvalidOperation, TypeError, ValueError):
                return Response({"error": "amount must be a number."}, status=400)
            if value < 0:
                return Response(
                    {"error": "amount cannot be negative."}, status=400
                )
            try:
                converted = convert_money(value, source, target)
            except CurrencyRateUnavailable as exc:
                return Response({"error": str(exc)}, status=400)
            payload["conversion"] = {
                "from": source.upper(),
                "to": target.upper(),
                "amount": str(value),
                "result": str(converted),
            }

        response = Response(payload)
        response["Cache-Control"] = "public, max-age=60"
        return response
