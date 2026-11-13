from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, render

from .models import Order


@login_required
def cart(request, order_id):
    order = get_object_or_404(Order, pk=order_id, user=request.user, status=Order.Status.CART)
    return render(request, "orders/cart.html", {"order": order})
