from django.contrib import admin, messages
from django.db.models import Count

from .models import Coupon, Order


@admin.register(Coupon)
class CouponAdmin(admin.ModelAdmin):
    list_display = ("code", "percent_off", "min_subtotal", "valid_until", "active", "orders_count")
    list_filter = ("active", "valid_until")
    search_fields = ("code", "description")
    ordering = ("-valid_until", "code")
    actions = ("deactivate",)

    def get_queryset(self, request):
        return super().get_queryset(request).annotate(_orders=Count("order"))

    @admin.display(ordering="_orders", description="Orders")
    def orders_count(self, obj):
        return obj._orders

    def has_delete_permission(self, request, obj=None):
        # Order.coupon is SET_NULL: deleting a used coupon would erase it from past orders.
        # Used coupons are deactivated instead.
        if obj is not None and obj.order_set.exists():
            return False
        return super().has_delete_permission(request, obj)

    def get_actions(self, request):
        actions = super().get_actions(request)
        actions.pop("delete_selected", None)
        return actions

    def get_readonly_fields(self, request, obj=None):
        # Changing the code or percentage of a coupon that customers already used rewrites history.
        if obj is not None and obj.order_set.exists():
            return ("code", "percent_off")
        return ()

    @admin.action(description="Deactivate selected coupons", permissions=["change"])
    def deactivate(self, request, queryset):
        # order_by(): update() refuses a queryset sorted by the Orders count annotation.
        n = queryset.filter(active=True).order_by().update(active=False)
        self.message_user(request, f"Deactivated {n} coupon(s).", messages.SUCCESS)


@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):
    list_display = ("id", "user", "status", "subtotal", "discount", "total", "coupon", "created")
    list_filter = ("status",)
    list_select_related = ("user", "coupon")
    search_fields = ("user__username", "coupon__code")
    readonly_fields = ("subtotal", "discount", "total", "coupon", "created")
    date_hierarchy = "created"

