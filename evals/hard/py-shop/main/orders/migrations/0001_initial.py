from decimal import Decimal

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    initial = True
    dependencies = [migrations.swappable_dependency(settings.AUTH_USER_MODEL)]

    operations = [
        migrations.CreateModel(
            name="Coupon",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("code", models.CharField(max_length=32, unique=True)),
                ("description", models.CharField(blank=True, max_length=200)),
                ("percent_off", models.PositiveSmallIntegerField()),
                ("min_subtotal", models.DecimalField(decimal_places=2, default=Decimal("0"), max_digits=10)),
                ("valid_until", models.DateField()),
                ("active", models.BooleanField(default=True)),
            ],
        ),
        migrations.CreateModel(
            name="Order",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("status", models.CharField(choices=[("cart", "Cart"), ("placed", "Placed"), ("paid", "Paid")], default="cart", max_length=10)),
                ("subtotal", models.DecimalField(decimal_places=2, default=Decimal("0"), max_digits=10)),
                ("discount", models.DecimalField(decimal_places=2, default=Decimal("0"), max_digits=10)),
                ("total", models.DecimalField(decimal_places=2, default=Decimal("0"), max_digits=10)),
                ("created", models.DateTimeField(auto_now_add=True)),
                ("coupon", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, to="orders.coupon")),
                ("user", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="orders", to=settings.AUTH_USER_MODEL)),
            ],
        ),
    ]
