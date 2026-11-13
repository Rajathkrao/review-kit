from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase

from orders.models import Order
from orders.services import recalc


class RecalcTests(TestCase):
    def test_total(self):
        user = get_user_model().objects.create_user("u")
        order = Order.objects.create(user=user, subtotal=Decimal("10.00"), discount=Decimal("2.50"))
        self.assertEqual(recalc(order).total, Decimal("7.50"))
