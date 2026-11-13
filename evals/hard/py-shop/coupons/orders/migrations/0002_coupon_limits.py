import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("orders", "0001_initial"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(
            model_name="coupon",
            name="max_uses",
            field=models.PositiveIntegerField(default=0, help_text="Empty = unlimited"),
            preserve_default=False,
        ),
        migrations.AlterField(
            model_name="coupon",
            name="max_uses",
            field=models.PositiveIntegerField(blank=True, null=True, help_text="Empty = unlimited"),
        ),
        migrations.CreateModel(
            name="CouponRedemption",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("created", models.DateTimeField(auto_now_add=True)),
                ("coupon", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="redemptions", to="orders.coupon")),
                ("order", models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name="redemption", to="orders.order")),
                ("user", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to=settings.AUTH_USER_MODEL)),
            ],
            options={"constraints": [models.UniqueConstraint(fields=("coupon", "user"), name="one_redemption_per_user")]},
        ),
    ]
