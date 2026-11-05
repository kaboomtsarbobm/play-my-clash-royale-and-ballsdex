from __future__ import annotations

import math
from dataclasses import dataclass, field
from enum import Enum, IntEnum
from typing import Final, Iterable, List, NamedTuple, Optional, Sequence, Tuple, Union


@dataclass(frozen=True, slots=True)
class GameRules:
    tick_seconds: int = 3
    match_ticks: int = 60
    overtime_ticks: int = 20
    double_elixir_after: int = 40
    starting_elixir: float = 5.0
    maximum_elixir: float = 10.0
    elixir_cycle_seconds: float = 2.8
    deck_capacity: int = 8
    princess_positions: Tuple[int, int] = (13, 87)
    king_positions: Tuple[int, int] = (0, 100)
    spawn_positions: Tuple[int, int] = (20, 80)
    lanes: int = 2
    field_length: int = 100
    princess_health: int = 1400
    king_health: int = 2400
    tower_damage_per_second: int = 60
    tower_attack_range: int = 25
    unit_aggro_range: int = 30
    unit_damage_factor: float = 0.12
    target_average_health: int = 600
    ranged_attack_ratio: float = 1.3
    tank_attack_ratio: float = 0.75
    minimum_attack_fraction: float = 0.01
    health_ratio_tolerance: float = 0.0001

    @property
    def regular_time_limit(self) -> int:
        return self.match_ticks

    @property
    def overtime_time_limit(self) -> int:
        return self.match_ticks + self.overtime_ticks

    @property
    def initial_tower_health(self) -> Tuple[int, int, int]:
        return self.princess_health, self.princess_health, self.king_health

    @property
    def total_tower_health(self) -> int:
        return self.princess_health * 2 + self.king_health


RULES: Final[GameRules] = GameRules()

TICK: Final[int] = RULES.tick_seconds
DECK_SIZE: Final[int] = RULES.deck_capacity


tick = TICK
match_ticks = RULES.match_ticks
overtime_ticks = RULES.overtime_ticks
double_elixir_after = RULES.double_elixir_after
start_elixir = RULES.starting_elixir
max_elixir = RULES.maximum_elixir
elixir_seconds = RULES.elixir_cycle_seconds
deck_size = DECK_SIZE
princess_pos = RULES.princess_positions
king_pos = RULES.king_positions
spawn_pos = RULES.spawn_positions
lane_count = RULES.lanes
field_length = RULES.field_length
princess_hp = RULES.princess_health
king_hp = RULES.king_health
tower_dps = RULES.tower_damage_per_second
tower_range = RULES.tower_attack_range
aggro_range = RULES.unit_aggro_range
unit_dps_factor = RULES.unit_damage_factor
hp_scale_target = RULES.target_average_health
ranged_ratio = RULES.ranged_attack_ratio
tank_ratio = RULES.tank_attack_ratio
min_fraction = RULES.minimum_attack_fraction
ratio_tolerance = RULES.health_ratio_tolerance


class TowerSlot(IntEnum):
    LEFT = 0
    RIGHT = 1
    KING = 2


class TargetKind(Enum):
    UNIT = "unit"
    TOWER = "tower"


class TowerRef(NamedTuple):
    side: int
    slot: int


@dataclass(slots=True)
class Card:
    ball_id: int
    name: str
    atk: int
    hp: int
    cost: int
    cooldown: int

    def __post_init__(self) -> None:
        self.atk = max(0, int(self.atk))
        self.hp = max(1, int(self.hp))
        self.cost = max(0, int(self.cost))
        self.cooldown = max(0, int(self.cooldown))


@dataclass(slots=True)
class Unit:
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
        self.pos = min(float(RULES.field_length), max(0.0, self.pos))

    def move_toward(self, position: float, distance: float) -> float:
        previous = self.pos
        direction = 1.0 if position > self.pos else -1.0
        self.pos += direction * max(0.0, distance)
        self.clamp_position()
        return abs(self.pos - previous)

    def receive_damage(self, amount: float) -> None:
        self.hp = max(0.0, self.hp - max(0.0, amount))


@dataclass(frozen=True, slots=True)
class MovementProfile:
    reach: float
    speed: float


RANGED_PROFILE: Final[MovementProfile] = MovementProfile(reach=18, speed=3.0)
TANK_PROFILE: Final[MovementProfile] = MovementProfile(reach=6, speed=2.5)
BALANCED_PROFILE: Final[MovementProfile] = MovementProfile(reach=9, speed=3.5)

ranged = RANGED_PROFILE
tank = TANK_PROFILE
balanced = BALANCED_PROFILE


@dataclass(slots=True)
class Target:
    kind: TargetKind
    ref: Union[Unit, TowerRef]
    position: float


@dataclass(slots=True)
class Hit:
    kind: TargetKind
    ref: Union[Unit, TowerRef]
    amount: float


def movement_profile(card: Card) -> MovementProfile:
    attack_ratio = card.atk / max(card.hp, 1)
    if attack_ratio > RULES.ranged_attack_ratio:
        return RANGED_PROFILE
    if attack_ratio < RULES.tank_attack_ratio:
        return TANK_PROFILE
    return BALANCED_PROFILE


def tower_position(side_index: int, slot: int) -> int:
    if slot == TowerSlot.KING:
        return RULES.king_positions[side_index]
    return RULES.princess_positions[side_index]


@dataclass(slots=True)
class Side:
    cards: List[Card]
    cooldowns: List[int] = field(init=False)
    elixir: float = field(default=RULES.starting_elixir)
    towers: List[float] = field(init=False)

    def __post_init__(self) -> None:
        self.cards = list(self.cards)
        self.cooldowns = [0] * len(self.cards)
        self.towers = list(RULES.initial_tower_health)

    def tower_hp_ratio(self) -> float:
        return sum(max(0.0, health) for health in self.towers) / RULES.total_tower_health

    def can_afford(self, card: Card) -> bool:
        return self.elixir >= card.cost

    def start_cooldown(self, index: int) -> None:
        self.cooldowns[index] = math.ceil(self.cards[index].cooldown / RULES.tick_seconds)

    def regenerate(self, gain: float) -> None:
        self.elixir = min(RULES.maximum_elixir, self.elixir + max(0.0, gain))

    def cool_down(self) -> None:
        self.cooldowns = [max(0, remaining - 1) for remaining in self.cooldowns]

    def damage_tower(self, slot: int, amount: float) -> None:
        self.towers[slot] = max(0.0, self.towers[slot] - max(0.0, amount))


class Game:
    def __init__(self, deck_a: Sequence[Card], deck_b: Sequence[Card]) -> None:
        self.sides: List[Side] = [Side(deck_a), Side(deck_b)]
        self.units: List[Unit] = []
        self.ticks = 0
        self.overtime = False
        self.over = False
        self.winner: Optional[int] = None
        self.scale = self._calculate_health_scale((*deck_a, *deck_b))

    @staticmethod
    def _calculate_health_scale(cards: Iterable[Card]) -> float:
        card_list = tuple(cards)
        if not card_list:
            return 1.0
        average_health = sum(max(1, card.hp) for card in card_list) / len(card_list)
        return RULES.target_average_health / average_health

    @property
    def double_elixir(self) -> bool:
        return self.ticks >= RULES.double_elixir_after

    @property
    def time_limit(self) -> int:
        return RULES.overtime_time_limit if self.overtime else RULES.regular_time_limit

    def crowns(self, side: int) -> int:
        enemy_towers = self.sides[1 - side].towers
        if enemy_towers[TowerSlot.KING] <= 0:
            return 3
        return sum(enemy_towers[lane] <= 0 for lane in range(RULES.lanes))

    def seconds_left(self) -> int:
        return max(0, self.time_limit - self.ticks) * RULES.tick_seconds

    def play(self, side: int, index: int, lane: int) -> Optional[str]:
        if self.over:
            return "The battle is over."
        if side not in (0, 1):
            return "Invalid side."
        if not 0 <= index < len(self.sides[side].cards):
            return "Invalid card selection."
        if not 0 <= lane < RULES.lanes:
            return "Invalid lane selection."

        player = self.sides[side]
        card = player.cards[index]
        remaining_cooldown = player.cooldowns[index]
        if remaining_cooldown > 0:
            wait_seconds = remaining_cooldown * RULES.tick_seconds
            return f"{card.name} is on cooldown for {wait_seconds} more seconds."
        if not player.can_afford(card):
            return f"Not enough elixir for {card.name} ({card.cost})."

        player.elixir -= card.cost
        player.start_cooldown(index)
        profile = movement_profile(card)
        scaled_health = card.hp * self.scale
        self.units.append(
            Unit(
                side=side,
                lane=lane,
                pos=RULES.spawn_positions[side],
                hp=scaled_health,
                max_hp=scaled_health,
                dps=card.atk * self.scale * RULES.unit_damage_factor,
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
    ) -> Optional[Unit]:
        candidates = (
            unit
            for unit in self.units
            if unit.alive
            and unit.side == enemy_side
            and (lane is None or unit.lane == lane)
        )
        return min(
            (unit for unit in candidates if unit.distance_to(origin) <= limit),
            key=lambda unit: unit.distance_to(origin),
            default=None,
        )

    def _pick_target(self, unit: Unit) -> Optional[Target]:
        enemy_side = 1 - unit.side
        enemy_unit = self._closest_enemy(
            enemy_side,
            unit.pos,
            RULES.unit_aggro_range,
            lane=unit.lane,
        )
        if enemy_unit is not None:
            return Target(TargetKind.UNIT, enemy_unit, enemy_unit.pos)

        enemy_towers = self.sides[enemy_side].towers
        lane_tower = enemy_towers[unit.lane]
        if lane_tower > 0:
            return Target(
                TargetKind.TOWER,
                TowerRef(enemy_side, unit.lane),
                tower_position(enemy_side, unit.lane),
            )
        if enemy_towers[TowerSlot.KING] > 0:
            return Target(
                TargetKind.TOWER,
                TowerRef(enemy_side, TowerSlot.KING),
                tower_position(enemy_side, TowerSlot.KING),
            )
        return None

    def _collect_unit_hits(self) -> List[Hit]:
        hits: List[Hit] = []
        for unit in self.units:
            if not unit.alive:
                continue
            target = self._pick_target(unit)
            if target is None:
                continue

            distance = abs(target.position - unit.pos)
            movement_step = unit.speed * RULES.tick_seconds
            attack_fraction = 1.0
            if distance > unit.reach:
                movement_needed = distance - unit.reach
                moved = unit.move_toward(target.position, min(movement_step, movement_needed))
                attack_fraction = 1.0 - moved / movement_step if movement_step > 0 else 0.0
                if attack_fraction <= RULES.minimum_attack_fraction:
                    continue

            hits.append(
                Hit(
                    kind=target.kind,
                    ref=target.ref,
                    amount=unit.dps * RULES.tick_seconds * attack_fraction,
                )
            )
        return hits

    def _collect_tower_hits(self) -> List[Hit]:
        hits: List[Hit] = []
        for side_index, side in enumerate(self.sides):
            enemy_side = 1 - side_index
            for slot, health in enumerate(side.towers):
                if health <= 0:
                    continue
                lane = None if slot == TowerSlot.KING else slot
                tower_origin = tower_position(side_index, slot)
                target_unit = self._closest_enemy(
                    enemy_side,
                    tower_origin,
                    RULES.tower_attack_range,
                    lane=lane,
                )
                if target_unit is not None:
                    hits.append(
                        Hit(
                            TargetKind.UNIT,
                            target_unit,
                            RULES.tower_damage_per_second * RULES.tick_seconds,
                        )
                    )
        return hits

    def _apply(self, hit: Hit) -> None:
        if hit.kind is TargetKind.UNIT:
            if isinstance(hit.ref, Unit):
                hit.ref.receive_damage(hit.amount)
            return
        if isinstance(hit.ref, TowerRef):
            self.sides[hit.ref.side].damage_tower(hit.ref.slot, hit.amount)

    def tick(self) -> None:
        if self.over:
            return

        self.ticks += 1
        elixir_gain = RULES.tick_seconds / RULES.elixir_cycle_seconds
        if self.double_elixir:
            elixir_gain *= 2

        for side in self.sides:
            side.regenerate(elixir_gain)
            side.cool_down()

        pending_hits = self._collect_unit_hits()
        pending_hits.extend(self._collect_tower_hits())
        for hit in pending_hits:
            self._apply(hit)

        self.units = [unit for unit in self.units if unit.alive]
        self._check_end()

    def _finish(self, winner: Optional[int]) -> None:
        self.winner = winner
        self.over = True

    def _check_end(self) -> None:
        for side_index in range(2):
            enemy_king = self.sides[1 - side_index].towers[TowerSlot.KING]
            if enemy_king <= 0:
                self._finish(side_index)
                return

        crowns_a = self.crowns(0)
        crowns_b = self.crowns(1)
        leader = 0 if crowns_a > crowns_b else 1

        if self.overtime and crowns_a != crowns_b:
            self._finish(leader)
            return

        if not self.overtime and self.ticks >= RULES.match_ticks:
            if crowns_a != crowns_b:
                self._finish(leader)
            else:
                self.overtime = True
            return

        if self.overtime and self.ticks >= RULES.overtime_time_limit:
            health_a = self.sides[0].tower_hp_ratio()
            health_b = self.sides[1].tower_hp_ratio()
            difference = health_a - health_b
            if abs(difference) > RULES.health_ratio_tolerance:
                self._finish(0 if difference > 0 else 1)
            else:
                self._finish(None)
