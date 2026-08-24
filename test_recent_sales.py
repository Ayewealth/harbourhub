from apps.commerce.models import OrderItem, Order
from apps.listings.serializers import PublicRecentSaleSerializer
from django.test import RequestFactory
import traceback

if __name__ == '__main__':
    import os
    import django
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'hb.settings')
    django.setup()

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
