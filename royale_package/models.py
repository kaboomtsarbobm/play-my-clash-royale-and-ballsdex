from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models

from bd_models.models import Ball, Player


class RoyaleCard(models.Model):
    ball = models.OneToOneField(Ball, on_delete=models.CASCADE, related_name="royale_card")
    enabled = models.BooleanField(default=True)
    elixir_cost = models.PositiveSmallIntegerField(
        default=4, validators=[MinValueValidator(1), MaxValueValidator(10)]
    )
    cooldown_seconds = models.PositiveIntegerField(default=12)
    attack = models.PositiveIntegerField(null=True, blank=True, help_text="Leave empty to use the ball's attack")
    health = models.PositiveIntegerField(null=True, blank=True, help_text="Leave empty to use the ball's health")

    def __str__(self):
        return f"{self.ball.country} ({self.elixir_cost} elixir, {self.cooldown_seconds}s cooldown)"


class RoyalePlayer(models.Model):
    player = models.OneToOneField(Player, on_delete=models.CASCADE, related_name="royale")
    wins = models.PositiveIntegerField(default=0)
    losses = models.PositiveIntegerField(default=0)
    draws = models.PositiveIntegerField(default=0)
    chests_opened = models.PositiveIntegerField(default=0)
    next_chest_at = models.DateTimeField(null=True, blank=True)
    deck = models.JSONField(default=list, blank=True)

    def __str__(self):
        return f"{self.player} ({self.wins} wins)"
