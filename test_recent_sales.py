from apps.commerce.models import OrderItem, Order
from apps.listings.serializers import PublicRecentSaleSerializer
from django.test import RequestFactory
import traceback

item = OrderItem.objects.first()
if item:
    item.order.store = None
    item.order.save()
    request = RequestFactory().get("/listings/recent-sales/")
    serializer = PublicRecentSaleSerializer(item, context={"request": request})
    try:
        print(serializer.data)
        print("SUCCESS")
    except Exception as e:
        traceback.print_exc()
        print("ERROR:", e)
else:
    print("NO ITEMS")
