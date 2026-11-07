# Initial database schema for Dandy's Shops.
from django.core.validators import MinValueValidator
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    initial = True

    dependencies = [
        ("bd_models", "__first__"),
    ]

    operations = [
        migrations.CreateModel(
            name="Shop",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("key", models.SlugField(help_text="Unique internal key, e.g. dandys or bobettes.", max_length=40, unique=True)),
                ("name", models.CharField(max_length=80)),
                ("regime_name", models.CharField(help_text="Only balls whose regime name matches this exactly (case-insensitive) are eligible.", max_length=64)),
                ("enabled", models.BooleanField(default=True)),
                ("welcome_message", models.TextField(default="Welcome! Choose an item below to purchase.")),
                ("slots", models.PositiveSmallIntegerField(default=3, validators=[MinValueValidator(1)])),
                ("is_holiday", models.BooleanField(default=False)),
                ("start_month", models.PositiveSmallIntegerField(blank=True, null=True)),
                ("start_day", models.PositiveSmallIntegerField(blank=True, null=True)),
                ("end_month", models.PositiveSmallIntegerField(blank=True, null=True)),
                ("end_day", models.PositiveSmallIntegerField(blank=True, null=True)),
                ("fallback_priority", models.PositiveSmallIntegerField(default=100)),
            ],
            options={"db_table": "dandys_shop", "ordering": ("fallback_priority", "name")},
        ),
        migrations.CreateModel(
            name="ShopEvent",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("key", models.CharField(choices=[("discount", "Discount (10% off)"), ("extra_stock", "Extra Stock (4 slots)"), ("special_shop", "Special Shop (Dyles Store)")], max_length=32, unique=True)),
                ("enabled", models.BooleanField(default=True)),
                ("button_label", models.CharField(blank=True, max_length=80)),
                ("description", models.CharField(blank=True, max_length=200)),
            ],
            options={"db_table": "dandys_shop_event", "ordering": ("key",)},
        ),
        migrations.CreateModel(
            name="ShopCycleState",
            fields=[
                ("id", models.PositiveSmallIntegerField(default=1, editable=False, primary_key=True, serialize=False)),
                ("next_kind", models.CharField(choices=[("event", "Event"), ("shop", "Dandy's Store")], default="event", max_length=16)),
            ],
            options={"db_table": "dandys_shop_cycle_state"},
        ),
        migrations.CreateModel(
            name="ShopBallPrice",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("price", models.PositiveBigIntegerField(default=100, validators=[MinValueValidator(0)])),
                ("available", models.BooleanField(default=True)),
                ("ball", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="dandys_shop_prices", to="bd_models.ball")),
                ("shop", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="ball_prices", to="dandys_shops.shop")),
            ],
            options={"db_table": "dandys_shop_ball_price", "ordering": ("ball__country",)},
        ),
        migrations.AddConstraint(
            model_name="shopballprice",
            constraint=models.UniqueConstraint(fields=("shop", "ball"), name="dandys_unique_shop_ball_price"),
        ),
    ]
