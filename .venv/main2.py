#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
3-Body-Sim mit Erweiterungen und schwarzem Loch
Author: Tobias Bayhan (scnbt90)

Single-window pygame-GUI:
- Top-Bar: Start, Pause, Reset, Körper +/- , Speed & Pfad-Slider,
           BH-Masse, Gravitation ±, Merge/Repel, Bounds-Modus,
           ZoomBounds, Orbit-Tool
- Links: Panel für
    * Orbit-Defaults (Masse & ω) für neue Orbits
    * Orbit-Liste (pro Orbit eigene Zeile mit m, ω, Track, Info, Delete)
    * Körper-Liste (mit Track + Info und Infozeile direkt darunter)
- Rechts: klar begrenzter Simulationsbereich
- Footer: "3-Body-Sim - scnbt90 - License: <TEXT>"

Bounds:
- HARD   : reflektierende Wände
- SOFT   : keine Wände
- PORTAL : toroidal (rechts raus → links rein); Pfade haben keine „Brücke“

ZoomBounds:
- OFF: bei HARD/PORTAL ist Zoom + Pan gesperrt
- ON : Wände folgen dem Viewport (in Weltkoordinaten skaliert)

Orbit-Body:
- Kinematisch auf Ellipse; pro Orbit editierbar: m & ω (live)
- Beeinflusst normale Bodies gravitationell, wird selbst nicht beeinflusst
"""

from __future__ import annotations

import math
import pygame
import pygame_gui

# ---------------------------------------------------------------------------
# Grundkonfiguration
# ---------------------------------------------------------------------------

pygame.init()

BASE_WIDTH, BASE_HEIGHT = 1300, 800

TOP_BAR_HEIGHT   = 120
FOOTER_HEIGHT    = 26
LEFT_PANEL_WIDTH = 430
SIM_MARGIN       = 10

MAX_ORBIT_ROWS      = 5
ORBIT_ROW_HEIGHT    = 62   # kompakter
ORBIT_PANEL_START_Y = TOP_BAR_HEIGHT + 75

BODY_ROW_HEIGHT     = 96
BODY_PANEL_START_Y  = ORBIT_PANEL_START_Y + MAX_ORBIT_ROWS * ORBIT_ROW_HEIGHT + 20

COLOR_BG         = (10, 12, 16)
COLOR_TOP_BAR    = (18, 24, 32)
COLOR_LEFT_PANEL = (16, 22, 24)
COLOR_SIM_BG     = (5, 8, 10)
COLOR_SIM_BORDER = (60, 80, 100)
COLOR_FOOTER_BG  = (12, 18, 16)
COLOR_FOOTER_FG  = (160, 220, 180)

LICENSE_TEXT = "MIT (example)"
G = 6.67430e-1

WIDTH, HEIGHT = BASE_WIDTH, BASE_HEIGHT
screen = pygame.display.set_mode((WIDTH, HEIGHT), pygame.RESIZABLE)
pygame.display.set_caption("3-Body-Sim — scnbt90")
clock = pygame.time.Clock()
manager = pygame_gui.UIManager((WIDTH, HEIGHT))
font_footer = pygame.font.SysFont("Consolas", 14)

SIM_LEFT = SIM_TOP = SIM_RIGHT = SIM_BOTTOM = SIM_WIDTH = SIM_HEIGHT = 0

# ---------------------------------------------------------------------------
# Kamera
# ---------------------------------------------------------------------------

class Camera:
    def __init__(self):
        self.offset = pygame.Vector2(0, 0)
        self.drag_start: pygame.Vector2 | None = None
        self.zoom = 1.0

    def apply(self, pos: pygame.Vector2) -> pygame.Vector2:
        return (pos - self.offset) * self.zoom + pygame.Vector2(SIM_LEFT, SIM_TOP)

    def inverse_apply(self, screen_pos: pygame.Vector2) -> pygame.Vector2:
        return (screen_pos - pygame.Vector2(SIM_LEFT, SIM_TOP)) / max(self.zoom, 1e-6) + self.offset

    def reset_view(self):
        self.offset.update(0, 0)
        self.zoom = 1.0
        self.drag_start = None

    def handle_input(self, events, boundary_mode: str, zoom_bounds_follow: bool):
        allow_zoom_pan = (boundary_mode == "soft") or zoom_bounds_follow

        for event in events:
            if event.type == pygame.MOUSEBUTTONDOWN:
                if event.button == 3 and allow_zoom_pan:
                    self.drag_start = pygame.Vector2(pygame.mouse.get_pos())
                elif event.button == 4 and allow_zoom_pan:
                    self.zoom *= 1.1
                elif event.button == 5 and allow_zoom_pan:
                    self.zoom /= 1.1
                    if self.zoom < 0.1:
                        self.zoom = 0.1
            elif event.type == pygame.MOUSEBUTTONUP:
                if event.button == 3:
                    self.drag_start = None
            elif event.type == pygame.MOUSEMOTION:
                if self.drag_start is not None and allow_zoom_pan:
                    mouse_pos = pygame.Vector2(pygame.mouse.get_pos())
                    delta = (self.drag_start - mouse_pos) / max(self.zoom, 1e-6)
                    self.offset += delta
                    self.drag_start = mouse_pos

camera = Camera()

# ---------------------------------------------------------------------------
# Simulationselemente
# ---------------------------------------------------------------------------

bodies: list["Body"] = []
black_holes: list["BlackHole"] = []
orbit_bodies: list["OrbitBody"] = []
black_hole_mass = 5000.0

paused = False
simulation_running = False

speed = 1.0
max_bodies = 7
max_path_length = 300
invert_gravity = False
use_merge_logic = False
use_soft_repulsion = False

boundary_mode = "hard"
zoom_bounds_follow = False

tracked_target: tuple[str, int] | None = None

inputs: list[dict] = []       # Körper-UI
orbit_inputs: list[dict] = [] # Orbit-UI

class Body:
    def __init__(self, mass, pos, vel, color):
        self.mass = mass
        self.position = pygame.Vector2(pos)
        self.velocity = pygame.Vector2(vel)
        self.color = color
        self.base_radius = max(3, int(mass ** (1 / 3) * 0.2))
        self.path: list[pygame.Vector2] = []

    def update(self, dt: float):
        self.position += self.velocity * dt
        self._enforce_bounds()
        self.path.append(self.position.copy())
        if len(self.path) > max_path_length:
            self.path.pop(0)

    def _enforce_bounds(self):
        global boundary_mode, SIM_WIDTH, SIM_HEIGHT, zoom_bounds_follow, camera

        if boundary_mode == "soft":
            return

        if boundary_mode in ("hard", "portal") and zoom_bounds_follow:
            max_x = SIM_WIDTH / max(camera.zoom, 1e-6)
            max_y = SIM_HEIGHT / max(camera.zoom, 1e-6)
        else:
            max_x = SIM_WIDTH
            max_y = SIM_HEIGHT

        if boundary_mode == "portal":
            if max_x > 0:
                if self.position.x < 0:
                    self.position.x += max_x
                elif self.position.x > max_x:
                    self.position.x -= max_x
            if max_y > 0:
                if self.position.y < 0:
                    self.position.y += max_y
                elif self.position.y > max_y:
                    self.position.y -= max_y
            return

        if self.position.x < 0:
            self.position.x = 0
            self.velocity.x *= -1
        elif self.position.x > max_x:
            self.position.x = max_x
            self.velocity.x *= -1

        if self.position.y < 0:
            self.position.y = 0
            self.velocity.y *= -1
        elif self.position.y > max_y:
            self.position.y = max_y
            self.velocity.y *= -1

    def draw(self, surf: pygame.Surface, cam: Camera):
        pos = cam.apply(self.position)
        radius = max(1, int(self.base_radius * cam.zoom))
        pygame.draw.circle(surf, self.color, (int(pos.x), int(pos.y)), radius)

        if len(self.path) > 2:
            jump_threshold = max(SIM_WIDTH, SIM_HEIGHT) * 0.5
            segments: list[list[pygame.Vector2]] = []
            current_seg = [self.path[0]]

            for p in self.path[1:]:
                if (p - current_seg[-1]).length() > jump_threshold:
                    if len(current_seg) > 1:
                        segments.append(current_seg)
                    current_seg = [p]
                else:
                    current_seg.append(p)
            if len(current_seg) > 1:
                segments.append(current_seg)

            for seg in segments:
                pts = [cam.apply(p) for p in seg]
                pygame.draw.lines(
                    surf,
                    self.color,
                    False,
                    [(int(p.x), int(p.y)) for p in pts],
                    1,
                )

class BlackHole:
    def __init__(self, pos, mass):
        self.position = pygame.Vector2(pos)
        self.mass = mass

    def draw(self, surf: pygame.Surface, cam: Camera):
        pos = cam.apply(self.position)
        radius = max(5, int(math.sqrt(self.mass) * 0.1 * cam.zoom))
        pygame.draw.circle(surf, (0, 0, 0), (int(pos.x), int(pos.y)), radius)
        pygame.draw.circle(surf, (200, 200, 255), (int(pos.x), int(pos.y)), radius, 2)

class OrbitBody:
    def __init__(self, center, radii, omega, color=(220, 220, 0), mass=1000.0):
        self.center = pygame.Vector2(center)
        self.radii = pygame.Vector2(radii)
        self.omega = omega
        self.theta = 0.0
        self.color = color
        self.mass = mass

    @property
    def position(self) -> pygame.Vector2:
        return pygame.Vector2(
            self.center.x + self.radii.x * math.cos(self.theta),
            self.center.y + self.radii.y * math.sin(self.theta),
        )

    def update(self, dt: float, speed_factor: float):
        self.theta += self.omega * dt * speed_factor

    def draw(self, surf: pygame.Surface, cam: Camera):
        num_segments = 64
        pts = []
        for i in range(num_segments + 1):
            t = 2 * math.pi * i / num_segments
            p = pygame.Vector2(
                self.center.x + self.radii.x * math.cos(t),
                self.center.y + self.radii.y * math.sin(t),
            )
            pts.append(cam.apply(p))

        pygame.draw.lines(
            surf,
            (120, 120, 80),
            False,
            [(int(p.x), int(p.y)) for p in pts],
            1,
        )

        pos = cam.apply(self.position)
        pygame.draw.circle(surf, self.color, (int(pos.x), int(pos.y)), 5)

# ---------------------------------------------------------------------------
# Physik
# ---------------------------------------------------------------------------

def apply_blackhole_gravity(dt: float, speed: float):
    for bh in black_holes:
        for body in bodies:
            distance = bh.position - body.position
            r2 = max(distance.length_squared(), 100.0)
            force_mag = G * bh.mass * body.mass / r2
            force = distance.normalize() * force_mag
            acc = force / body.mass
            body.velocity += acc * dt * speed

def compute_gravity(b1: Body, b2: Body) -> pygame.Vector2:
    distance = b2.position - b1.position
    r2 = max(distance.length_squared(), 100.0)
    force_mag = G * b1.mass * b2.mass / r2
    sign = -1 if invert_gravity else 1
    return distance.normalize() * force_mag * sign

def compute_gravity_from_orbit(b: Body, ob: OrbitBody) -> pygame.Vector2:
    distance = ob.position - b.position
    r2 = max(distance.length_squared(), 100.0)
    force_mag = G * b.mass * ob.mass / r2
    sign = -1 if invert_gravity else 1
    return distance.normalize() * force_mag * sign

def calculate_energy_and_momentum_per_body():
    n = len(bodies)
    kin = [0.0] * n
    pot = [0.0] * n
    P = pygame.Vector2(0, 0)

    for i, b in enumerate(bodies):
        kin[i] = 0.5 * b.mass * b.velocity.length_squared()
        P += b.velocity * b.mass

    for i in range(n):
        for j in range(i + 1, n):
            r = (bodies[i].position - bodies[j].position).length()
            if r > 0:
                U = -G * bodies[i].mass * bodies[j].mass / r
                pot[i] += 0.5 * U
                pot[j] += 0.5 * U

    for i, b in enumerate(bodies):
        for ob in orbit_bodies:
            r = (b.position - ob.position).length()
            if r > 0:
                U = -G * b.mass * ob.mass / r
                pot[i] += U

    T = sum(kin)
    U = sum(pot)
    E = T + U
    return T, U, E, P, kin, pot

def apply_soft_repulsion():
    for i in range(len(bodies)):
        for j in range(i + 1, len(bodies)):
            b1, b2 = bodies[i], bodies[j]
            delta = b2.position - b1.position
            dist = delta.length()
            if dist <= 0:
                continue
            min_dist = b1.base_radius + b2.base_radius
            if dist < min_dist:
                repulsion_strength = 500.0
                force = delta.normalize() * repulsion_strength * (min_dist - dist)
                b1.velocity -= force / b1.mass
                b2.velocity += force / b2.mass

def handle_merging_collisions():
    global bodies
    merged = set()
    new_bodies: list[Body] = []

    for i in range(len(bodies)):
        if i in merged:
            continue
        b1 = bodies[i]
        for j in range(i + 1, len(bodies)):
            if j in merged:
                continue
            b2 = bodies[j]
            dist = (b1.position - b2.position).length()
            min_dist = b1.base_radius + b2.base_radius
            if dist < min_dist:
                total_mass = b1.mass + b2.mass
                new_velocity = (b1.velocity * b1.mass + b2.velocity * b2.mass) / total_mass
                new_position = (b1.position * b1.mass + b2.position * b2.mass) / total_mass
                new_color = [(c1 + c2) // 2 for c1, c2 in zip(b1.color, b2.color)]
                new_body = Body(total_mass, new_position, new_velocity, new_color)
                new_bodies.append(new_body)
                merged.add(i)
                merged.add(j)
                break
        if i not in merged:
            new_bodies.append(b1)

    bodies = new_bodies

# ---------------------------------------------------------------------------
# Orbit-Tool & Orbit-UI
# ---------------------------------------------------------------------------

orbit_tool_active = False
orbit_tmp_center: pygame.Vector2 | None = None

ORBIT_DEFAULT_MASS = 1000.0
ORBIT_DEFAULT_OMEGA = 1.0  # rad/s

def create_orbit_ui_for(ob: OrbitBody):
    if len(orbit_inputs) >= MAX_ORBIT_ROWS:
        return

    i = len(orbit_inputs)
    base_y = ORBIT_PANEL_START_Y + i * ORBIT_ROW_HEIGHT

    label = pygame_gui.elements.UILabel(
        pygame.Rect(20, base_y - 18, LEFT_PANEL_WIDTH - 40, 18),
        f"Orbit {i + 1}:",
        manager,
    )
    mass_label = pygame_gui.elements.UILabel(
        pygame.Rect(20, base_y, 18, 22),
        "m:",
        manager,
    )
    mass_entry = pygame_gui.elements.UITextEntryLine(
        pygame.Rect(38, base_y, 70, 22),
        manager,
    )
    mass_entry.set_text(str(ob.mass))

    omega_label = pygame_gui.elements.UILabel(
        pygame.Rect(116, base_y, 18, 22),
        "ω:",
        manager,
    )
    omega_entry = pygame_gui.elements.UITextEntryLine(
        pygame.Rect(134, base_y, 60, 22),
        manager,
    )
    omega_entry.set_text(f"{ob.omega:.3f}")

    track_btn = pygame_gui.elements.UIButton(
        pygame.Rect(205, base_y - 2, 65, 24),
        "Track",
        manager,
    )
    del_btn = pygame_gui.elements.UIButton(
        pygame.Rect(275, base_y - 2, 50, 24),
        "Del",
        manager,
    )
    info_btn = pygame_gui.elements.UIButton(
        pygame.Rect(330, base_y - 2, 60, 24),
        "Info",
        manager,
    )
    info_label = pygame_gui.elements.UILabel(
        pygame.Rect(20, base_y + 24, 370, 18),
        "",
        manager,
    )

    orbit_inputs.append(
        {
            "label": label,
            "mass_label": mass_label,
            "mass": mass_entry,
            "omega_label": omega_label,
            "omega": omega_entry,
            "track_btn": track_btn,
            "del_btn": del_btn,
            "info_btn": info_btn,
            "info_label": info_label,
            "info_on": False,
        }
    )

def clear_all_orbit_ui():
    for entry in orbit_inputs:
        for v in entry.values():
            if hasattr(v, "kill"):
                v.kill()
    orbit_inputs.clear()

def handle_mouse_tools(events, orbit_mass_entry, orbit_omega_entry):
    global black_hole_mass, orbit_tool_active, orbit_tmp_center

    for event in events:
        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            mouse_pos = pygame.mouse.get_pos()
            if not (SIM_LEFT <= mouse_pos[0] <= SIM_RIGHT and
                    SIM_TOP <= mouse_pos[1] <= SIM_BOTTOM):
                continue
            sim_pos = camera.inverse_apply(pygame.Vector2(mouse_pos))

            if orbit_tool_active:
                if orbit_tmp_center is None:
                    orbit_tmp_center = sim_pos
                else:
                    delta = sim_pos - orbit_tmp_center
                    a = abs(delta.x)
                    b = abs(delta.y)
                    if a < 20 and b < 20:
                        a = b = 80.0
                    elif a < 20:
                        a = 20.0
                    elif b < 20:
                        b = 20.0

                    try:
                        m = float(orbit_mass_entry.get_text())
                    except Exception:
                        m = ORBIT_DEFAULT_MASS
                    try:
                        omega = float(orbit_omega_entry.get_text())
                    except Exception:
                        omega = ORBIT_DEFAULT_OMEGA
                    if omega == 0:
                        omega = ORBIT_DEFAULT_OMEGA

                    ob = OrbitBody(
                        center=orbit_tmp_center,
                        radii=(a, b),
                        omega=omega,
                        color=(220, 220, 0),
                        mass=m,
                    )
                    orbit_bodies.append(ob)
                    create_orbit_ui_for(ob)

                    orbit_tmp_center = None
                    orbit_tool_active = False
                    orbit_button.set_text("Orbit-Tool")
            else:
                removed = False
                for bh in list(black_holes):
                    if (sim_pos - bh.position).length() < math.sqrt(bh.mass) * 0.1:
                        black_holes.remove(bh)
                        removed = True
                        break
                if not removed:
                    black_holes.append(BlackHole(sim_pos, black_hole_mass))

# ---------------------------------------------------------------------------
# Körper-UI
# ---------------------------------------------------------------------------

def add_body_input():
    if len(inputs) >= max_bodies:
        return
    i = len(inputs)
    base_y = BODY_PANEL_START_Y + i * BODY_ROW_HEIGHT

    # Label-Zeile
    label = pygame_gui.elements.UILabel(
        pygame.Rect(20, base_y, LEFT_PANEL_WIDTH - 40, 18),
        f"Körper {i + 1}:",
        manager,
    )

    fields_y = base_y + 24      # Zeile mit m, x, y, vx, vy
    color_y  = base_y + 52      # Zeile mit Farbe + Track/Info
    info_y   = base_y + 76      # Info-Zeile

    entry = {
        "mass": pygame_gui.elements.UITextEntryLine(
            pygame.Rect(20,  fields_y, 60, 26), manager
        ),
        "pos_x": pygame_gui.elements.UITextEntryLine(
            pygame.Rect(86,  fields_y, 60, 26), manager
        ),
        "pos_y": pygame_gui.elements.UITextEntryLine(
            pygame.Rect(152, fields_y, 60, 26), manager
        ),
        "vel_x": pygame_gui.elements.UITextEntryLine(
            pygame.Rect(218, fields_y, 60, 26), manager
        ),
        "vel_y": pygame_gui.elements.UITextEntryLine(
            pygame.Rect(284, fields_y, 60, 26), manager
        ),
        "color": pygame_gui.elements.UITextEntryLine(
            pygame.Rect(20, color_y, 150, 24), manager
        ),
        "label": label,
    }

    track_btn = pygame_gui.elements.UIButton(
        pygame.Rect(180, color_y, 70, 24),
        "Track",
        manager,
    )
    info_btn = pygame_gui.elements.UIButton(
        pygame.Rect(255, color_y, 60, 24),
        "Info",
        manager,
    )
    info_label = pygame_gui.elements.UILabel(
        pygame.Rect(20, info_y, 360, 18),
        "",
        manager,
    )

    entry["track_btn"] = track_btn
    entry["info_btn"] = info_btn
    entry["info_label"] = info_label
    entry["info_on"] = False

    # Default-Werte
    entry["mass"].set_text("1000")
    entry["pos_x"].set_text(str(SIM_WIDTH / 2 + i * 30))
    entry["pos_y"].set_text(str(SIM_HEIGHT / 2))
    entry["vel_x"].set_text("0")
    entry["vel_y"].set_text(str(1.5 - i * 0.5))
    entry["color"].set_text(
        "255,0,0" if i == 0 else "0,255,0" if i == 1 else "0,0,255"
    )

    inputs.append(entry)

def remove_body_input():
    if len(inputs) <= 1:
        return
    entry = inputs.pop()
    for element in entry.values():
        if hasattr(element, "kill"):
            element.kill()

def build_bodies():
    global bodies
    bodies = []
    for entry in inputs:
        try:
            mass = float(entry["mass"].get_text())
            pos = (
                float(entry["pos_x"].get_text()),
                float(entry["pos_y"].get_text()),
            )
            vel = (
                float(entry["vel_x"].get_text()),
                float(entry["vel_y"].get_text()),
            )
            color = tuple(map(int, entry["color"].get_text().split(",")))
            bodies.append(Body(mass, pos, vel, color))
        except Exception:
            continue

# ---------------------------------------------------------------------------
# Top-Bar & Orbit-Defaults-UI
# ---------------------------------------------------------------------------

ROW1_Y = 15
ROW2_Y = 65

start_button  = pygame_gui.elements.UIButton(pygame.Rect(20, ROW1_Y, 100, 32), "Start",  manager)
pause_button  = pygame_gui.elements.UIButton(pygame.Rect(130, ROW1_Y, 100, 32), "Pause",  manager)
reset_button  = pygame_gui.elements.UIButton(pygame.Rect(240, ROW1_Y, 100, 32), "Reset",  manager)

add_button    = pygame_gui.elements.UIButton(pygame.Rect(20, ROW2_Y, 100, 28), "Körper +", manager)
remove_button = pygame_gui.elements.UIButton(pygame.Rect(130, ROW2_Y, 100, 28), "Körper -", manager)

speed_label = pygame_gui.elements.UILabel(
    pygame.Rect(0, 0, 120, 26), "Speed: 1.0x", manager
)
speed_slider = pygame_gui.elements.UIHorizontalSlider(
    pygame.Rect(0, 0, 230, 26),
    start_value=1.0,
    value_range=(0.1, 20.0),
    manager=manager,
)

blackhole_label = pygame_gui.elements.UILabel(
    pygame.Rect(0, 0, 150, 26), "BH-Masse: 5000", manager
)
blackhole_slider = pygame_gui.elements.UIHorizontalSlider(
    pygame.Rect(0, 0, 230, 26),
    start_value=5000,
    value_range=(1000, 1000000),
    manager=manager,
)

path_label = pygame_gui.elements.UILabel(
    pygame.Rect(0, 0, 120, 26), "Pfad: 300", manager
)
path_slider = pygame_gui.elements.UIHorizontalSlider(
    pygame.Rect(0, 0, 230, 26),
    start_value=300,
    value_range=(0, 1000),
    manager=manager,
)

gravity_button = pygame_gui.elements.UIButton(
    pygame.Rect(0, 0, 120, 28), "Gravitation ±", manager
)
merge_toggle = pygame_gui.elements.UIButton(
    pygame.Rect(0, 0, 100, 28), "Merge: OFF", manager
)
repel_toggle = pygame_gui.elements.UIButton(
    pygame.Rect(0, 0, 100, 28), "Repel: OFF", manager
)

bounds_button = pygame_gui.elements.UIButton(
    pygame.Rect(0, 0, 120, 28), "Bounds: HARD", manager
)
orbit_button = pygame_gui.elements.UIButton(
    pygame.Rect(0, 0, 100, 28), "Orbit-Tool", manager
)
zoom_button = pygame_gui.elements.UIButton(
    pygame.Rect(0, 0, 150, 28), "ZoomBounds: OFF", manager
)

# Orbit-Defaults (kompakter Block)
orbit_cfg_label = pygame_gui.elements.UILabel(
    pygame.Rect(20, TOP_BAR_HEIGHT + 8, 130, 20),
    "Orbit-Defaults:",
    manager,
)
orbit_mass_label = pygame_gui.elements.UILabel(
    pygame.Rect(20, TOP_BAR_HEIGHT + 30, 18, 22),
    "m:",
    manager,
)
orbit_mass_entry = pygame_gui.elements.UITextEntryLine(
    pygame.Rect(38, TOP_BAR_HEIGHT + 30, 70, 22),
    manager,
)
orbit_mass_entry.set_text(str(ORBIT_DEFAULT_MASS))

orbit_omega_label = pygame_gui.elements.UILabel(
    pygame.Rect(118, TOP_BAR_HEIGHT + 30, 18, 22),
    "ω:",
    manager,
)
orbit_omega_entry = pygame_gui.elements.UITextEntryLine(
    pygame.Rect(136, TOP_BAR_HEIGHT + 30, 60, 22),
    manager,
)
orbit_omega_entry.set_text(f"{ORBIT_DEFAULT_OMEGA:.2f}")

# ---------------------------------------------------------------------------
# Layout
# ---------------------------------------------------------------------------

def recompute_layout():
    global SIM_LEFT, SIM_TOP, SIM_RIGHT, SIM_BOTTOM, SIM_WIDTH, SIM_HEIGHT
    SIM_LEFT   = LEFT_PANEL_WIDTH + SIM_MARGIN
    SIM_TOP    = TOP_BAR_HEIGHT + SIM_MARGIN
    SIM_RIGHT  = WIDTH - SIM_MARGIN
    SIM_BOTTOM = HEIGHT - FOOTER_HEIGHT - SIM_MARGIN
    SIM_WIDTH  = max(10, SIM_RIGHT - SIM_LEFT)
    SIM_HEIGHT = max(10, SIM_BOTTOM - SIM_TOP)

def layout_topbar():
    speed_label.set_relative_position((LEFT_PANEL_WIDTH + 30, ROW1_Y))
    speed_label.set_dimensions((120, 26))
    speed_slider.set_relative_position((LEFT_PANEL_WIDTH + 160, ROW1_Y))
    speed_slider.set_dimensions((230, 26))

    blackhole_label.set_relative_position((LEFT_PANEL_WIDTH + 405, ROW1_Y))
    blackhole_label.set_dimensions((150, 26))
    blackhole_slider.set_relative_position((LEFT_PANEL_WIDTH + 560, ROW1_Y))
    blackhole_slider.set_dimensions((230, 26))

    path_label.set_relative_position((LEFT_PANEL_WIDTH + 30, ROW2_Y))
    path_label.set_dimensions((120, 26))
    path_slider.set_relative_position((LEFT_PANEL_WIDTH + 160, ROW2_Y))
    path_slider.set_dimensions((230, 26))

    gravity_button.set_relative_position((LEFT_PANEL_WIDTH + 405, ROW2_Y))
    gravity_button.set_dimensions((120, 28))

    merge_toggle.set_relative_position((LEFT_PANEL_WIDTH + 530, ROW2_Y))
    merge_toggle.set_dimensions((100, 28))

    repel_toggle.set_relative_position((LEFT_PANEL_WIDTH + 635, ROW2_Y))
    repel_toggle.set_dimensions((100, 28))

    bounds_button.set_relative_position((LEFT_PANEL_WIDTH + 740, ROW2_Y))
    bounds_button.set_dimensions((120, 28))

    orbit_button.set_relative_position((LEFT_PANEL_WIDTH + 865, ROW2_Y))
    orbit_button.set_dimensions((100, 28))

    zoom_button.set_relative_position((LEFT_PANEL_WIDTH + 970, ROW2_Y))
    zoom_button.set_dimensions((150, 28))

def relayout_all():
    recompute_layout()
    layout_topbar()

relayout_all()

for _ in range(3):
    add_body_input()

# ---------------------------------------------------------------------------
# Bounds / Zoom / Tracking
# ---------------------------------------------------------------------------

def apply_zoom_constraints():
    global boundary_mode, zoom_bounds_follow
    if boundary_mode == "soft":
        return
    if zoom_bounds_follow:
        camera.offset.update(0, 0)
    else:
        camera.reset_view()

def cycle_boundary_mode():
    global boundary_mode
    if boundary_mode == "hard":
        boundary_mode = "soft"
    elif boundary_mode == "soft":
        boundary_mode = "portal"
    else:
        boundary_mode = "hard"
    bounds_button.set_text(f"Bounds: {boundary_mode.upper()}")
    apply_zoom_constraints()

def toggle_zoom_bounds():
    global zoom_bounds_follow
    zoom_bounds_follow = not zoom_bounds_follow
    zoom_button.set_text(f"ZoomBounds: {'ON' if zoom_bounds_follow else 'OFF'}")
    apply_zoom_constraints()

def toggle_orbit_tool():
    global orbit_tool_active, orbit_tmp_center
    orbit_tool_active = not orbit_tool_active
    orbit_tmp_center = None
    orbit_button.set_text("Orbit-Tool*" if orbit_tool_active else "Orbit-Tool")

def update_tracking_camera():
    global tracked_target
    if tracked_target is None:
        return
    kind, idx = tracked_target
    target_pos: pygame.Vector2 | None = None

    if kind == "body" and 0 <= idx < len(bodies):
        target_pos = bodies[idx].position
    elif kind == "orbit" and 0 <= idx < len(orbit_bodies):
        target_pos = orbit_bodies[idx].position

    if target_pos is None:
        tracked_target = None
        return

    center = pygame.Vector2(SIM_WIDTH / 2, SIM_HEIGHT / 2)
    camera.offset = target_pos - center / max(camera.zoom, 1e-6)

# ---------------------------------------------------------------------------
# Hauptloop
# ---------------------------------------------------------------------------

running = True

while running:
    dt = clock.tick(60) / 1000.0
    events = pygame.event.get()

    for event in events:
        if event.type == pygame.QUIT:
            running = False

        if event.type == pygame.VIDEORESIZE:
            WIDTH, HEIGHT = max(BASE_WIDTH, event.w), max(BASE_HEIGHT, event.h)
            screen = pygame.display.set_mode((WIDTH, HEIGHT), pygame.RESIZABLE)
            manager.set_window_resolution((WIDTH, HEIGHT))
            relayout_all()

        manager.process_events(event)

        if event.type == pygame_gui.UI_BUTTON_PRESSED:
            if event.ui_element == start_button:
                build_bodies()
                simulation_running = True
                paused = False
            elif event.ui_element == pause_button:
                paused = not paused
            elif event.ui_element == reset_button:
                simulation_running = False
                bodies = []
                black_holes = []
                orbit_bodies = []
                clear_all_orbit_ui()
                camera.reset_view()
                tracked_target = None
            elif event.ui_element == add_button:
                add_body_input()
            elif event.ui_element == remove_button:
                remove_body_input()
            elif event.ui_element == gravity_button:
                invert_gravity = not invert_gravity
            elif event.ui_element == merge_toggle:
                use_merge_logic = not use_merge_logic
                merge_toggle.set_text(f"Merge: {'ON' if use_merge_logic else 'OFF'}")
            elif event.ui_element == repel_toggle:
                use_soft_repulsion = not use_soft_repulsion
                repel_toggle.set_text(f"Repel: {'ON' if use_soft_repulsion else 'OFF'}")
            elif event.ui_element == bounds_button:
                cycle_boundary_mode()
            elif event.ui_element == zoom_button:
                toggle_zoom_bounds()
            elif event.ui_element == orbit_button:
                toggle_orbit_tool()
            else:
                handled = False
                # Körper-Buttons (Track / Info)
                for idx, entry in enumerate(inputs):
                    if event.ui_element == entry.get("track_btn"):
                        if tracked_target == ("body", idx):
                            tracked_target = None
                        else:
                            tracked_target = ("body", idx)
                            if boundary_mode in ("hard", "portal") and not zoom_bounds_follow:
                                zoom_bounds_follow = True
                                zoom_button.set_text("ZoomBounds: ON")
                                apply_zoom_constraints()
                        handled = True
                        break
                    if event.ui_element == entry.get("info_btn"):
                        entry["info_on"] = not entry.get("info_on", False)
                        if not entry["info_on"]:
                            entry["info_label"].set_text("")
                        handled = True
                        break
                if handled:
                    continue
                # Orbit-Buttons (Track / Info / Del)
                for idx, entry in enumerate(orbit_inputs):
                    if event.ui_element == entry.get("track_btn"):
                        if tracked_target == ("orbit", idx):
                            tracked_target = None
                        else:
                            tracked_target = ("orbit", idx)
                            if boundary_mode in ("hard", "portal") and not zoom_bounds_follow:
                                zoom_bounds_follow = True
                                zoom_button.set_text("ZoomBounds: ON")
                                apply_zoom_constraints()
                        handled = True
                        break
                    if event.ui_element == entry.get("info_btn"):
                        entry["info_on"] = not entry.get("info_on", False)
                        if not entry["info_on"]:
                            entry["info_label"].set_text("")
                        handled = True
                        break
                    if event.ui_element == entry.get("del_btn"):
                        if 0 <= idx < len(orbit_bodies):
                            orbit_bodies.pop(idx)
                        clear_all_orbit_ui()
                        for ob in orbit_bodies:
                            create_orbit_ui_for(ob)
                        tracked_target = None
                        handled = True
                        break

    handle_mouse_tools(events, orbit_mass_entry, orbit_omega_entry)
    camera.handle_input(events, boundary_mode, zoom_bounds_follow)

    speed = speed_slider.get_current_value()
    speed_label.set_text(f"Speed: {speed:.1f}x")

    max_path_length = int(path_slider.get_current_value())
    path_label.set_text(f"Pfad: {max_path_length}")

    black_hole_mass = blackhole_slider.get_current_value()
    blackhole_label.set_text(f"BH-Masse: {black_hole_mass:.0f}")

    # Orbit-Parameter live aus UI
    for i, ob in enumerate(orbit_bodies):
        if i < len(orbit_inputs):
            o_ui = orbit_inputs[i]
            try:
                m = float(o_ui["mass"].get_text())
                ob.mass = m
            except Exception:
                pass
            try:
                omega = float(o_ui["omega"].get_text())
                if omega != 0:
                    ob.omega = omega
            except Exception:
                pass

    if simulation_running and not paused and len(bodies) > 0:
        scaled_dt = dt * speed
        forces = [pygame.Vector2(0, 0) for _ in bodies]

        for i, b1 in enumerate(bodies):
            for j, b2 in enumerate(bodies):
                if i != j:
                    forces[i] += compute_gravity(b1, b2)
            for ob in orbit_bodies:
                forces[i] += compute_gravity_from_orbit(b1, ob)

        for i, body in enumerate(bodies):
            acc = forces[i] / body.mass
            body.velocity += acc * scaled_dt
            body.update(scaled_dt)

        if use_soft_repulsion:
            apply_soft_repulsion()
        if use_merge_logic:
            handle_merging_collisions()

        apply_blackhole_gravity(dt, speed)

        for ob in orbit_bodies:
            ob.update(dt, speed)

    # Energies + Info-Labels
    if len(bodies) > 0:
        T, U, E, P, kin, pot = calculate_energy_and_momentum_per_body()
        for i, entry in enumerate(inputs):
            if entry.get("info_on") and i < len(bodies) and i < len(kin):
                vmag = bodies[i].velocity.length()
                Ei = kin[i] + pot[i]
                entry["info_label"].set_text(f"v={vmag:.2f}, E={Ei:.1f}")
            elif not entry.get("info_on"):
                entry["info_label"].set_text("")
        for i, ob in enumerate(orbit_bodies):
            if i < len(orbit_inputs):
                o_ui = orbit_inputs[i]
                if o_ui.get("info_on"):
                    a, b = ob.radii
                    o_ui["info_label"].set_text(
                        f"m={ob.mass:.0f}, ω={ob.omega:.2f}, a={a:.0f}, b={b:.0f}"
                    )
                else:
                    o_ui["info_label"].set_text("")
    else:
        for entry in inputs:
            entry["info_label"].set_text("")
        for o_ui in orbit_inputs:
            o_ui["info_label"].set_text("")

    update_tracking_camera()

    # Zeichnen
    screen.fill(COLOR_BG)

    pygame.draw.rect(screen, COLOR_TOP_BAR, (0, 0, WIDTH, TOP_BAR_HEIGHT))
    pygame.draw.rect(
        screen,
        COLOR_LEFT_PANEL,
        (0, TOP_BAR_HEIGHT, LEFT_PANEL_WIDTH, HEIGHT - TOP_BAR_HEIGHT - FOOTER_HEIGHT),
    )

    sim_rect = pygame.Rect(SIM_LEFT, SIM_TOP, SIM_WIDTH, SIM_HEIGHT)
    pygame.draw.rect(screen, COLOR_SIM_BG, sim_rect)
    pygame.draw.rect(screen, COLOR_SIM_BORDER, sim_rect, 2)

    screen.set_clip(sim_rect)

    # --- Orbit-Vorschau, wenn erster Punkt gesetzt ist ---
    if orbit_tool_active and orbit_tmp_center is not None:
        mouse_px = pygame.mouse.get_pos()
        if SIM_LEFT <= mouse_px[0] <= SIM_RIGHT and SIM_TOP <= mouse_px[1] <= SIM_BOTTOM:
            mouse_world = camera.inverse_apply(pygame.Vector2(mouse_px))
            delta = mouse_world - orbit_tmp_center

            a = abs(delta.x)
            b = abs(delta.y)

            # gleiche Minimalgrößen wie bei der finalen Erzeugung
            if a < 20 and b < 20:
                a = b = 80.0
            elif a < 20:
                a = 20.0
            elif b < 20:
                b = 20.0

            num_segments = 64
            pts = []
            for i in range(num_segments + 1):
                t = 2 * math.pi * i / num_segments
                p = pygame.Vector2(
                    orbit_tmp_center.x + a * math.cos(t),
                    orbit_tmp_center.y + b * math.sin(t),
                )
                pts.append(camera.apply(p))

            # leichte, gelbliche Vorschau-Linie
            pygame.draw.lines(
                screen,
                (160, 160, 90),
                False,
                [(int(p.x), int(p.y)) for p in pts],
                1,
            )
            # Center-Punkt markieren
            center_px = camera.apply(orbit_tmp_center)
            pygame.draw.circle(
                screen,
                (220, 220, 120),
                (int(center_px.x), int(center_px.y)),
                4,
            )

    # --- existierende Orbits / Bodies / BH zeichnen ---
    for ob in orbit_bodies:
        ob.draw(screen, camera)
    for body in bodies:
        body.draw(screen, camera)
    for bh in black_holes:
        bh.draw(screen, camera)

    screen.set_clip(None)

    manager.update(dt)
    manager.draw_ui(screen)

    pygame.draw.rect(
        screen,
        COLOR_FOOTER_BG,
        (0, HEIGHT - FOOTER_HEIGHT, WIDTH, FOOTER_HEIGHT),
    )
    footer_text = f"3-Body-Sim - scnbt90 - License: {LICENSE_TEXT}"
    text_surf = font_footer.render(footer_text, True, COLOR_FOOTER_FG)
    text_rect = text_surf.get_rect()
    text_rect.centery = HEIGHT - FOOTER_HEIGHT // 2
    text_rect.x = 10
    screen.blit(text_surf, text_rect)

    pygame.display.set_caption(f"3-Body-Sim | Zoom: {camera.zoom:.2f}")
    pygame.display.flip()

pygame.quit()
