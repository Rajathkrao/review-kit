from datetime import date
from decimal import Decimal

from django.contrib.admin.sites import site
from django.contrib.auth import get_user_model
from django.test import RequestFactory, TestCase

from orders.admin import CouponAdmin
from orders.models import Coupon, Order


class CouponAdminTests(TestCase):
    def setUp(self):
        self.admin_user = get_user_model().objects.create_superuser("admin", "a@example.com", "pw")
        self.c1 = Coupon.objects.create(code="A", percent_off=10, valid_until=date(2030, 1, 1))
        self.c2 = Coupon.objects.create(code="B", percent_off=10, valid_until=date(2030, 1, 1), active=False)
        self.ma = CouponAdmin(Coupon, site)
        self.rf = RequestFactory()

    def request(self):
        r = self.rf.get("/")
        r.user = self.admin_user
        sent = self.sent = []
        r._messages = type("M", (), {"add": lambda self, level, msg, extra_tags="": sent.append(msg)})()
        return r

    def test_deactivate_counts_only_active(self):
        self.ma.deactivate(self.request(), Coupon.objects.all())
        self.assertFalse(Coupon.objects.get(code="A").active)
        self.assertEqual(self.sent, ["Deactivated 1 coupon(s)."])

    def test_code_readonly_once_used(self):
        self.assertEqual(self.ma.get_readonly_fields(self.request(), self.c1), ())
        Order.objects.create(user=self.admin_user, subtotal=Decimal("1"), coupon=self.c1)
        self.assertEqual(self.ma.get_readonly_fields(self.request(), self.c1), ("code", "percent_off"))

    def test_orders_count(self):
        Order.objects.create(user=self.admin_user, subtotal=Decimal("1"), coupon=self.c1)
        obj = self.ma.get_queryset(self.request()).get(pk=self.c1.pk)
        self.assertEqual(self.ma.orders_count(obj), 1)

    def test_used_coupon_cannot_be_deleted(self):
        self.assertTrue(self.ma.has_delete_permission(self.request(), self.c1))
        Order.objects.create(user=self.admin_user, subtotal=Decimal("1"), coupon=self.c1)
        self.assertFalse(self.ma.has_delete_permission(self.request(), self.c1))
        self.assertNotIn("delete_selected", self.ma.get_actions(self.request()))

    def test_deactivate_when_sorted_by_orders(self):
        self.client.force_login(self.admin_user)
        r = self.client.post("/admin/orders/coupon/?o=6", {"action": "deactivate", "_selected_action": [self.c1.pk]})
        self.assertEqual(r.status_code, 302)
        self.assertFalse(Coupon.objects.get(pk=self.c1.pk).active)

    def test_changelist_loads(self):
        self.client.force_login(self.admin_user)
        self.assertEqual(self.client.get("/admin/orders/coupon/").status_code, 200)
        self.assertEqual(self.client.get("/admin/orders/order/").status_code, 200)
