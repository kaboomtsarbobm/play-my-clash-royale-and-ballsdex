from django.contrib import admin

from .models import RoyaleCard


@admin.register(RoyaleCard)
class RoyaleCardAdmin(admin.ModelAdmin):
    list_display = ("ball", "enabled", "elixir_cost", "cooldown_seconds", "attack", "health")
    list_filter = ("enabled",)
    search_fields = ("ball__country",)
    autocomplete_fields = ("ball",)
