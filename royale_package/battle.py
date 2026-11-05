from __future__ import annotations

import math
from dataclasses import dataclass
from enum import Enum, IntEnum
from typing import Final, List, NamedTuple, Optional, Sequence, Tuple, Union

tick: Final[int] = 3
match_ticks: Final[int] = 60
overtime_ticks: Final[int] = 20
double_elixir_after: Final[int] = 40
start_elixir: Final[float] = 5.0
max_elixir: Final[float] = 10.0
elixir_seconds: Final[float] = 2.8
deck_size: Final[int] = 8

princess_pos: Final[Tuple[int, int]] = (13, 87)
king_pos: Final[Tuple[int, int]] = (0, 100)
spawn_pos: Final[Tuple[int, int]] = (20, 80)
princess_hp: Final[int] = 1400
king_hp: Final[int] = 2400
tower_dps: Final[int] = 60
tower_range: Final[int] = 25
aggro_range: Final[int] = 30
lane_count: Final[int] = 2
field_length: Final[int] = 100
unit_dps_factor: Final[float] = 0.12
hp_scale_target: Final[int] = 600
ranged_ratio: Final[float] = 1.3
tank_ratio: Final[float] = 0.75
min_fraction: Final[float] = 0.01
ratio_tolerance: Final[float] = 0.0001


class towerslot(IntEnum):
    left = 0
    right = 1
    king = 2


class targetkind(Enum):
    unit = "unit"
    tower = "tower"


class towerref(NamedTuple):
    side: int
    slot: int


@dataclass
class card:
    ball_id: int
    name: str
    atk: int
    hp: int
    cost: int
    cooldown: int


@dataclass
class unit:
    side: int
    lane: int
    pos: float
    hp: float
    max_hp: float
    dps: float
    reach: float
    speed: float
    name: str

    @property
    def alive(self) -> bool:
        return self.hp > 0

    def distance_to(self, position: float) -> float:
        return abs(position - self.pos)

    def clamp_position(self) -> None:
        self.pos = max(0, min(field_length, self.pos))


@dataclass(frozen=True)
class movementprofile:
    reach: float
    speed: float


ranged: Final[movementprofile] = movementprofile(reach=18, speed=3.0)
tank: Final[movementprofile] = movementprofile(reach=6, speed=2.5)
balanced: Final[movementprofile] = movementprofile(reach=9, speed=3.5)


@dataclass
class target:
    kind: targetkind
    ref: Union[unit, towerref]
    position: float


@dataclass
class hit:
    kind: targetkind
    ref: Union[unit, towerref]
    amount: float


def movement_profile(card: card) -> movementprofile:
    ratio = card.atk / max(card.hp, 1)
    if ratio > ranged_ratio:
        return ranged
    if ratio < tank_ratio:
        return tank
    return balanced


def tower_position(side_index: int, slot: int) -> int:
    if slot == towerslot.king:
        return king_pos[side_index]
    return princess_pos[side_index]


class side:
    def __init__(self, cards: Sequence[card]) -> None:
        self.cards: List[card] = list(cards)
        self.cooldowns: List[int] = [0 for _ in self.cards]
        self.elixir: float = start_elixir
        self.towers: List[float] = [princess_hp, princess_hp, king_hp]

    def tower_hp_ratio(self) -> float:
        remaining = sum(self.towers)
        maximum = princess_hp * 2 + king_hp
        return remaining / maximum

    def can_afford(self, card: card) -> bool:
        return self.elixir >= card.cost

    def start_cooldown(self, index: int) -> None:
        self.cooldowns[index] = math.ceil(self.cards[index].cooldown / tick)

    def regenerate(self, gain: float) -> None:
        self.elixir = min(max_elixir, self.elixir + gain)

    def cool_down(self) -> None:
        self.cooldowns = [max(0, remaining - 1) for remaining in self.cooldowns]


class game:
    def __init__(self, deck_a: Sequence[card], deck_b: Sequence[card]) -> None:
        self.sides: List[side] = [side(deck_a), side(deck_b)]
        self.units: List[unit] = []
        self.ticks: int = 0
        self.overtime: bool = False
        self.over: bool = False
        self.winner: Optional[int] = None

        everyone = list(deck_a) + list(deck_b)
        average_hp = sum(card.hp for card in everyone) / len(everyone)
        self.scale: float = hp_scale_target / average_hp

    @property
    def double_elixir(self) -> bool:
        return self.ticks >= double_elixir_after

    @property
    def time_limit(self) -> int:
        if self.overtime:
            return match_ticks + overtime_ticks
        return match_ticks

    def crowns(self, side: int) -> int:
        enemy = self.sides[1 - side]
        if enemy.towers[towerslot.king] <= 0:
            return 3
        return sum(1 for lane in range(lane_count) if enemy.towers[lane] <= 0)

    def seconds_left(self) -> int:
        ticks_left = max(0, self.time_limit - self.ticks)
        return ticks_left * tick

    def play(self, side: int, index: int, lane: int) -> Optional[str]:
        if self.over:
            return "the battle is over."

        player = self.sides[side]
        card = player.cards[index]

        if player.cooldowns[index] > 0:
            wait = player.cooldowns[index] * tick
            return f"{card.name} is on cooldown for {wait} more seconds."

        if not player.can_afford(card):
            return f"not enough elixir for {card.name} ({card.cost})."

        player.elixir -= card.cost
        player.start_cooldown(index)

        profile = movement_profile(card)
        unit_hp = card.hp * self.scale
        self.units.append(
            unit(
                side=side,
                lane=lane,
                pos=spawn_pos[side],
                hp=unit_hp,
                max_hp=unit_hp,
                dps=card.atk * self.scale * unit_dps_factor,
                reach=profile.reach,
                speed=profile.speed,
                name=card.name,
            )
        )
        return None

    def _closest_enemy(
        self,
        enemy_side: int,
        origin: float,
        limit: float,
        lane: Optional[int] = None,
    ) -> Optional[unit]:
        closest: Optional[unit] = None
        closest_distance: Optional[float] = None
        for candidate in self.units:
            if candidate.side != enemy_side:
                continue
            if lane is not None and candidate.lane != lane:
                continue
            distance = candidate.distance_to(origin)
            if distance > limit:
                continue
            if closest is None or distance < closest_distance:
                closest = candidate
                closest_distance = distance
        return closest

    def _pick_target(self, unit: unit) -> Optional[target]:
        enemy_side = 1 - unit.side

        enemy_unit = self._closest_enemy(enemy_side, unit.pos, aggro_range, lane=unit.lane)
        if enemy_unit is not None:
            return target(targetkind.unit, enemy_unit, enemy_unit.pos)

        enemy = self.sides[enemy_side]
        if enemy.towers[unit.lane] > 0:
            return target(
                targetkind.tower,
                towerref(enemy_side, unit.lane),
                tower_position(enemy_side, unit.lane),
            )
        if enemy.towers[towerslot.king] > 0:
            return target(
                targetkind.tower,
                towerref(enemy_side, towerslot.king),
                tower_position(enemy_side, towerslot.king),
            )
        return None

    def _collect_unit_hits(self) -> List[hit]:
        hits: List[hit] = []
        for unit in self.units:
            target = self._pick_target(unit)
            if target is None:
                continue

            distance = abs(target.position - unit.pos)
            step = unit.speed * tick
            fraction = 1.0

            if distance > unit.reach:
                move = min(step, distance - unit.reach)
                if target.position > unit.pos:
                    unit.pos += move
                else:
                    unit.pos -= move
                unit.clamp_position()

                fraction = 1 - move / step
                if fraction <= min_fraction:
                    continue

            hits.append(hit(target.kind, target.ref, unit.dps * tick * fraction))
        return hits

    def _collect_tower_hits(self) -> List[hit]:
        hits: List[hit] = []
        for side_index, side in enumerate(self.sides):
            enemy_side = 1 - side_index
            for slot, remaining in enumerate(side.towers):
                if remaining <= 0:
                    continue

                lane = None if slot == towerslot.king else slot
                origin = tower_position(side_index, slot)
                foe = self._closest_enemy(enemy_side, origin, tower_range, lane=lane)
                if foe is not None:
                    hits.append(hit(targetkind.unit, foe, tower_dps * tick))
        return hits

    def _apply(self, hit: hit) -> None:
        if hit.kind is targetkind.unit:
            hit.ref.hp -= hit.amount
            return
        towers = self.sides[hit.ref.side].towers
        towers[hit.ref.slot] = max(0, towers[hit.ref.slot] - hit.amount)

    def tick(self) -> None:
        self.ticks += 1

        gain = tick / elixir_seconds
        if self.double_elixir:
            gain *= 2

        for side in self.sides:
            side.regenerate(gain)
            side.cool_down()

        hits = self._collect_unit_hits() + self._collect_tower_hits()
        for hit in hits:
            self._apply(hit)

        self.units = [unit for unit in self.units if unit.alive]
        self._check_end()

    def _finish(self, winner: Optional[int]) -> None:
        self.winner = winner
        self.over = True

    def _check_end(self) -> None:
        for side in range(2):
            if self.sides[1 - side].towers[towerslot.king] <= 0:
                self._finish(side)
                return

        crowns_a = self.crowns(0)
        crowns_b = self.crowns(1)
        leader = 0 if crowns_a > crowns_b else 1

        if self.overtime and crowns_a != crowns_b:
            self._finish(leader)
            return

        if not self.overtime and self.ticks >= match_ticks:
            if crowns_a != crowns_b:
                self._finish(leader)
            else:
                self.overtime = True
            return

        if self.overtime and self.ticks >= match_ticks + overtime_ticks:
            ratio_a = self.sides[1].tower_hp_ratio()
            ratio_b = self.sides[0].tower_hp_ratio()
            if abs(ratio_a - ratio_b) > ratio_tolerance:
                self._finish(0 if ratio_a < ratio_b else 1)
            else:
                self._finish(None)
