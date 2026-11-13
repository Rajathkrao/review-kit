from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

from orders.coupons import AlreadyRedeemed, CouponExhausted, CouponNotFound, discount_for, redeem
from orders.models import Coupon, Order


class CouponTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.alice = User.objects.create_user("alice")
        self.bob = User.objects.create_user("bob")
        self.coupon = Coupon.objects.create(code="LAUNCH20", percent_off=20,
                                            valid_until=timezone.localdate() + timedelta(days=7))

    def order(self, user, subtotal="50.00"):
        return Order.objects.create(user=user, subtotal=Decimal(subtotal), total=Decimal(subtotal))

    def test_discount_rounds_half_up(self):
        self.assertEqual(discount_for(self.coupon, Decimal("0.125")), Decimal("0.03"))

    def test_unknown_code(self):
        with self.assertRaises(CouponNotFound):
            redeem(self.order(self.alice), "NOPE")

    def test_redeem(self):
        order = redeem(self.order(self.alice), " launch20 ")
        self.assertEqual(order.discount, Decimal("10.00"))
        self.assertEqual(order.total, Decimal("40.00"))

    def test_one_per_customer(self):
        redeem(self.order(self.alice), "LAUNCH20")
        with self.assertRaises(AlreadyRedeemed):
            redeem(self.order(self.alice), "LAUNCH20")

    def test_max_uses(self):
        self.coupon.max_uses = 1
        self.coupon.save()
        redeem(self.order(self.alice), "LAUNCH20")
        with self.assertRaises(CouponExhausted):
            redeem(self.order(self.bob), "LAUNCH20")
