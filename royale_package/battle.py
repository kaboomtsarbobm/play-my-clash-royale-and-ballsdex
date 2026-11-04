import math
from dataclasses import dataclass

TICK = 3
MATCH_TICKS = 60
OVERTIME_TICKS = 20
DOUBLE_ELIXIR_AFTER = 40
START_ELIXIR = 5.0
MAX_ELIXIR = 10.0
ELIXIR_SECONDS = 2.8
DECK_SIZE = 8

PRINCESS_POS = (13, 87)
KING_POS = (0, 100)
SPAWN_POS = (20, 80)
PRINCESS_HP = 1400
KING_HP = 2400
TOWER_DPS = 60
TOWER_RANGE = 25
AGGRO_RANGE = 30


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


class Side:
    def __init__(self, cards: list[Card]):
        self.cards = list(cards)
        self.cooldowns = [0] * len(cards)
        self.elixir = START_ELIXIR
        self.towers = [PRINCESS_HP, PRINCESS_HP, KING_HP]

    def tower_hp_ratio(self) -> float:
        return sum(self.towers) / (PRINCESS_HP * 2 + KING_HP)


class Game:
    def __init__(self, deck_a: list[Card], deck_b: list[Card]):
        self.sides = [Side(deck_a), Side(deck_b)]
        self.units: list[Unit] = []
        self.ticks = 0
        self.overtime = False
        self.over = False
        self.winner: int | None = None
        everyone = deck_a + deck_b
        self.scale = 600 / (sum(c.hp for c in everyone) / len(everyone))

    @property
    def double_elixir(self) -> bool:
        return self.ticks >= DOUBLE_ELIXIR_AFTER

    def crowns(self, side: int) -> int:
        enemy = self.sides[1 - side]
        if enemy.towers[2] <= 0:
            return 3
        return sum(1 for hp in enemy.towers[:2] if hp <= 0)

    def seconds_left(self) -> int:
        limit = MATCH_TICKS + (OVERTIME_TICKS if self.overtime else 0)
        return max(0, (limit - self.ticks) * TICK)

    def play(self, side: int, index: int, lane: int) -> str | None:
        if self.over:
            return "The battle is over."
        s = self.sides[side]
        card = s.cards[index]
        if s.cooldowns[index] > 0:
            return f"{card.name} is on cooldown for {s.cooldowns[index] * TICK} more seconds."
        if s.elixir < card.cost:
            return f"Not enough elixir for {card.name} ({card.cost})."

        s.elixir -= card.cost
        s.cooldowns[index] = math.ceil(card.cooldown / TICK)

        ratio = card.atk / max(card.hp, 1)
        if ratio > 1.3:
            reach, speed = 18, 3.0
        elif ratio < 0.75:
            reach, speed = 6, 2.5
        else:
            reach, speed = 9, 3.5

        hp = card.hp * self.scale
        self.units.append(
            Unit(
                side=side,
                lane=lane,
                pos=SPAWN_POS[side],
                hp=hp,
                max_hp=hp,
                dps=card.atk * self.scale * 0.12,
                reach=reach,
                speed=speed,
                name=card.name,
            )
        )
        return None

    def _pick_target(self, unit: Unit):
        enemy_side = 1 - unit.side
        near = [
            e for e in self.units
            if e.side == enemy_side and e.lane == unit.lane and abs(e.pos - unit.pos) <= AGGRO_RANGE
        ]
        if near:
            target = min(near, key=lambda e: abs(e.pos - unit.pos))
            return ("unit", target, target.pos)

        enemy = self.sides[enemy_side]
        if enemy.towers[unit.lane] > 0:
            return ("tower", (enemy_side, unit.lane), PRINCESS_POS[enemy_side])
        if enemy.towers[2] > 0:
            return ("tower", (enemy_side, 2), KING_POS[enemy_side])
        return None

    def tick(self) -> None:
        self.ticks += 1
        gain = TICK / ELIXIR_SECONDS * (2 if self.double_elixir else 1)
        for s in self.sides:
            s.elixir = min(MAX_ELIXIR, s.elixir + gain)
            s.cooldowns = [max(0, c - 1) for c in s.cooldowns]

        hits = []

        for unit in self.units:
            target = self._pick_target(unit)
            if target is None:
                continue
            kind, ref, tpos = target
            dist = abs(tpos - unit.pos)
            step = unit.speed * TICK
            fraction = 1.0
            if dist > unit.reach:
                move = min(step, dist - unit.reach)
                unit.pos += move if tpos > unit.pos else -move
                unit.pos = max(0, min(100, unit.pos))
                fraction = 1 - move / step
                if fraction <= 0.01:
                    continue
            hits.append((kind, ref, unit.dps * TICK * fraction))

        for side_index, side in enumerate(self.sides):
            enemy_side = 1 - side_index
            for t in range(3):
                if side.towers[t] <= 0:
                    continue
                tower_pos = KING_POS[side_index] if t == 2 else PRINCESS_POS[side_index]
                foes = [
                    e for e in self.units
                    if e.side == enemy_side and (t == 2 or e.lane == t) and abs(e.pos - tower_pos) <= TOWER_RANGE
                ]
                if foes:
                    foe = min(foes, key=lambda e: abs(e.pos - tower_pos))
                    hits.append(("unit", foe, TOWER_DPS * TICK))

        for kind, ref, amount in hits:
            if kind == "unit":
                ref.hp -= amount
            else:
                side_index, t = ref
                tower = self.sides[side_index].towers
                tower[t] = max(0, tower[t] - amount)

        self.units = [u for u in self.units if u.hp > 0]
        self._check_end()

    def _check_end(self) -> None:
        for side in (0, 1):
            if self.sides[1 - side].towers[2] <= 0:
                self.winner, self.over = side, True
                return

        a, b = self.crowns(0), self.crowns(1)

        if self.overtime and a != b:
            self.winner, self.over = (0 if a > b else 1), True
            return

        if not self.overtime and self.ticks >= MATCH_TICKS:
            if a != b:
                self.winner, self.over = (0 if a > b else 1), True
            else:
                self.overtime = True
            return

        if self.overtime and self.ticks >= MATCH_TICKS + OVERTIME_TICKS:
            ra, rb = self.sides[1].tower_hp_ratio(), self.sides[0].tower_hp_ratio()
            self.over = True
            if abs(ra - rb) > 0.0001:
                self.winner = 0 if ra < rb else 1
            else:
                self.winner = None
