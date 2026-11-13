from decimal import Decimal

from django.conf import settings
from django.db import models


class Coupon(models.Model):
    code = models.CharField(max_length=32, unique=True)
    description = models.CharField(max_length=200, blank=True)
    percent_off = models.PositiveSmallIntegerField()
    min_subtotal = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal("0"))
    valid_until = models.DateField()
    active = models.BooleanField(default=True)
    max_uses = models.PositiveIntegerField(null=True, blank=True, help_text="Empty = unlimited")

    def __str__(self):
        return self.code


class Order(models.Model):
    class Status(models.TextChoices):
        CART = "cart"
        PLACED = "placed"
        PAID = "paid"

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="orders")
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.CART)
    subtotal = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal("0"))
    discount = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal("0"))
    total = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal("0"))
    coupon = models.ForeignKey(Coupon, null=True, blank=True, on_delete=models.SET_NULL)
    created = models.DateTimeField(auto_now_add=True)


class CouponRedemption(models.Model):
    coupon = models.ForeignKey(Coupon, on_delete=models.PROTECT, related_name="redemptions")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    order = models.OneToOneField(Order, on_delete=models.CASCADE, related_name="redemption")
    created = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["coupon", "user"], name="one_redemption_per_user")]
