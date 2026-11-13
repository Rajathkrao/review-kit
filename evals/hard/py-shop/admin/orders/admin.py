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

    def get_readonly_fields(self, request, obj=None):
        # Changing the code or percentage of a coupon that customers already used rewrites history.
        if obj is not None and obj.order_set.exists():
            return ("code", "percent_off")
        return ()

    @admin.action(description="Deactivate selected coupons", permissions=["change"])
    def deactivate(self, request, queryset):
        n = queryset.filter(active=True).update(active=False)
        self.message_user(request, f"Deactivated {n} coupon(s).", messages.SUCCESS)


@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):
    list_display = ("id", "user", "status", "subtotal", "discount", "total", "coupon", "created")
    list_filter = ("status",)
    list_select_related = ("user", "coupon")
    search_fields = ("user__username", "coupon__code")
    readonly_fields = ("subtotal", "discount", "total", "coupon", "created")
    date_hierarchy = "created"

