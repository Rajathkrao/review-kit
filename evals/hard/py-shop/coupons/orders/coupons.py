"""Coupon redemption (docs/coupons.md)."""
from django.db import IntegrityError, transaction
from django.utils import timezone

from .models import Coupon, CouponRedemption, Order
from .money import q


class CouponError(Exception):
    message = "This coupon can't be used."


class CouponNotFound(CouponError):
    message = "Unknown coupon code."


class CouponExpired(CouponError):
    message = "This coupon has expired."


class CouponExhausted(CouponError):
    message = "This coupon has been fully redeemed."


class BelowMinimum(CouponError):
    message = "Your cart is below this coupon's minimum."


class AlreadyRedeemed(CouponError):
    message = "You have already used this coupon."


def discount_for(coupon: Coupon, subtotal):
    return q(subtotal * coupon.percent_off / 100)


def redeem(order: Order, code: str) -> Order:
    try:
        coupon = Coupon.objects.get(code__iexact=code.strip(), active=True)
    except Coupon.DoesNotExist:
        raise CouponNotFound() from None
    if coupon.valid_until < timezone.now().date():
        raise CouponExpired()
    if coupon.max_uses is not None and coupon.redemptions.count() >= coupon.max_uses:
        raise CouponExhausted()
    discount = discount_for(coupon, order.subtotal)
    if order.subtotal - discount < coupon.min_subtotal:
        raise BelowMinimum()
    try:
        with transaction.atomic():
            CouponRedemption.objects.create(coupon=coupon, user=order.user, order=order)
            order.coupon = coupon
            order.discount = discount
            order.total = q(order.subtotal - discount)
            order.save(update_fields=["coupon", "discount", "total"])
    except IntegrityError:
        raise AlreadyRedeemed() from None
    return order
