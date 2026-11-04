from django.apps import AppConfig


class RoyaleConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "royale_package"
    label = "royale"
    verbose_name = "Royale"
    dpy_package = "royale_package.cog"
