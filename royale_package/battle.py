from __future__ import annotations

import math
from dataclasses import dataclass
from enum import Enum, IntEnum
from typing import Final, List, NamedTuple, Optional, Sequence, Tuple, Union

                                                                             
                          
 
                                                                          
                                                                         
                                                                    
                                                                             

@dataclass(frozen=True)
class _ClockConfiguration:

    tick_seconds: int
    regulation_ticks: int
    overtime_ticks: int
    double_resource_start_tick: int

@dataclass(frozen=True)
class _ResourceConfiguration:

    starting_amount: float
    capacity: float
    regeneration_period_seconds: float

@dataclass(frozen=True)
class _DeckConfiguration:

    maximum_cards: int

@dataclass(frozen=True)
class _FieldConfiguration:

    princess_positions: Tuple[int, int]
    king_positions: Tuple[int, int]
    spawn_positions: Tuple[int, int]
    lane_total: int
    length: int

@dataclass(frozen=True)
class _TowerConfiguration:

    princess_health: int
    king_health: int
    damage_per_second: int
    attack_range: int
    acquisition_range: int

@dataclass(frozen=True)
class _UnitBalanceConfiguration:

    damage_scale: float
    target_average_health: int
    ranged_attack_health_ratio: float
    tank_attack_health_ratio: float
    minimum_attack_fraction: float
    health_ratio_tolerance: float

_CLOCK: Final[_ClockConfiguration] = _ClockConfiguration(
    tick_seconds=3,
    regulation_ticks=60,
    overtime_ticks=20,
    double_resource_start_tick=40,
)

_RESOURCES: Final[_ResourceConfiguration] = _ResourceConfiguration(
    starting_amount=5.0,
    capacity=10.0,
    regeneration_period_seconds=2.8,
)

_DECK: Final[_DeckConfiguration] = _DeckConfiguration(
    maximum_cards=8,
)

_FIELD: Final[_FieldConfiguration] = _FieldConfiguration(
    princess_positions=(13, 87),
    king_positions=(0, 100),
    spawn_positions=(20, 80),
    lane_total=2,
    length=100,
)

_TOWERS: Final[_TowerConfiguration] = _TowerConfiguration(
    princess_health=1400,
    king_health=2400,
    damage_per_second=60,
    attack_range=25,
    acquisition_range=30,
)

_UNIT_BALANCE: Final[_UnitBalanceConfiguration] = _UnitBalanceConfiguration(
    damage_scale=0.12,
    target_average_health=600,
    ranged_attack_health_ratio=1.3,
    tank_attack_health_ratio=0.75,
    minimum_attack_fraction=0.01,
    health_ratio_tolerance=0.0001,
)

                                                                             
                                
 
                                                                         
                                                                     
                                                                             

TICK: Final[int] = _CLOCK.tick_seconds
MATCH_TICKS: Final[int] = _CLOCK.regulation_ticks
OVERTIME_TICKS: Final[int] = _CLOCK.overtime_ticks
DOUBLE_ELIXIR_AFTER: Final[int] = _CLOCK.double_resource_start_tick

START_ELIXIR: Final[float] = _RESOURCES.starting_amount
MAX_ELIXIR: Final[float] = _RESOURCES.capacity
ELIXIR_SECONDS: Final[float] = _RESOURCES.regeneration_period_seconds

DECK_SIZE: Final[int] = _DECK.maximum_cards

PRINCESS_POS: Final[Tuple[int, int]] = _FIELD.princess_positions
KING_POS: Final[Tuple[int, int]] = _FIELD.king_positions
SPAWN_POS: Final[Tuple[int, int]] = _FIELD.spawn_positions
LANE_COUNT: Final[int] = _FIELD.lane_total
FIELD_LENGTH: Final[int] = _FIELD.length

PRINCESS_HP: Final[int] = _TOWERS.princess_health
KING_HP: Final[int] = _TOWERS.king_health
TOWER_DPS: Final[int] = _TOWERS.damage_per_second
TOWER_RANGE: Final[int] = _TOWERS.attack_range
AGGRO_RANGE: Final[int] = _TOWERS.acquisition_range

UNIT_DPS_FACTOR: Final[float] = _UNIT_BALANCE.damage_scale
HP_SCALE_TARGET: Final[int] = _UNIT_BALANCE.target_average_health
RANGED_RATIO: Final[float] = _UNIT_BALANCE.ranged_attack_health_ratio
TANK_RATIO: Final[float] = _UNIT_BALANCE.tank_attack_health_ratio
MIN_FRACTION: Final[float] = _UNIT_BALANCE.minimum_attack_fraction
RATIO_TOLERANCE: Final[float] = _UNIT_BALANCE.health_ratio_tolerance

                                                                             
                                        
                                                                             

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

                                                                             
                    
                                                                             

@dataclass
class Card:

    ball_id: int
    name: str
    atk: int
    hp: int
    cost: int
    cooldown: int

@dataclass
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
        self.pos = max(0, min(FIELD_LENGTH, self.pos))

@dataclass(frozen=True)
class MovementProfile:

    reach: float
    speed: float

                                                                       
RANGED: Final[MovementProfile] = MovementProfile(reach=18, speed=3.0)
TANK: Final[MovementProfile] = MovementProfile(reach=6, speed=2.5)
BALANCED: Final[MovementProfile] = MovementProfile(reach=9, speed=3.5)

@dataclass
class Target:

    kind: TargetKind
    ref: Union[Unit, TowerRef]
    position: float

@dataclass
class Hit:

    kind: TargetKind
    ref: Union[Unit, TowerRef]
    amount: float

def movement_profile(card: Card) -> MovementProfile:
    ratio = card.atk / max(card.hp, 1)
    if ratio > RANGED_RATIO:
        return RANGED
    if ratio < TANK_RATIO:
        return TANK
    return BALANCED

def tower_position(side_index: int, slot: int) -> int:
    if slot == TowerSlot.KING:
        return KING_POS[side_index]
    return PRINCESS_POS[side_index]

class Side:
    def __init__(self, cards: Sequence[Card]) -> None:
        self.cards: List[Card] = list(cards)
        self.cooldowns: List[int] = [0 for _ in self.cards]
        self.elixir: float = START_ELIXIR
        self.towers: List[float] = [PRINCESS_HP, PRINCESS_HP, KING_HP]

    def tower_hp_ratio(self) -> float:
        remaining = sum(self.towers)
        maximum = PRINCESS_HP * 2 + KING_HP
        return remaining / maximum

    def can_afford(self, card: Card) -> bool:
        return self.elixir >= card.cost

    def start_cooldown(self, index: int) -> None:
        self.cooldowns[index] = math.ceil(self.cards[index].cooldown / TICK)

    def regenerate(self, gain: float) -> None:
        self.elixir = min(MAX_ELIXIR, self.elixir + gain)

    def cool_down(self) -> None:
        self.cooldowns = [max(0, remaining - 1) for remaining in self.cooldowns]

class Game:
    def __init__(self, deck_a: Sequence[Card], deck_b: Sequence[Card]) -> None:
        self.sides: List[Side] = [Side(deck_a), Side(deck_b)]
        self.units: List[Unit] = []
        self.ticks: int = 0
        self.overtime: bool = False
        self.over: bool = False
        self.winner: Optional[int] = None

        everyone = list(deck_a) + list(deck_b)
        average_hp = sum(card.hp for card in everyone) / len(everyone)
        self.scale: float = HP_SCALE_TARGET / average_hp

    @property
    def double_elixir(self) -> bool:
        return self.ticks >= DOUBLE_ELIXIR_AFTER

    @property
    def time_limit(self) -> int:
        if self.overtime:
            return MATCH_TICKS + OVERTIME_TICKS
        return MATCH_TICKS

    def crowns(self, side: int) -> int:
        enemy = self.sides[1 - side]
        if enemy.towers[TowerSlot.KING] <= 0:
            return 3
        return sum(1 for lane in range(LANE_COUNT) if enemy.towers[lane] <= 0)

    def seconds_left(self) -> int:
        ticks_left = max(0, self.time_limit - self.ticks)
        return ticks_left * TICK

    def play(self, side: int, index: int, lane: int) -> Optional[str]:
        if self.over:
            return "The battle is over."

        player = self.sides[side]
        card = player.cards[index]

        if player.cooldowns[index] > 0:
            wait = player.cooldowns[index] * TICK
            return f"{card.name} is on cooldown for {wait} more seconds."

        if not player.can_afford(card):
            return f"Not enough elixir for {card.name} ({card.cost})."

        player.elixir -= card.cost
        player.start_cooldown(index)

        profile = movement_profile(card)
        unit_hp = card.hp * self.scale
        self.units.append(
            Unit(
                side=side,
                lane=lane,
                pos=SPAWN_POS[side],
                hp=unit_hp,
                max_hp=unit_hp,
                dps=card.atk * self.scale * UNIT_DPS_FACTOR,
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
        closest: Optional[Unit] = None
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

    def _pick_target(self, unit: Unit) -> Optional[Target]:
        enemy_side = 1 - unit.side

        enemy_unit = self._closest_enemy(enemy_side, unit.pos, AGGRO_RANGE, lane=unit.lane)
        if enemy_unit is not None:
            return Target(TargetKind.UNIT, enemy_unit, enemy_unit.pos)

        enemy = self.sides[enemy_side]
        if enemy.towers[unit.lane] > 0:
            return Target(
                TargetKind.TOWER,
                TowerRef(enemy_side, unit.lane),
                tower_position(enemy_side, unit.lane),
            )
        if enemy.towers[TowerSlot.KING] > 0:
            return Target(
                TargetKind.TOWER,
                TowerRef(enemy_side, TowerSlot.KING),
                tower_position(enemy_side, TowerSlot.KING),
            )
        return None

    def _collect_unit_hits(self) -> List[Hit]:
        hits: List[Hit] = []
        for unit in self.units:
            target = self._pick_target(unit)
            if target is None:
                continue

            distance = abs(target.position - unit.pos)
            step = unit.speed * TICK
            fraction = 1.0

            if distance > unit.reach:
                move = min(step, distance - unit.reach)
                if target.position > unit.pos:
                    unit.pos += move
                else:
                    unit.pos -= move
                unit.clamp_position()

                fraction = 1 - move / step
                if fraction <= MIN_FRACTION:
                    continue

            hits.append(Hit(target.kind, target.ref, unit.dps * TICK * fraction))
        return hits

    def _collect_tower_hits(self) -> List[Hit]:
        hits: List[Hit] = []
        for side_index, side in enumerate(self.sides):
            enemy_side = 1 - side_index
            for slot, remaining in enumerate(side.towers):
                if remaining <= 0:
                    continue

                lane = None if slot == TowerSlot.KING else slot
                origin = tower_position(side_index, slot)
                foe = self._closest_enemy(enemy_side, origin, TOWER_RANGE, lane=lane)
                if foe is not None:
                    hits.append(Hit(TargetKind.UNIT, foe, TOWER_DPS * TICK))
        return hits

    def _apply(self, hit: Hit) -> None:
        if hit.kind is TargetKind.UNIT:
            hit.ref.hp -= hit.amount
            return
        towers = self.sides[hit.ref.side].towers
        towers[hit.ref.slot] = max(0, towers[hit.ref.slot] - hit.amount)

    def tick(self) -> None:
        self.ticks += 1

        gain = TICK / ELIXIR_SECONDS
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
            if self.sides[1 - side].towers[TowerSlot.KING] <= 0:
                self._finish(side)
                return

        crowns_a = self.crowns(0)
        crowns_b = self.crowns(1)
        leader = 0 if crowns_a > crowns_b else 1

        if self.overtime and crowns_a != crowns_b:
            self._finish(leader)
            return

        if not self.overtime and self.ticks >= MATCH_TICKS:
            if crowns_a != crowns_b:
                self._finish(leader)
            else:
                self.overtime = True
            return

        if self.overtime and self.ticks >= MATCH_TICKS + OVERTIME_TICKS:
            ratio_a = self.sides[1].tower_hp_ratio()
            ratio_b = self.sides[0].tower_hp_ratio()
            if abs(ratio_a - ratio_b) > RATIO_TOLERANCE:
                self._finish(0 if ratio_a < ratio_b else 1)
            else:
                self._finish(None)
