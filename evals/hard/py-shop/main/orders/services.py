from .models import Order
from .money import q


def recalc(order: Order) -> Order:
    order.total = q(order.subtotal - order.discount)
    order.save(update_fields=["total"])
    return order
