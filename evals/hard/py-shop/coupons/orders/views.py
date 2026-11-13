from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from .coupons import CouponError, redeem
from .models import Order


@login_required
def cart(request, order_id):
    order = get_object_or_404(Order.objects.select_related("coupon"), pk=order_id,
                              user=request.user, status=Order.Status.CART)
    return render(request, "orders/cart.html", {"order": order})


@login_required
@require_POST
def apply_coupon(request, order_id):
    order = get_object_or_404(Order, pk=order_id, user=request.user, status=Order.Status.CART)
    try:
        redeem(order, request.POST.get("code", ""))
    except CouponError as exc:
        messages.error(request, exc.message)
    else:
        messages.success(request, "Coupon applied.")
    return redirect("cart", order_id=order.pk)
