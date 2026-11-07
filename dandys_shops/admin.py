from django.contrib import admin

from .models import Shop, ShopBallPrice, ShopCycleState, ShopEvent


class ShopBallPriceInline(admin.TabularInline):
    model = ShopBallPrice
    extra = 1
    autocomplete_fields = ("ball",)
    fields = ("ball", "price", "available")


@admin.register(Shop)
class ShopAdmin(admin.ModelAdmin):
    list_display = ("name", "key", "regime_name", "enabled", "slots", "is_holiday")
    list_filter = ("enabled", "is_holiday", "regime_name")
    search_fields = ("name", "key", "regime_name")
    inlines = (ShopBallPriceInline,)
    fieldsets = (
        ("Shop", {"fields": ("name", "key", "regime_name", "enabled", "welcome_message", "slots")}),
        ("Holiday schedule", {"fields": (
            "is_holiday", "start_month", "start_day", "end_month", "end_day", "fallback_priority"
        )}),
    )


@admin.register(ShopBallPrice)
class ShopBallPriceAdmin(admin.ModelAdmin):
    list_display = ("shop", "ball", "price", "available")
    list_filter = ("shop", "available", "ball__regime")
    search_fields = ("ball__country", "shop__name")
    autocomplete_fields = ("shop", "ball")


@admin.register(ShopEvent)
class ShopEventAdmin(admin.ModelAdmin):
    list_display = ("key", "enabled", "button_label", "description")
    list_editable = ("enabled", "button_label", "description")


@admin.register(ShopCycleState)
class ShopCycleStateAdmin(admin.ModelAdmin):
    list_display = ("id", "next_kind")
    readonly_fields = ("id",)
