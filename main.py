"""
Block Blitz - a neon, space-themed falling-blocks game made with pygame.

Controls
    Left / Right   move (hold to slide)
    Up or X        rotate
    Down           soft drop   (+1 point per row)
    Space          hard drop   (+2 points per row)
    C              hold piece
    P              pause        (R restarts while paused)
    M              sound on / off
    Esc            quit

Files it uses from this folder: font.TTF, sound.py, sound/*.ogg, record.
The background is drawn in code, so no image files are needed.
"""
import math
import random
import sys
from pathlib import Path

import pygame

try:
    from sound import Music
except ImportError:  # the game still works without sound.py
    Music = None

# ================================================================ settings
COLS, ROWS = 10, 20
TILE = 45
FIELD_SIZE = (COLS * TILE, ROWS * TILE)
FIELD_POS = (20, 20)
RES = (750, 940)
PANEL_X = 610            # horizontal centre of the right-hand panel
FPS = 60

BASE_DIR = Path(__file__).resolve().parent
RECORD_FILE = BASE_DIR / "record"

# timings (milliseconds)
LINE_CLEAR_TIME = 220    # cleared rows flash for this long
LOCK_DELAY = 500         # time a piece can slide on the floor before locking
MAX_LOCK_RESETS = 15     # moves/rotations that restart the lock timer
DAS_DELAY = 170          # hold Left/Right this long before auto-repeat starts
DAS_REPEAT = 45          # auto-repeat speed
SOFT_DROP_INTERVAL = 35
TRAIL_TIME = 180         # hard-drop streak

NEXT_COUNT = 3
LINE_SCORES = {1: 100, 2: 300, 3: 700, 4: 1500}   # multiplied by level
CLEAR_NAMES = {1: "SINGLE", 2: "DOUBLE", 3: "TRIPLE", 4: "BLITZ!"}

# The first cell of each shape is its rotation centre.
SHAPES = {
    "I": [(-1, 0), (-2, 0), (0, 0), (1, 0)],
    "O": [(0, -1), (-1, -1), (-1, 0), (0, 0)],
    "S": [(-1, 0), (-1, 1), (0, 0), (0, -1)],
    "Z": [(0, 0), (-1, 0), (0, 1), (-1, -1)],
    "J": [(0, 0), (0, -1), (0, 1), (-1, -1)],
    "L": [(0, 0), (0, -1), (0, 1), (1, -1)],
    "T": [(0, 0), (0, -1), (0, 1), (-1, 0)],
}

# neon palette
COLORS = {
    "I": (0, 235, 255),
    "O": (255, 215, 0),
    "S": (60, 255, 130),
    "Z": (255, 60, 105),
    "J": (70, 130, 255),
    "L": (255, 145, 40),
    "T": (200, 85, 255),
}
LEVEL_THEMES = [          # field border colour changes every level
    (0, 229, 255), (180, 120, 255), (255, 64, 150), (90, 255, 170),
    (255, 210, 60), (255, 110, 64), (64, 170, 255), (240, 120, 255),
]
TEXT = (236, 240, 255)
MUTED = (145, 155, 200)
GOLD = (255, 210, 80)
ORANGE = (255, 160, 50)
PINK = (255, 80, 140)
DEAD_BLOCK = (70, 72, 95)
NEBULA = [(110, 40, 190), (30, 90, 200), (200, 40, 140), (20, 150, 170)]


# ================================================================ helpers
def mix(c1, c2, t):
    return tuple(int(a + (b - a) * t) for a, b in zip(c1, c2))


def scale_color(color, factor):
    return tuple(max(0, min(255, int(v * factor))) for v in color)


def lighten(color, t):
    return mix(color, (255, 255, 255), t)


def load_font(size):
    path = BASE_DIR / "font.TTF"
    return pygame.font.Font(str(path) if path.exists() else None, size)


def load_record():
    try:
        return int(RECORD_FILE.read_text().strip() or 0)
    except (FileNotFoundError, ValueError):
        return 0


def save_record(value):
    try:
        RECORD_FILE.write_text(str(value))
    except OSError:
        pass


def format_time(ms):
    seconds = int(ms // 1000)
    return f"{seconds // 60:02d}:{seconds % 60:02d}"


# ================================================================ pieces
class Piece:
    def __init__(self, kind):
        self.kind = kind
        self.color = COLORS[kind]
        self.cells = [(x + COLS // 2, y + 1) for x, y in SHAPES[kind]]

    def shifted(self, dx, dy):
        return [(x + dx, y + dy) for x, y in self.cells]

    def rotated(self):
        if self.kind == "O":  # a square doesn't need to rotate
            return list(self.cells)
        cx, cy = self.cells[0]
        return [(cx - (y - cy), cy + (x - cx)) for x, y in self.cells]


class Bag:
    """7-bag randomizer: every piece appears once per 7 before any repeats."""

    def __init__(self):
        self.items = []

    def next(self):
        if not self.items:
            self.items = list(SHAPES)
            random.shuffle(self.items)
        return self.items.pop()


# ================================================================ sound
class Sound:
    """Wraps the Music class so a missing sound file never crashes the game."""

    def __init__(self):
        self.music = None
        self.muted = False
        if Music is None:
            return
        try:
            self.music = Music()
            self.music.set_music_volume(0.1)
            self.music.set_rotate_volume(0.4)
            self.music.set_clear_volume(0.8)
            self.music.set_collision_volume(0.1)
            if hasattr(self.music, "set_game_over_volume"):
                self.music.set_game_over_volume(0.5)
        except Exception as err:
            print(f"Sound disabled: {err}")
            self.music = None

    def play(self, name, *args):
        if self.music and not self.muted:
            getattr(self.music, name)(*args)

    def start_music(self):
        if self.music:
            self.music.play_music()
            pygame.mixer.music.set_volume(0 if self.muted else self.music.music_volume)

    def pause(self):
        if self.music:
            pygame.mixer.music.pause()

    def resume(self):
        if self.music:
            pygame.mixer.music.unpause()

    def toggle_mute(self):
        self.muted = not self.muted
        if self.music:
            pygame.mixer.music.set_volume(0 if self.muted else self.music.music_volume)


# ================================================================ visuals
class Art:
    """Builds neon sprites once and caches them, so drawing stays fast."""

    def __init__(self):
        self.cache = {}

    def _get(self, key, build):
        if key not in self.cache:
            self.cache[key] = build()
        return self.cache[key]

    def glow(self, size, color, spread=12, strength=170, radius=8, width=0):
        """A soft blurred rectangle (or outline, if width > 0)."""
        def build():
            w, h = size
            surf = pygame.Surface((w + spread * 2, h + spread * 2), pygame.SRCALPHA)
            surf.fill((*color, 0))  # transparent pixels keep the colour -> no dark edges
            pygame.draw.rect(surf, (*color, strength), (spread, spread, w, h),
                             width, border_radius=radius)
            full = surf.get_size()
            small = pygame.transform.smoothscale(surf, (max(1, full[0] // 4), max(1, full[1] // 4)))
            return pygame.transform.smoothscale(small, full)
        return self._get(("glow", size, color, spread, strength, radius, width), build)

    @staticmethod
    def block_pad(glow):
        return 8 if glow else 0

    def block(self, color, size=TILE, glow=False):
        def build():
            pad = self.block_pad(glow)
            surf = pygame.Surface((size + pad * 2, size + pad * 2), pygame.SRCALPHA)
            if glow:
                surf.blit(self.glow((size - 2, size - 2), color, spread=pad,
                                    strength=130, radius=size // 6), (1, 1))
            rect = pygame.Rect(pad, pad, size - 2, size - 2)
            r = max(2, size // 7)
            pygame.draw.rect(surf, scale_color(color, 0.30), rect, border_radius=r)
            pygame.draw.rect(surf, scale_color(color, 0.55), rect.inflate(-size // 4, -size // 4),
                             border_radius=r)
            pygame.draw.rect(surf, color, rect, width=max(2, size // 12), border_radius=r)
            shine = lighten(color, 0.7)
            pygame.draw.line(surf, shine, (rect.x + r + 1, rect.y + 4),
                             (rect.right - r - 2, rect.y + 4), 2)
            return surf
        return self._get(("block", color, size, glow), build)

    def ghost(self, color):
        def build():
            surf = pygame.Surface((TILE - 2, TILE - 2), pygame.SRCALPHA)
            rect = surf.get_rect()
            pygame.draw.rect(surf, (*color, 30), rect, border_radius=6)
            pygame.draw.rect(surf, (*color, 150), rect, width=2, border_radius=6)
            return surf
        return self._get(("ghost", color), build)

    def card(self, size):
        def build():
            surf = pygame.Surface(size, pygame.SRCALPHA)
            rect = surf.get_rect()
            pygame.draw.rect(surf, (10, 12, 32, 175), rect, border_radius=14)
            pygame.draw.rect(surf, (255, 255, 255, 38), rect, width=2, border_radius=14)
            return surf
        return self._get(("card", size), build)

    def field_frame(self):
        def build():
            surf = pygame.Surface(FIELD_SIZE, pygame.SRCALPHA)
            surf.fill((5, 6, 18, 190))
            line = (28, 32, 62, 200)
            for x in range(1, COLS):
                pygame.draw.line(surf, line, (x * TILE, 0), (x * TILE, FIELD_SIZE[1]))
            for y in range(1, ROWS):
                pygame.draw.line(surf, line, (0, y * TILE), (FIELD_SIZE[0], y * TILE))
            return surf
        return self._get(("field",), build)


class Starfield:
    """Gradient sky + nebula clouds + twinkling, drifting stars."""

    def __init__(self, size, count=170):
        self.w, self.h = size
        self.base = self._build_base()
        self.stars = [
            [random.uniform(0, self.w), random.uniform(0, self.h),
             random.choice((1, 1, 1, 2, 2, 3)),          # size = depth
             random.uniform(0, math.tau), random.uniform(0.002, 0.006)]
            for _ in range(count)
        ]
        self.t = 0
        self.warp = 0  # counts down after a level-up

    def _build_base(self):
        surf = pygame.Surface((self.w, self.h))
        top, bottom = (6, 5, 20), (24, 8, 38)
        for y in range(self.h):
            pygame.draw.line(surf, mix(top, bottom, y / (self.h - 1)), (0, y), (self.w - 1, y))

        # nebula: paint soft blobs on a tiny image, then scale it up (free blur)
        sw, sh = self.w // 10, self.h // 10
        small = pygame.Surface((sw, sh), 0, 32)
        rng = random.Random(42)
        blobs = [(rng.uniform(0, sw), rng.uniform(0, sh), rng.uniform(8, 22),
                  rng.choice(NEBULA), rng.uniform(0.25, 0.6)) for _ in range(10)]
        for x in range(sw):
            for y in range(sh):
                r = g = b = 0.0
                for bx, by, rad, col, k in blobs:
                    f = k * math.exp(-((x - bx) ** 2 + (y - by) ** 2) / (rad * rad))
                    r += col[0] * f
                    g += col[1] * f
                    b += col[2] * f
                small.set_at((x, y), (min(255, int(r)), min(255, int(g)), min(255, int(b))))
        surf.blit(pygame.transform.smoothscale(small, (self.w, self.h)), (0, 0),
                  special_flags=pygame.BLEND_ADD)
        return surf

    def boost(self):
        self.warp = 1200

    def update(self, dt, speed=1.0):
        self.t += dt
        mult = speed + 5 * (self.warp / 1200)
        self.warp = max(0, self.warp - dt)
        for star in self.stars:
            star[1] += star[2] * 0.012 * dt * mult
            if star[1] > self.h:
                star[1] -= self.h
                star[0] = random.uniform(0, self.w)

    def draw(self, screen):
        screen.blit(self.base, (0, 0))
        streak = self.warp / 1200 * 40
        for x, y, size, phase, twinkle in self.stars:
            b = 0.55 + 0.45 * math.sin(self.t * twinkle + phase)
            c = int(110 + 145 * b)
            color = (int(c * 0.85), int(c * 0.9), c)
            ix, iy = int(x), int(y)
            if streak > 1 and size > 1:
                pygame.draw.line(screen, scale_color(color, 0.5), (ix, iy - int(streak * size)), (ix, iy))
            if size == 1:
                screen.fill(color, (ix, iy, 1, 1))
            elif size == 2:
                screen.fill(color, (ix, iy, 2, 2))
            else:
                pygame.draw.circle(screen, color, (ix, iy), 2)


class Particle:
    __slots__ = ("x", "y", "vx", "vy", "color", "size", "life", "max_life")

    def __init__(self, x, y, vx, vy, color, size, life):
        self.x, self.y, self.vx, self.vy = x, y, vx, vy
        self.color, self.size = color, size
        self.life = self.max_life = life

    def update(self, dt):
        s = dt / 1000
        self.vy += 900 * s  # gravity
        self.x += self.vx * s
        self.y += self.vy * s
        self.life -= dt
        return self.life > 0


class FloatText:
    """Text that pops up, floats upward and fades out (e.g. "DOUBLE", "+600")."""

    def __init__(self, text, color, pos, font="mid", life=1100, delay=0, rise=70):
        self.text, self.color, self.pos, self.font = text, color, pos, font
        self.life, self.delay, self.rise = life, delay, rise
        self.age = 0

    def update(self, dt):
        self.age += dt
        return self.age < self.life + self.delay


# ================================================================ game
class Game:
    def __init__(self):
        pygame.init()
        pygame.display.set_icon(self._make_icon())
        pygame.display.set_caption("Block Blitz")
        self.screen = pygame.display.set_mode(RES)
        self.clock = pygame.time.Clock()

        self.fonts = {
            "hero": load_font(64),
            "title": load_font(42),
            "big": load_font(30),
            "mid": load_font(26),
            "label": load_font(20),
            "small": load_font(16),
        }
        self.art = Art()
        self.stars = Starfield(RES)
        self.sound = Sound()
        self.record = load_record()
        self.state = "start"  # start | play | pause | over
        self.time = 0
        self.menu_pieces = [self._new_menu_piece(random.uniform(-RES[1], RES[1])) for _ in range(9)]
        self.reset()

    @staticmethod
    def _make_icon():
        icon = pygame.Surface((32, 32), pygame.SRCALPHA)
        for (x, y), color in zip([(2, 2), (17, 2), (2, 17), (17, 17)],
                                 [COLORS["I"], COLORS["Z"], COLORS["S"], COLORS["O"]]):
            pygame.draw.rect(icon, color, (x, y, 13, 13), border_radius=3)
        return icon

    # ------------------------------------------------ state
    def reset(self):
        self.field = [[None] * COLS for _ in range(ROWS)]
        self.bag = Bag()
        self.queue = [self.bag.next() for _ in range(NEXT_COUNT)]
        self.hold_kind = None
        self.can_hold = True
        self.score = 0
        self.lines = 0
        self.combo = -1
        self.back_to_back = False
        self.play_time = 0
        self.fall_timer = 0
        self.lock_timer = 0
        self.lock_resets = 0
        self.move_dir = 0
        self.move_timer = 0
        self.clearing_rows = []
        self.clear_timer = 0
        self.particles = []
        self.floaters = []
        self.trails = []
        self.shake = 0.0
        self.over_timer = 0
        self.new_record = False
        self.piece = None
        self.spawn()

    def start_game(self):
        self.reset()
        self.state = "play"
        self.sound.start_music()

    @property
    def level(self):
        return self.lines // 10 + 1

    @property
    def fall_interval(self):
        return max(70, 550 - (self.level - 1) * 45)

    @property
    def accent(self):
        return LEVEL_THEMES[(self.level - 1) % len(LEVEL_THEMES)]

    # ------------------------------------------------ board logic
    def is_valid(self, cells):
        for x, y in cells:
            if not 0 <= x < COLS or y >= ROWS:
                return False
            if y >= 0 and self.field[y][x]:
                return False
        return True

    def on_ground(self):
        return not self.is_valid(self.piece.shifted(0, 1))

    def try_move(self, dx, dy):
        cells = self.piece.shifted(dx, dy)
        if self.is_valid(cells):
            self.piece.cells = cells
            return True
        return False

    def player_moved(self):
        """Sliding or rotating on the floor buys a little more time (lock delay)."""
        if self.on_ground() and self.lock_resets < MAX_LOCK_RESETS:
            self.lock_timer = 0
            self.lock_resets += 1

    def rotate(self):
        rotated = self.piece.rotated()
        # "wall kicks": if rotation hits a wall or block, try nudging the piece
        for dx, dy in ((0, 0), (-1, 0), (1, 0), (-2, 0), (2, 0), (0, -1)):
            cells = [(x + dx, y + dy) for x, y in rotated]
            if self.is_valid(cells):
                self.piece.cells = cells
                self.sound.play("rotation_sound")
                self.player_moved()
                return

    def ghost_cells(self):
        dy = 0
        while self.is_valid(self.piece.shifted(0, dy + 1)):
            dy += 1
        return self.piece.shifted(0, dy)

    def hard_drop(self):
        start = list(self.piece.cells)
        rows = 0
        while self.try_move(0, 1):
            rows += 1
        self.score += rows * 2
        if rows:
            for col in {x for x, _ in start}:
                top = min(y for x, y in start if x == col)
                bottom = max(y for x, y in self.piece.cells if x == col)
                self.trails.append([col, max(0, top), bottom, self.piece.color, TRAIL_TIME])
            self.shake = max(self.shake, 5)
        self.lock_piece()

    def hold(self):
        if not self.can_hold:
            return
        current = self.piece.kind
        if self.hold_kind is None:
            self.spawn()
        else:
            self.piece = Piece(self.hold_kind)
            self._reset_piece_timers()
            if not self.is_valid(self.piece.cells):
                self.game_over()
        self.hold_kind = current
        self.can_hold = False

    def _reset_piece_timers(self):
        self.fall_timer = 0
        self.lock_timer = 0
        self.lock_resets = 0

    def spawn(self):
        self.piece = Piece(self.queue.pop(0))
        self.queue.append(self.bag.next())
        self.can_hold = True
        self._reset_piece_timers()
        if not self.is_valid(self.piece.cells):
            self.game_over()

    def lock_piece(self):
        for x, y in self.piece.cells:
            if y < 0:  # locked above the top of the board
                self.game_over()
                return
        for x, y in self.piece.cells:
            self.field[y][x] = self.piece.color
        self.sound.play("collision_sound")

        full = [y for y in range(ROWS) if all(self.field[y])]
        if full:
            self.clearing_rows = full
            self.clear_timer = LINE_CLEAR_TIME
            self.sound.play("clear_sound", len(full))
            self.burst_rows(full)
            self.shake = max(self.shake, 4 + 2 * len(full))
        else:
            self.combo = -1  # a piece that clears nothing ends the combo
            self.spawn()

    def finish_clear(self):
        rows = self.clearing_rows
        count = len(rows)
        old_level = self.level

        kept = [row for y, row in enumerate(self.field) if y not in rows]
        self.field = [[None] * COLS for _ in range(count)] + kept

        self.combo += 1
        points = LINE_SCORES[count] * self.level
        blitz = count == 4
        if blitz and self.back_to_back:
            points = points * 3 // 2
        if self.combo > 0:
            points += 50 * self.combo * self.level
        self.score += points
        self.lines += count

        # pop-up text
        cx = FIELD_POS[0] + FIELD_SIZE[0] // 2
        cy = FIELD_POS[1] + int(sum(rows) / count * TILE)
        cy = max(160, min(cy, FIELD_POS[1] + FIELD_SIZE[1] - 120))
        name_color = GOLD if blitz else TEXT
        self.floaters.append(FloatText(CLEAR_NAMES[count], name_color, (cx, cy),
                                       font="title" if blitz else "big"))
        self.floaters.append(FloatText(f"+{points}", self.accent, (cx, cy + 45), font="label", delay=80))
        if blitz and self.back_to_back:
            self.floaters.append(FloatText("BACK TO BACK", PINK, (cx, cy - 50), font="label", delay=120))
        if self.combo > 0:
            self.floaters.append(FloatText(f"COMBO x{self.combo}", ORANGE, (cx, cy + 80),
                                           font="label", delay=160))
        self.back_to_back = blitz

        if self.level > old_level:
            self.stars.boost()
            self.floaters.append(FloatText(f"LEVEL {self.level}", self.accent,
                                           (cx, FIELD_POS[1] + FIELD_SIZE[1] // 2 - 120),
                                           font="title", life=1600, delay=250, rise=40))

        self.clearing_rows = []
        self.spawn()

    def game_over(self):
        if self.state == "over":
            return
        self.state = "over"
        self.over_timer = 0
        self.shake = 10
        if self.score > self.record:
            self.record = self.score
            self.new_record = True
            save_record(self.record)
        self.sound.play("game_over_sound")

    # ------------------------------------------------ effects
    def burst_rows(self, rows):
        for y in rows:
            for x in range(COLS):
                color = self.field[y][x]
                cx = FIELD_POS[0] + x * TILE + TILE / 2
                cy = FIELD_POS[1] + y * TILE + TILE / 2
                for _ in range(3):
                    self.particles.append(Particle(
                        cx, cy, random.uniform(-260, 260), random.uniform(-450, -80),
                        lighten(color, 0.2), random.randint(3, 7), random.randint(450, 850)))

    def update_effects(self, dt):
        self.particles = [p for p in self.particles if p.update(dt)]
        self.floaters = [f for f in self.floaters if f.update(dt)]
        for trail in self.trails:
            trail[4] -= dt
        self.trails = [t for t in self.trails if t[4] > 0]
        self.shake = max(0.0, self.shake - dt * 0.04)

    def _new_menu_piece(self, y):
        return {"kind": random.choice(list(SHAPES)), "x": random.uniform(40, RES[0] - 40),
                "y": y, "speed": random.uniform(0.03, 0.08)}

    # ------------------------------------------------ input
    def handle_events(self):
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                self.quit()
            if event.type != pygame.KEYDOWN:
                continue

            key = event.key
            if key == pygame.K_ESCAPE:
                self.quit()
            elif key == pygame.K_m:
                self.sound.toggle_mute()
            elif self.state == "start":
                if key == pygame.K_RETURN:
                    self.start_game()
            elif self.state == "over":
                if key == pygame.K_RETURN and self.over_timer > 500:
                    self.start_game()
            elif self.state == "pause":
                if key in (pygame.K_p, pygame.K_RETURN):
                    self.state = "play"
                    self.sound.resume()
                elif key == pygame.K_r:
                    self.start_game()
            elif self.state == "play":
                self.handle_play_key(key)

    def handle_play_key(self, key):
        if key == pygame.K_p:
            self.state = "pause"
            self.sound.pause()
            return
        if self.clearing_rows:  # ignore moves while rows are flashing
            return
        if key in (pygame.K_LEFT, pygame.K_RIGHT):
            self.move_dir = -1 if key == pygame.K_LEFT else 1
            self.move_timer = -DAS_DELAY
            if self.try_move(self.move_dir, 0):
                self.player_moved()
        elif key in (pygame.K_UP, pygame.K_x):
            self.rotate()
        elif key == pygame.K_SPACE:
            self.hard_drop()
        elif key == pygame.K_c:
            self.hold()

    # ------------------------------------------------ update
    def update(self, dt):
        self.time += dt
        speed = 1 + (self.level - 1) * 0.15 if self.state in ("play", "pause") else 1
        if self.state != "pause":
            self.stars.update(dt, speed)
            self.update_effects(dt)

        if self.state == "start":
            for piece in self.menu_pieces:
                piece["y"] += piece["speed"] * dt
                if piece["y"] > RES[1] + 60:
                    piece.update(self._new_menu_piece(-150))
        elif self.state == "over":
            self.over_timer += dt
        elif self.state == "play":
            self.update_play(dt)

    def update_play(self, dt):
        self.play_time += dt

        if self.clearing_rows:
            self.clear_timer -= dt
            if self.clear_timer <= 0:
                self.finish_clear()
            return

        keys = pygame.key.get_pressed()

        # auto-repeat while holding Left/Right
        if self.move_dir:
            held = keys[pygame.K_LEFT] if self.move_dir < 0 else keys[pygame.K_RIGHT]
            if held:
                self.move_timer += dt
                while self.move_timer >= DAS_REPEAT:
                    self.move_timer -= DAS_REPEAT
                    if self.try_move(self.move_dir, 0):
                        self.player_moved()
            else:
                self.move_dir = 0

        # on the floor: count down the lock delay instead of falling
        if self.on_ground():
            self.lock_timer += dt
            if self.lock_timer >= LOCK_DELAY:
                self.lock_piece()
            return
        self.lock_timer = 0

        # gravity (time-based, so speed doesn't depend on frame rate)
        soft_drop = keys[pygame.K_DOWN]
        interval = min(SOFT_DROP_INTERVAL, self.fall_interval) if soft_drop else self.fall_interval
        self.fall_timer += dt
        if self.fall_timer >= interval:
            self.fall_timer = 0
            if self.try_move(0, 1) and soft_drop:
                self.score += 1

    # ------------------------------------------------ drawing helpers
    def text(self, msg, font, color, pos, glow=None, alpha=255, anchor="center"):
        f = self.fonts[font]
        image = f.render(str(msg), True, color)
        rect = image.get_rect(**{anchor: (int(pos[0]), int(pos[1]))})
        if glow:
            halo = f.render(str(msg), True, glow)
            halo.set_alpha(55 * alpha // 255)
            for dx, dy in ((-2, 0), (2, 0), (0, -2), (0, 2), (-2, -2), (2, 2), (-2, 2), (2, -2)):
                self.screen.blit(halo, rect.move(dx, dy))
        if alpha < 255:
            image.set_alpha(alpha)
        self.screen.blit(image, rect)
        return rect

    def shade(self, alpha):
        overlay = pygame.Surface(RES, pygame.SRCALPHA)
        overlay.fill((3, 3, 12, alpha))
        self.screen.blit(overlay, (0, 0))

    def draw_card(self, rect):
        self.screen.blit(self.art.card(rect.size), rect)

    def draw_shape(self, kind, center, size, color=None, glow=False):
        """Draw a whole piece centred on a point (for next/hold/menu)."""
        points = SHAPES[kind]
        min_x = min(x for x, _ in points)
        min_y = min(y for _, y in points)
        width = (max(x for x, _ in points) - min_x + 1) * size
        height = (max(y for _, y in points) - min_y + 1) * size
        ox, oy = int(center[0]) - width // 2, int(center[1]) - height // 2
        sprite = self.art.block(color or COLORS[kind], size, glow)
        pad = self.art.block_pad(glow)
        for x, y in points:
            self.screen.blit(sprite, (ox + (x - min_x) * size - pad, oy + (y - min_y) * size - pad))

    # ------------------------------------------------ drawing
    def draw_field(self):
        s = self.shake
        fx = FIELD_POS[0] + (int(random.uniform(-s, s)) if s else 0)
        fy = FIELD_POS[1] + (int(random.uniform(-s, s)) if s else 0)
        accent = self.accent

        border_glow = self.art.glow(FIELD_SIZE, accent, spread=16, strength=200, radius=10, width=4)
        self.screen.blit(border_glow, (fx - 16, fy - 16))
        self.screen.blit(self.art.field_frame(), (fx, fy))
        pygame.draw.rect(self.screen, accent, (fx - 2, fy - 2, FIELD_SIZE[0] + 4, FIELD_SIZE[1] + 4),
                         2, border_radius=6)

        # hard-drop streaks
        for col, top, bottom, color, life in self.trails:
            height = (bottom - top + 1) * TILE
            streak = pygame.Surface((TILE - 12, height), pygame.SRCALPHA)
            streak.fill((*color, int(110 * life / TRAIL_TIME)))
            self.screen.blit(streak, (fx + col * TILE + 5, fy + top * TILE))

        # locked blocks
        flash_on = bool(self.clearing_rows) and (self.clear_timer // 55) % 2 == 0
        dead_rows = min(ROWS, int(self.over_timer / 35)) if self.state == "over" else 0
        for y, row in enumerate(self.field):
            for x, color in enumerate(row):
                if not color:
                    continue
                if y >= ROWS - dead_rows:
                    color = DEAD_BLOCK
                elif flash_on and y in self.clearing_rows:
                    color = (255, 255, 255)
                self.screen.blit(self.art.block(color), (fx + x * TILE, fy + y * TILE))

        # ghost + falling piece
        if self.state in ("play", "pause") and not self.clearing_rows:
            ghost = self.art.ghost(self.piece.color)
            for x, y in self.ghost_cells():
                if y >= 0:
                    self.screen.blit(ghost, (fx + x * TILE, fy + y * TILE))
            sprite = self.art.block(self.piece.color, glow=True)
            pad = self.art.block_pad(True)
            for x, y in self.piece.cells:
                if y >= 0:
                    self.screen.blit(sprite, (fx + x * TILE - pad, fy + y * TILE - pad))

    def draw_effects(self):
        for p in self.particles:
            fade = p.life / p.max_life
            size = max(1, int(p.size * (0.4 + 0.6 * fade)))
            self.screen.fill(scale_color(p.color, fade), (int(p.x), int(p.y), size, size))

        for f in self.floaters:
            if f.age < f.delay:
                continue
            t = (f.age - f.delay) / f.life
            ease = 1 - (1 - t) ** 3
            alpha = 255 if t < 0.6 else int(255 * (1 - (t - 0.6) / 0.4))
            x, y = f.pos
            self.text(f.text, f.font, f.color, (x, y - f.rise * ease), glow=f.color, alpha=max(0, alpha))

    def draw_panel(self):
        accent = self.accent
        self.text("BLOCK", "title", ORANGE, (PANEL_X, 52), glow=ORANGE)
        self.text("BLITZ", "title", PINK, (PANEL_X, 100), glow=PINK)

        # next queue
        self.draw_card(pygame.Rect(495, 135, 230, 285))
        self.text("NEXT", "label", MUTED, (PANEL_X, 160))
        self.draw_shape(self.queue[0], (PANEL_X, 225), 32, glow=True)
        self.draw_shape(self.queue[1], (PANEL_X, 310), 24)
        self.draw_shape(self.queue[2], (PANEL_X, 375), 24)

        # hold
        self.draw_card(pygame.Rect(495, 435, 230, 140))
        self.text("HOLD", "label", MUTED, (PANEL_X, 460))
        if self.hold_kind:
            color = None if self.can_hold else DEAD_BLOCK
            self.draw_shape(self.hold_kind, (PANEL_X, 520), 30, color=color)
        else:
            self.text("PRESS C", "small", scale_color(MUTED, 0.7), (PANEL_X, 520))

        # stats
        self.draw_card(pygame.Rect(495, 590, 230, 330))
        self.text("SCORE", "label", MUTED, (PANEL_X, 618))
        self.text(self.score, "big", TEXT, (PANEL_X, 655), glow=accent)
        self.text("BEST", "label", MUTED, (PANEL_X, 705))
        self.text(max(self.record, self.score), "mid", GOLD, (PANEL_X, 740))
        self.text("LEVEL", "small", MUTED, (553, 790))
        self.text(self.level, "mid", accent, (553, 825), glow=accent)
        self.text("LINES", "small", MUTED, (667, 790))
        self.text(self.lines, "mid", TEXT, (667, 825))
        self.text(format_time(self.play_time), "small", MUTED, (PANEL_X, 880))
        if self.sound.muted:
            self.text("SOUND OFF", "small", PINK, (PANEL_X, 905))

    def draw_start(self):
        cx = RES[0] // 2
        for piece in self.menu_pieces:
            self.draw_shape(piece["kind"], (piece["x"], piece["y"]), 34,
                            color=scale_color(COLORS[piece["kind"]], 0.45))

        bob = math.sin(self.time / 400) * 6
        self.text("BLOCK", "hero", ORANGE, (cx, 180 + bob), glow=ORANGE)
        self.text("BLITZ", "hero", PINK, (cx, 260 + bob), glow=PINK)
        if (self.time // 500) % 2 == 0:
            self.text("PRESS ENTER", "mid", TEXT, (cx, 370), glow=LEVEL_THEMES[0])

        card = pygame.Rect(0, 0, 470, 340)
        card.midtop = (cx, 440)
        self.draw_card(card)
        self.text("CONTROLS", "label", MUTED, (cx, card.y + 30))
        controls = [("LEFT RIGHT", "MOVE"), ("UP  X", "ROTATE"), ("DOWN", "SOFT DROP"),
                    ("SPACE", "HARD DROP"), ("C", "HOLD"), ("P", "PAUSE"),
                    ("M", "SOUND"), ("ESC", "QUIT")]
        for i, (key, action) in enumerate(controls):
            y = card.y + 72 + i * 33
            self.text(key, "small", LEVEL_THEMES[0], (cx - 15, y), anchor="midright")
            self.text(action, "small", TEXT, (cx + 15, y), anchor="midleft")

        self.text(f"BEST  {self.record}", "mid", GOLD, (cx, 830), glow=GOLD)
        if self.sound.muted:
            self.text("SOUND OFF", "small", PINK, (cx, 880))

    def draw_pause(self):
        cx, cy = RES[0] // 2, RES[1] // 2
        self.shade(170)
        card = pygame.Rect(0, 0, 420, 260)
        card.center = (cx, cy)
        self.draw_card(card)
        self.text("PAUSED", "title", TEXT, (cx, cy - 70), glow=self.accent)
        self.text("P   RESUME", "label", TEXT, (cx, cy + 5))
        self.text("R   RESTART", "label", TEXT, (cx, cy + 45))
        self.text("ESC   QUIT", "label", MUTED, (cx, cy + 85))

    def draw_game_over(self):
        if self.over_timer < 700:  # let the board grey out first
            return
        fade = min(1.0, (self.over_timer - 700) / 300)
        a = int(255 * fade)
        cx, cy = RES[0] // 2, RES[1] // 2
        self.shade(int(185 * fade))
        card = pygame.Rect(0, 0, 540, 440)
        card.center = (cx, cy)
        panel = self.art.card(card.size).copy()
        panel.set_alpha(a)
        self.screen.blit(panel, card)

        self.text("GAME OVER", "title", PINK, (cx, cy - 165), glow=PINK, alpha=a)
        self.text("SCORE", "label", MUTED, (cx, cy - 95), alpha=a)
        self.text(self.score, "hero", TEXT, (cx, cy - 45), glow=self.accent, alpha=a)
        if self.new_record and (self.time // 350) % 2 == 0:
            self.text("NEW RECORD!", "mid", GOLD, (cx, cy + 20), glow=GOLD, alpha=a)
        elif not self.new_record:
            self.text(f"BEST  {self.record}", "label", GOLD, (cx, cy + 20), alpha=a)
        self.text(f"LEVEL {self.level}    LINES {self.lines}    {format_time(self.play_time)}",
                  "small", MUTED, (cx, cy + 75), alpha=a)
        self.text("ENTER  PLAY AGAIN", "label", (90, 255, 170), (cx, cy + 135), alpha=a)
        self.text("ESC  QUIT", "label", MUTED, (cx, cy + 175), alpha=a)

    def draw(self):
        self.stars.draw(self.screen)
        if self.state == "start":
            self.draw_start()
        else:
            self.draw_field()
            self.draw_panel()
            self.draw_effects()
            if self.state == "pause":
                self.draw_pause()
            elif self.state == "over":
                self.draw_game_over()
        pygame.display.flip()

    # ------------------------------------------------ main loop
    def run(self):
        while True:
            dt = min(self.clock.tick(FPS), 100)  # cap dt so a window drag doesn't skip rows
            self.handle_events()
            self.update(dt)
            self.draw()

    @staticmethod
    def quit():
        pygame.quit()
        sys.exit()


if __name__ == "__main__":
    Game().run()
