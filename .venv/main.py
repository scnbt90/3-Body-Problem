''' 3-Body-Problem by scnbt90'''
import pygame
import pygame_gui
import math

pygame.init()

# Bildschirmparameter
WIDTH, HEIGHT = 1300, 800
GUI_HEIGHT = 170
SIM_HEIGHT = HEIGHT - GUI_HEIGHT
screen = pygame.display.set_mode((WIDTH, HEIGHT))
pygame.display.set_caption("3-Body Problem mit Kamera und GUI")
clock = pygame.time.Clock()
manager = pygame_gui.UIManager((WIDTH, HEIGHT))
G = 6.67430e-1

# Kamera
class Camera:
    def __init__(self):
        self.offset = pygame.Vector2(0, 0)
        self.drag_start = None
        self.zoom = 1.0

    def apply(self, pos):
        return (pos - self.offset) * self.zoom + pygame.Vector2(0, GUI_HEIGHT)

    def inverse_apply(self, screen_pos):
        return (screen_pos - pygame.Vector2(0, GUI_HEIGHT)) / self.zoom + self.offset

    def handle_input(self, events):
        for event in events:
            if event.type == pygame.MOUSEBUTTONDOWN:
                if event.button == 3:
                    self.drag_start = pygame.Vector2(pygame.mouse.get_pos())
                elif event.button == 4:
                    self.zoom *= 1.1
                elif event.button == 5:
                    self.zoom /= 1.1
            elif event.type == pygame.MOUSEBUTTONUP:
                if event.button == 3:
                    self.drag_start = None
            elif event.type == pygame.MOUSEMOTION:
                if self.drag_start:
                    mouse_pos = pygame.Vector2(pygame.mouse.get_pos())
                    delta = (self.drag_start - mouse_pos) / self.zoom
                    self.offset += delta
                    self.drag_start = mouse_pos

camera = Camera()

# Simulationselemente
bodies = []
paused = False
running = True
simulation_running = False
speed = 1.0
max_bodies = 10
max_path_length = 300

# GUI Elemente
start_button = pygame_gui.elements.UIButton(pygame.Rect((20, 20), (120, 40)), "Start", manager)
pause_button = pygame_gui.elements.UIButton(pygame.Rect((150, 20), (100, 40)), "Pause", manager)
reset_button = pygame_gui.elements.UIButton(pygame.Rect((260, 20), (100, 40)), "Reset", manager)
add_button = pygame_gui.elements.UIButton(pygame.Rect((370, 20), (120, 40)), "Körper +", manager)
remove_button = pygame_gui.elements.UIButton(pygame.Rect((500, 20), (120, 40)), "Körper -", manager)
speed_slider = pygame_gui.elements.UIHorizontalSlider(pygame.Rect((640, 20), (200, 40)), start_value=1.0, value_range=(0.1, 20.0), manager=manager)
speed_label = pygame_gui.elements.UILabel(pygame.Rect((850, 20), (130, 40)), "Speed: 1.0x", manager=manager)
path_slider = pygame_gui.elements.UIHorizontalSlider(pygame.Rect((1000, 20), (180, 40)), start_value=300, value_range=(0, 1000), manager=manager)
path_label = pygame_gui.elements.UILabel(pygame.Rect((1190, 20), (100, 40)), f"Pfad: {max_path_length}", manager=manager)
energy_label = pygame_gui.elements.UILabel(pygame.Rect(WIDTH - 300, 70, 280, 90), "", manager=manager)

inputs = []

def add_body_input():
    if len(inputs) >= max_bodies:
        return
    i = len(inputs)
    base_y = GUI_HEIGHT + i * 110
    label = pygame_gui.elements.UILabel(pygame.Rect(20, base_y - 25, 200, 20), f"Körper {i+1}:", manager)
    entry = {
        'mass': pygame_gui.elements.UITextEntryLine(pygame.Rect(20, base_y, 60, 30), manager),
        'pos_x': pygame_gui.elements.UITextEntryLine(pygame.Rect(90, base_y, 60, 30), manager),
        'pos_y': pygame_gui.elements.UITextEntryLine(pygame.Rect(160, base_y, 60, 30), manager),
        'vel_x': pygame_gui.elements.UITextEntryLine(pygame.Rect(230, base_y, 60, 30), manager),
        'vel_y': pygame_gui.elements.UITextEntryLine(pygame.Rect(300, base_y, 60, 30), manager),
        'color': pygame_gui.elements.UITextEntryLine(pygame.Rect(370, base_y, 90, 30), manager),
        'label': label
    }
    entry['mass'].set_text("1000")
    entry['pos_x'].set_text(str(600 + i * 30))
    entry['pos_y'].set_text(str(400))
    entry['vel_x'].set_text("0")
    entry['vel_y'].set_text(str(1.5 - i * 0.5))
    entry['color'].set_text("255,0,0" if i == 0 else "0,255,0" if i == 1 else "0,0,255")
    inputs.append(entry)

def remove_body_input():
    if len(inputs) <= 1:
        return
    entry = inputs.pop()
    for element in entry.values():
        if hasattr(element, 'kill'):
            element.kill()

class Body:
    def __init__(self, mass, pos, vel, color):
        self.mass = mass
        self.position = pygame.Vector2(pos)
        self.velocity = pygame.Vector2(vel)
        self.color = color
        self.base_radius = max(3, int(mass ** (1/3) * 0.2))
        self.path = []

    def update(self, dt):
        self.position += self.velocity * dt
        self.path.append(self.position.copy())
        if len(self.path) > max_path_length:
            self.path.pop(0)

    def draw(self, screen, camera):
        pos = camera.apply(self.position)
        radius = max(1, int(self.base_radius * camera.zoom))
        pygame.draw.circle(screen, self.color, (int(pos.x), int(pos.y)), radius)
        if len(self.path) > 2:
            points = [camera.apply(p) for p in self.path]
            pygame.draw.lines(screen, self.color, False, [(int(p.x), int(p.y)) for p in points], 1)

def compute_gravity(b1, b2):
    distance = b2.position - b1.position
    r2 = max(distance.length_squared(), 100)
    force_mag = G * b1.mass * b2.mass / r2
    return distance.normalize() * force_mag

def calculate_energy_and_momentum():
    T, U = 0, 0
    P = pygame.Vector2(0, 0)
    for i, b1 in enumerate(bodies):
        T += 0.5 * b1.mass * b1.velocity.length_squared()
        P += b1.velocity * b1.mass
        for j, b2 in enumerate(bodies):
            if i < j:
                r = (b1.position - b2.position).length()
                U -= G * b1.mass * b2.mass / r
    return T, U, T + U, P

def build_bodies():
    global bodies
    bodies = []
    for entry in inputs:
        try:
            mass = float(entry['mass'].get_text())
            pos = (float(entry['pos_x'].get_text()), float(entry['pos_y'].get_text()))
            vel = (float(entry['vel_x'].get_text()), float(entry['vel_y'].get_text()))
            color = tuple(map(int, entry['color'].get_text().split(',')))
            bodies.append(Body(mass, pos, vel, color))
        except:
            continue

for _ in range(3):
    add_body_input()

while running:
    dt = clock.tick(60) / 1000.0
    events = pygame.event.get()
    for event in events:
        if event.type == pygame.QUIT:
            running = False
        if event.type == pygame.USEREVENT:
            if event.user_type == pygame_gui.UI_BUTTON_PRESSED:
                if event.ui_element == start_button:
                    build_bodies()
                    simulation_running = True
                    paused = False
                elif event.ui_element == pause_button:
                    paused = not paused
                elif event.ui_element == reset_button:
                    simulation_running = False
                    bodies = []
                    camera.offset = pygame.Vector2(0, 0)
                    camera.zoom = 1.0
                elif event.ui_element == add_button:
                    add_body_input()
                elif event.ui_element == remove_button:
                    remove_body_input()
        manager.process_events(event)

    camera.handle_input(events)
    speed = speed_slider.get_current_value()
    speed_label.set_text(f"Speed: {speed:.1f}x")
    max_path_length = int(path_slider.get_current_value())
    path_label.set_text(f"Pfad: {max_path_length}")

    if simulation_running and not paused:
        scaled_dt = dt * speed
        forces = [pygame.Vector2(0, 0) for _ in bodies]
        for i, b1 in enumerate(bodies):
            for j, b2 in enumerate(bodies):
                if i != j:
                    forces[i] += compute_gravity(b1, b2)
        for i, body in enumerate(bodies):
            acc = forces[i] / body.mass
            body.velocity += acc * scaled_dt
            body.update(scaled_dt)
        T, U, E, P = calculate_energy_and_momentum()
        energy_label.set_text(f"T: {T:.1f} | U: {U:.1f}\nE: {E:.1f}\nImpuls: {P.x:.1f}, {P.y:.1f}")

    screen.fill((15, 15, 15))
    for body in bodies:
        body.draw(screen, camera)
    pygame.draw.rect(screen, (30, 30, 30), (0, 0, WIDTH, GUI_HEIGHT))
    manager.update(dt)
    manager.draw_ui(screen)
    pygame.display.flip()

pygame.quit()