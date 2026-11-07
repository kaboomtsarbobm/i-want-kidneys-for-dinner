from django.core.validators import MinValueValidator
from django.db import models

from bd_models.models import Ball


class Shop(models.Model):
    key = models.SlugField(max_length=40, unique=True, help_text="Unique internal key, e.g. dandys or bobettes.")
    name = models.CharField(max_length=80)
    regime_name = models.CharField(
        max_length=64,
        help_text='Only balls whose regime name matches this exactly are eligible (case-insensitive).',
    )
    enabled = models.BooleanField(default=True)
    welcome_message = models.TextField(default="Welcome! Choose an item below to purchase.")
    slots = models.PositiveSmallIntegerField(default=3, validators=[MinValueValidator(1)])
    is_holiday = models.BooleanField(default=False)
    start_month = models.PositiveSmallIntegerField(null=True, blank=True)
    start_day = models.PositiveSmallIntegerField(null=True, blank=True)
    end_month = models.PositiveSmallIntegerField(null=True, blank=True)
    end_day = models.PositiveSmallIntegerField(null=True, blank=True)
    fallback_priority = models.PositiveSmallIntegerField(default=100)

    class Meta:
        db_table = "dandys_shop"
        ordering = ("fallback_priority", "name")

    def __str__(self):
        return self.name


class ShopBallPrice(models.Model):
    shop = models.ForeignKey(Shop, on_delete=models.CASCADE, related_name="ball_prices")
    ball = models.ForeignKey(Ball, on_delete=models.CASCADE, related_name="dandys_shop_prices")
    price = models.PositiveBigIntegerField(default=100, validators=[MinValueValidator(0)])
    available = models.BooleanField(default=True)

    class Meta:
        db_table = "dandys_shop_ball_price"
        constraints = [
            models.UniqueConstraint(fields=("shop", "ball"), name="dandys_unique_shop_ball_price")
        ]
        ordering = ("ball__country",)

    def __str__(self):
        return f"{self.shop.name}: {self.ball.country} ({self.price})"


class ShopEvent(models.Model):
    class EventType(models.TextChoices):
        DISCOUNT = "discount", "Discount (10% off)"
        EXTRA_STOCK = "extra_stock", "Extra Stock (4 slots)"
        SPECIAL_SHOP = "special_shop", "Special Shop (Dyles Store)"

    key = models.CharField(max_length=32, choices=EventType.choices, unique=True)
    enabled = models.BooleanField(default=True)
    button_label = models.CharField(max_length=80, blank=True)
    description = models.CharField(max_length=200, blank=True)

    class Meta:
        db_table = "dandys_shop_event"
        ordering = ("key",)

    def __str__(self):
        return self.get_key_display()


class ShopCycleState(models.Model):
    # Single row (pk=1). The next regular-cycle spawn is either "event" or "shop".
    id = models.PositiveSmallIntegerField(primary_key=True, default=1, editable=False)
    next_kind = models.CharField(max_length=16, choices=(("event", "Event"), ("shop", "Dandy's Store")), default="event")

    class Meta:
        db_table = "dandys_shop_cycle_state"

    def __str__(self):
        return f"Next: {self.next_kind}"
