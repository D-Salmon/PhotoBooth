#!/usr/bin/env python3
"""Photobooth tactile : aperçu, décompte, planche de photos, impression.

Menu de configuration : maintenir le doigt ~2 s en haut à droite de l'écran d'accueil.
Lancer en test sur un ordinateur :  python3 photobooth.py --windowed --camera fake --no-web
"""
import argparse
import math
import os
import queue
import shutil
import sys
import threading
import time

import pygame
from PIL import Image, ImageOps

import composer as C
import hardware as HW

LANCZOS = C.LANCZOS

BG = (22, 22, 30)
PANEL = (38, 38, 52)
PANEL2 = (58, 58, 78)
ACCENT = (212, 175, 55)
WHITE = (245, 245, 245)
GREY = (150, 150, 168)
GREEN = (60, 160, 95)
RED = (190, 60, 60)
DARK = (25, 18, 10)

TABS = ["Fond", "Photos", "Texte", "Stockage", "Système"]
ADMIN_TIMEOUT = 600      # déconnexion admin après 10 min sans action d'administration
GALLERY_IDLE = 120       # retour à l'accueil après 2 min d'inactivité dans la galerie
PRINT_MODES = [("auto", "Impression automatique (annulable)"), ("off", "Sans impression")]
READY_TIMEOUT = 120      # retour à l'accueil si personne ne touche l'écran entre deux photos
REVIEW_TIMEOUT = 30      # photo conservée automatiquement si personne ne répond

KB_ROWS = [
    [("1", 1), ("2", 1), ("3", 1), ("4", 1), ("5", 1), ("6", 1), ("7", 1), ("8", 1), ("9", 1), ("0", 1), ("EFF", 1.6)],
    [(c, 1) for c in "azertyuiop"],
    [(c, 1) for c in "qsdfghjklm"],
    [("MAJ", 1.6)] + [(c, 1) for c in "wxcvbn'-&"],
    [(c, 1) for c in "éèêàâçùôîï"],
    [("ESPACE", 3.2)] + [(c, 1) for c in ",.!?"] + [("VIDER", 1.6), ("ANNULER", 1.8), ("OK", 1.4)],
]


def to_surface(img):
    img = img.convert("RGB")
    return pygame.image.fromstring(img.tobytes(), img.size, "RGB")


class App:
    def __init__(self, args):
        pygame.init()
        pygame.display.set_caption("Photobooth")
        if args.windowed:
            w, h = map(int, args.size.lower().split("x"))
            self.screen = pygame.display.set_mode((w, h))
        else:
            self.screen = pygame.display.set_mode((0, 0), pygame.FULLSCREEN)
        pygame.mouse.set_visible(bool(args.windowed))
        self.windowed = args.windowed
        self.W, self.H = self.screen.get_size()
        self.s = self.H / 800
        self.clock = pygame.time.Clock()
        self.running = True

        self.ui_font_path = pygame.font.match_font("dejavusans,liberationsans,freesans,arial")
        self.fonts = {}

        self.cfg = C.load_config()
        C.ensure_default_backgrounds()
        if self.cfg["background"] not in C.list_backgrounds():
            names = C.list_backgrounds()
            self.cfg["background"] = names[0] if names else ""
        self.camera = HW.make_camera(args.camera)

        self.mode = "home"
        self.phase = ""
        self.ready_t0 = 0
        self.hits = []
        self.hits_mode = None
        self.reg = True
        self.cam_surf = None
        self.cam_frame = None
        self.shots = []
        self.shot_surf = None
        self.pending = None
        self.review_t0 = 0.0
        self.t0 = 0.0
        self.gear_t0 = None
        self.toast = ("", 0)
        self.guide_cache = None

        self.result_img = None
        self.result_surf = None
        self.result_path = None
        self.result_t0 = 0.0
        self.print_state = None      # pending | printing | done | error | cancelled | noprinter | saved
        self.print_msg = ""
        self.state_t0 = 0.0
        self.print_deadline = 0.0
        self.printer_ok = None       # None = pas encore vérifié
        self.printer_detail = "vérification…"
        self.printer_t = 0.0
        self.printer_busy = False

        self.tab = "Fond"
        self.bg_page = 0
        self.kb = None
        self.picker = None
        self.picker_page = 0
        self.dirty = True
        self.preview_surf = None
        self.placeholders = [C.make_placeholder(i) for i in range(3)]
        self.thumbs = {}
        self.quit_armed = False
        self.admin = False
        self.admin_last = 0.0
        self.gal_files = []
        self.gal_idx = 0
        self.gal_confirm = False
        self.gal_cache = {}
        self.swipe = None
        self.usb_mount = None
        self.usb_free = None
        self.storage_t = 0.0
        self.sync_running = False
        self.eject_running = False
        self.ui_queue = queue.Queue()
        self.sync_again = False
        self.refresh_gallery()
        self.pin = None
        self.pin_fails = 0
        self.pin_lock_until = 0.0
        self.last_touch = time.time()

        self.web_queue = queue.Queue()
        self.web = None if args.no_web else HW.start_web_upload(
            lambda n: self.web_queue.put(n), lambda pin: C.check_pin(self.cfg, pin))
        self.ip = HW.local_ip()
        self.printers = HW.list_printers()

    # ------------------------------------------------------------ utilitaires
    def S(self, v):
        return int(v * self.s)

    def font(self, size):
        size = max(8, int(size))
        f = self.fonts.get(size)
        if f is None:
            f = pygame.font.Font(self.ui_font_path, size)
            self.fonts[size] = f
        return f

    def text(self, s, size, color=WHITE, max_w=None, **anchor):
        size = size * self.s
        f = self.font(size)
        if max_w:
            while f.size(s)[0] > max_w and size > 10:
                size -= 1
                f = self.font(size)
        surf = f.render(s, True, color)
        r = surf.get_rect(**anchor)
        self.screen.blit(surf, r)
        return r

    def button(self, rect, label, cb=None, active=False, size=24, fill=None, fg=WHITE, enabled=True):
        rect = pygame.Rect(rect)
        col = fill or (ACCENT if active else PANEL2)
        if not enabled:
            col = (44, 44, 54)
        pygame.draw.rect(self.screen, col, rect, border_radius=self.S(12))
        color = DARK if (active and fill is None) else fg
        self.text(label, size, color if enabled else GREY, max_w=rect.w - self.S(14), center=rect.center)
        if cb and enabled and self.reg:
            self.hits.append((rect, cb))
        return rect

    def hit(self, rect, cb):
        if self.reg:
            self.hits.append((pygame.Rect(rect), cb))

    def click(self, pos):
        if self.hits_mode != self.mode:      # boutons d'un écran précédent : on ignore
            return False
        for rect, cb in reversed(self.hits):
            if rect.collidepoint(pos):
                cb()
                return True
        return False

    def save(self):
        self.dirty = True
        try:
            C.save_config(self.cfg)
        except OSError as ex:
            self.show_toast(f"Réglages non enregistrés : {ex}", 10)
            return False
        return True

    def show_toast(self, msg, secs=4):
        self.toast = (msg, time.time() + secs)

    # ------------------------------------------------------------ événements
    def gear_rect(self):
        return pygame.Rect(self.W - self.S(120), 0, self.S(120), self.S(120))

    def handle(self, e):
        if e.type == pygame.QUIT:
            self.running = False
        elif e.type == pygame.MOUSEBUTTONDOWN and e.button == 1:
            self.on_down(e.pos)
        elif e.type == pygame.MOUSEBUTTONUP and e.button == 1:
            self.on_up(e.pos)
        elif e.type == pygame.KEYDOWN:
            self.on_key(e)

    def on_down(self, pos):
        now = time.time()
        self.last_touch = now
        if self.admin and self.mode in ("config", "pin"):
            self.admin_last = now
        if self.mode == "home":
            if self.click(pos):
                return
            if self.gear_rect().collidepoint(pos):
                self.gear_t0 = now
            else:
                self.start_session()
        elif self.mode == "gallery":
            self.swipe = pos
            self.click(pos)
        elif self.mode == "countdown":
            if self.phase == "review":
                self.click(pos)
            elif self.phase == "ready" and time.time() - self.ready_t0 > 0.6:
                self.start_next_shot()      # n'importe où sur l'écran, comme à l'accueil
        elif self.mode in ("result", "config", "pin"):
            self.click(pos)

    def on_up(self, pos):
        self.gear_t0 = None
        if self.mode == "gallery" and self.swipe and not self.gal_confirm and self.gal_files:
            dx, dy = pos[0] - self.swipe[0], pos[1] - self.swipe[1]
            if abs(dx) > self.S(120) and abs(dx) > 2 * abs(dy):
                self.gal_step(1 if dx < 0 else -1)
        self.swipe = None

    def on_key(self, e):
        if self.kb is not None:
            if e.key == pygame.K_RETURN:
                self.kb_ok()
            elif e.key == pygame.K_ESCAPE:
                self.kb = None
            elif e.key == pygame.K_BACKSPACE:
                self.kb["text"] = self.kb["text"][:-1]
            elif e.unicode and e.unicode.isprintable():
                self.kb_type(e.unicode)
            return
        if e.key == pygame.K_F1 and self.mode == "home":
            self.request_config()
        elif e.key == pygame.K_ESCAPE and self.windowed:
            if self.mode == "config":
                self.close_config()
            else:
                self.running = False

    # ------------------------------------------------------------ session photo
    def start_session(self):
        self.shots = []
        self.mode = "countdown"
        self.phase = "count"
        self.t0 = time.time()

    def grab_camera(self):
        try:
            frame = self.camera.frame()
        except Exception:
            frame = None
        if frame is None:
            return
        import numpy as np
        self.cam_frame = np.ascontiguousarray(frame)
        h, w = self.cam_frame.shape[:2]
        self.cam_surf = pygame.image.frombuffer(self.cam_frame, (w, h), "RGB")

    def keep_shot(self):
        if self.mode != "countdown" or self.phase != "review" or self.pending is None:
            return
        self.shots.append(self.pending)
        self.pending = None
        if len(self.shots) < self.cfg["num_photos"]:
            self.phase, self.ready_t0 = "ready", time.time()
        else:
            self.phase = "compose"

    def start_next_shot(self):
        if self.mode != "countdown" or self.phase != "ready":
            return
        self.phase, self.t0 = "count", time.time()

    def retake_shot(self):
        if self.mode != "countdown" or self.phase != "review":
            return
        self.pending = None
        self.phase, self.t0 = "count", time.time()

    def shot_display(self, shot):
        a = C.photo_aspect(self.cfg["num_photos"])
        hh = int(self.H * 0.58)
        img = ImageOps.fit(shot.convert("RGB"), (int(hh * a), hh), LANCZOS, centering=(0.5, 0.4))
        return to_surface(img)

    def finish_session(self):
        img = C.compose(self.cfg, self.shots)
        self.result_img = img
        self.result_path = None
        save_error = None
        try:
            self.result_path = C.save_outputs(img, self.shots)
        except OSError as ex:
            save_error = str(ex)
        self.refresh_gallery()
        if not save_error and self.cfg["storage"] == "usb":
            self.start_sync()
        maxw, maxh = self.W - self.S(40), self.H - self.S(190)
        k = min(maxw / img.width, maxh / img.height)
        self.result_surf = to_surface(img.resize((int(img.width * k), int(img.height * k)), LANCZOS))
        now = time.time()
        self.mode = "result"
        self.result_t0 = now
        self.print_msg = ""
        if save_error is not None:
            self.print_msg = "Enregistrement incomplet : " + save_error
            self.set_pstate("saveerror")
        elif self.cfg["print_mode"] != "auto":
            self.set_pstate("saved")
        elif self.printer_ok:
            self.print_deadline = now + self.cfg["print_delay"]
            self.set_pstate("pending")
        else:
            self.set_pstate("noprinter")

    def set_pstate(self, state):
        self.print_state = state
        self.state_t0 = time.time()

    def cancel_print(self):
        if self.print_state == "pending":
            self.set_pstate("cancelled")

    def do_print(self):
        if self.print_state == "printing":
            return
        self.set_pstate("printing")
        self.print_msg = "Impression en cours…"
        path, cfg = self.result_path, self.cfg

        def job():
            ok, msg = HW.print_file(path, cfg["printer"], cfg["copies"], cfg["print_options"])
            self.print_msg = ("Impression lancée ! Votre photo sort dans environ une minute."
                              if ok else f"Erreur d'impression : {msg}")
            self.set_pstate("done" if ok else "error")

        threading.Thread(target=job, daemon=True).start()

    def go_home(self):
        self.mode = "home"
        self.phase = ""
        self.print_state = None
        self.pending = None

    # ------------------------------------------------------------ imprimante connectée ?
    def poll_printer(self, now, force=False):
        if self.printer_busy or (not force and now - self.printer_t < 10):
            return
        self.printer_t = now
        self.printer_busy = True
        name, host = self.cfg["printer"], self.cfg.get("printer_host", "")

        def job():
            try:
                self.printer_ok, self.printer_detail = HW.printer_status(name, host)
            finally:
                self.printer_busy = False

        threading.Thread(target=job, daemon=True).start()

    # ------------------------------------------------------------ mise à jour
    def update(self):
        now = time.time()
        while not self.ui_queue.empty():
            self.ui_queue.get_nowait()()
        while True:
            try:
                name = self.web_queue.get_nowait()
            except queue.Empty:
                break
            self.cfg["background"] = name
            self.save()
            self.show_toast("Nouveau fond reçu depuis le téléphone ✔")

        if self.admin and now - self.admin_last > ADMIN_TIMEOUT:
            self.logout(auto=True)
        self.poll_storage(now)
        self.poll_printer(now)

        if self.mode in ("home", "countdown") and self.phase != "flash":
            self.grab_camera()

        if self.mode == "home":
            if self.gear_t0 and now - self.gear_t0 > 1.5:
                self.request_config()
        elif self.mode == "countdown":
            n = self.cfg["num_photos"]
            if self.phase == "count":
                if now - self.t0 >= self.cfg["countdown"]:
                    self.phase = "flash"
            elif self.phase == "flash":
                try:
                    shot = self.camera.capture()
                except Exception as ex:
                    print("Erreur de capture :", ex)
                    self.show_toast("Erreur caméra, réessayez")
                    self.go_home()
                    return
                self.pending = shot
                self.shot_surf = self.shot_display(shot)
                self.phase = "review"
                self.review_t0 = now
            elif self.phase == "review":
                if now - self.review_t0 > REVIEW_TIMEOUT:
                    self.keep_shot()
            elif self.phase == "ready":
                if now - max(self.last_touch, self.ready_t0) > READY_TIMEOUT:
                    self.go_home()
            elif self.phase == "compose":
                self.finish_session()
        elif self.mode == "pin":
            if self.pin and self.pin.get("submit_at") and now >= self.pin["submit_at"]:
                self.pin_submit()
            if now - self.last_touch > 30:
                self.pin_cancel()
        elif self.mode == "config":
            if now - self.last_touch > 120:          # le menu se referme (l'admin reste connecté)
                self.close_config()
        elif self.mode == "gallery":
            if now - self.last_touch > GALLERY_IDLE:
                self.close_gallery()
        elif self.mode == "result":
            st = self.print_state
            if st == "saveerror":
                return  # Conserver les clichés en mémoire pour réessayer.
            if st == "pending" and now >= self.print_deadline:
                self.do_print()
            elif st in ("done", "error") and now - self.state_t0 > 9:
                self.go_home()
            elif st in ("cancelled", "noprinter", "saved") and now - self.state_t0 > 7:
                self.go_home()
            elif st == "printing" and now - self.state_t0 > 60:
                self.go_home()
            elif now - self.result_t0 > 120:
                self.go_home()

    # ------------------------------------------------------------ dessin : caméra
    def draw_camera(self, guide=True):
        if self.cam_surf is None:
            self.screen.fill(BG)
            return
        w, h = self.cam_surf.get_size()
        sc = max(self.W / w, self.H / h)
        tw, th = int(w * sc) + 1, int(h * sc) + 1
        surf = pygame.transform.flip(pygame.transform.scale(self.cam_surf, (tw, th)), True, False)
        ox, oy = (self.W - tw) // 2, (self.H - th) // 2
        self.screen.blit(surf, (ox, oy))
        if not guide:
            return
        a = C.photo_aspect(self.cfg["num_photos"])
        if a <= tw / th:
            ch, cw = th, th * a
        else:
            cw, ch = tw, tw / a
        cx = ox + (tw - cw) / 2
        cy = oy + (th - ch) * 0.4
        crop = pygame.Rect(int(cx), int(cy), int(cw), int(ch)).clip(self.screen.get_rect())
        key = (crop.x, crop.y, crop.w, crop.h)
        if self.guide_cache is None or self.guide_cache[0] != key:
            dim = pygame.Surface((self.W, self.H), pygame.SRCALPHA)
            dim.fill((0, 0, 0, 175))
            dim.fill((0, 0, 0, 0), crop)
            self.guide_cache = (key, dim)
        self.screen.blit(self.guide_cache[1], (0, 0))
        pygame.draw.rect(self.screen, (255, 255, 255), crop, max(4, self.S(5)), border_radius=6)

    def outlined(self, s, size, center, color=WHITE):
        for dx, dy in ((-3, -3), (3, -3), (-3, 3), (3, 3), (0, 4)):
            self.text(s, size, (0, 0, 0), center=(center[0] + dx, center[1] + dy))
        self.text(s, size, color, center=center)

    def draw_gear(self):
        """Icône de réglages sobre, lisible sur tous les fonds."""
        S = self.S
        cx, cy = self.W - S(55), S(55)
        panel = pygame.Surface((S(76), S(76)), pygame.SRCALPHA)
        pygame.draw.circle(panel, (15, 15, 22, 180), (S(38), S(38)), S(36))
        self.screen.blit(panel, panel.get_rect(center=(cx, cy)))

        col = WHITE
        left, right = cx - S(21), cx + S(21)
        rows = ((cy - S(15), cx - S(8)), (cy, cx + S(10)), (cy + S(15), cx - S(2)))
        for yy, knob_x in rows:
            pygame.draw.line(self.screen, col, (left, yy), (right, yy), max(2, S(3)))
            pygame.draw.circle(self.screen, (15, 15, 22), (knob_x, yy), S(7))
            pygame.draw.circle(self.screen, ACCENT, (knob_x, yy), S(6))
        if self.gear_t0:
            frac = min(1.0, (time.time() - self.gear_t0) / 1.5)
            rect = pygame.Rect(0, 0, self.S(84), self.S(84))
            rect.center = (cx, cy)
            pygame.draw.arc(self.screen, ACCENT, rect, math.pi / 2, math.pi / 2 + 2 * math.pi * frac, 6)

    # ------------------------------------------------------------ écrans : accueil / décompte / résultat
    def draw_home(self):
        self.draw_camera()
        title = self.cfg["lines"][0]["text"]
        if title.strip():
            self.outlined(title, 40, (self.W // 2, self.S(60)))
        pulse = 1 + 0.03 * math.sin(time.time() * 3)
        rect = pygame.Rect(0, 0, int(self.S(560) * pulse), int(self.S(110) * pulse))
        rect.midbottom = (self.W // 2, self.H - self.S(36))
        pygame.draw.rect(self.screen, ACCENT, rect, border_radius=rect.h // 2)
        self.text("Touchez pour commencer", 34, DARK, center=rect.center)
        self.outlined("Placez-vous dans le cadre blanc", 28, (self.W // 2, rect.top - self.S(30)))
        self.draw_gear()
        self.draw_usb_badge()
        label = f"Galerie ({len(self.gal_files)})" if self.gal_files else "Galerie"
        self.button((self.W - self.S(240), self.H - self.S(100), self.S(210), self.S(70)), label,
                    self.open_gallery, fill=(30, 30, 42), size=24)
        if self.admin:
            self.outlined("Mode administrateur", 22, (self.S(150), self.H - self.S(140)), ACCENT)
            self.button((self.S(20), self.H - self.S(100), self.S(260), self.S(70)), "Déconnecter",
                        self.logout, fill=(200, 120, 30), size=26)

    def draw_countdown(self):
        n = self.cfg["num_photos"]
        idx = min(len(self.shots), n - 1) + 1
        if self.phase == "flash":
            self.screen.fill((255, 255, 255))
            return
        if self.phase == "compose":
            self.screen.fill(BG)
            self.text("Un instant…", 46, WHITE, center=(self.W // 2, self.H // 2))
            return
        if self.phase == "review":
            self.screen.fill(BG)
            S = self.S
            self.text(f"Photo {len(self.shots) + 1}/{n}", 40, ACCENT, center=(self.W // 2, S(40)))
            r = self.shot_surf.get_rect(midtop=(self.W // 2, S(82)))
            pygame.draw.rect(self.screen, WHITE, r.inflate(S(20), S(20)), border_radius=S(6))
            self.screen.blit(self.shot_surf, r)
            bw, bh = S(380), S(100)
            by = self.H - S(150)
            self.button((self.W // 2 - bw - S(15), by, bw, bh), "Conserver", self.keep_shot, size=36, fill=GREEN)
            self.button((self.W // 2 + S(15), by, bw, bh), "Reprendre", self.retake_shot, size=36)
            return
        if self.phase == "ready":
            self.draw_camera()
            self.outlined(f"Photo {idx}/{n}", 40, (self.W // 2, self.S(55)))
            pulse = 1 + 0.03 * math.sin(time.time() * 3)
            rect = pygame.Rect(0, 0, int(self.S(700) * pulse), int(self.S(110) * pulse))
            rect.midbottom = (self.W // 2, self.H - self.S(36))
            pygame.draw.rect(self.screen, ACCENT, rect, border_radius=rect.h // 2)
            self.text(f"Touchez pour la photo {idx}/{n}", 34, DARK, center=rect.center)
            self.outlined("Placez-vous dans le cadre blanc", 28, (self.W // 2, rect.top - self.S(30)))
            return
        self.draw_camera()
        remaining = max(1, math.ceil(self.cfg["countdown"] - (time.time() - self.t0)))
        self.outlined(str(remaining), 340, (self.W // 2, self.H // 2))
        self.outlined(f"Photo {idx}/{n}", 40, (self.W // 2, self.S(55)))
        self.outlined("Restez dans le cadre et regardez la caméra !", 32, (self.W // 2, self.H - self.S(55)))

    def draw_result(self):
        S = self.S
        self.screen.fill(BG)
        r = self.result_surf.get_rect(midtop=(self.W // 2, S(16)))
        self.screen.blit(self.result_surf, r)
        by = self.H - S(150)
        st, mid = self.print_state, self.W // 2
        if st == "saveerror":
            self.text(self.print_msg, 24, RED, max_w=self.W - S(40), center=(mid, by + S(18)))
            self.button((mid - S(240), by + S(62), S(480), S(80)),
                        "Réessayer l’enregistrement", self.finish_session, size=26)
            return
        if st == "pending":
            remaining = max(1, math.ceil(self.print_deadline - time.time()))
            self.text(f"Impression dans {remaining} s…", 34, ACCENT, center=(mid, by + S(18)))
            bw = S(520)
            self.button((mid - bw // 2, by + S(48), bw, S(90)), "Ne pas imprimer", self.cancel_print, size=34, fill=RED)
            return
        msgs = {
            "printing": ("Impression en cours…", ACCENT),
            "done": (self.print_msg, ACCENT),
            "error": (self.print_msg, (255, 120, 120)),
            "cancelled": ("Impression annulée. Votre photo est enregistrée.", WHITE),
            "noprinter": ("Photo enregistrée. Imprimante non connectée : pas d'impression.", (255, 190, 90)),
            "saved": ("Photo enregistrée.", WHITE),
        }
        msg, col = msgs.get(st, ("", WHITE))
        self.text(msg, 30, col, max_w=self.W - S(60), center=(mid, by + S(30)))
        if st in ("cancelled", "noprinter", "saved", "done", "error"):
            bw = S(360)
            self.button((mid - bw // 2, by + S(62), bw, S(80)), "Terminer", self.go_home, size=30)

    # ------------------------------------------------------------ code d'accès
    def request_config(self):
        """Ouvre le menu ; demande le code sauf si l'administrateur est déjà connecté."""
        self.gear_t0 = None
        if self.admin:
            self.admin_last = time.time()
            self.open_config()
        else:
            self.login("config")

    def login(self, back="config"):
        """Écran de saisie du code (ou de création au tout premier accès)."""
        self.gear_t0 = None
        self.pin = {"purpose": "unlock" if C.has_pin(self.cfg) else "create", "back": back,
                    "digits": "", "first": None, "msg": "", "submit_at": None}
        self.mode = "pin"
        self.last_touch = time.time()

    def after_login(self, back):
        self.admin = True
        self.admin_last = time.time()
        if back == "gallery":
            self.mode = "gallery"
            self.last_touch = time.time()
            self.show_toast("Mode administrateur")
        else:
            self.open_config()

    def logout(self, auto=False):
        """Retour au mode utilisateur."""
        was_config = self.mode in ("config", "pin")
        if self.mode == "config":
            self.save()
        self.admin = False
        self.kb = None
        self.picker = None
        self.pin = None
        self.gal_confirm = False
        if was_config:
            self.mode = "home"
        self.show_toast("Déconnexion automatique : mode utilisateur" if auto else "Mode utilisateur")

    def change_pin(self):
        self.pin = {"purpose": "change", "back": "config", "digits": "", "first": None, "msg": "", "submit_at": None}
        self.mode = "pin"

    def pin_cancel(self):
        back = self.pin.get("back", "home") if self.pin else "home"
        purpose = self.pin["purpose"] if self.pin else ""
        self.pin = None
        if purpose == "change":
            self.mode = "config"
        elif back == "gallery":
            self.mode = "gallery"
            self.last_touch = time.time()
        else:
            self.go_home()

    def pin_key(self, tok):
        p, now = self.pin, time.time()
        if tok == "ANNULER":
            self.pin_cancel()
            return
        if p["purpose"] == "unlock" and now < self.pin_lock_until:
            return
        if tok == "EFF":
            p["digits"] = p["digits"][:-1]
            p["submit_at"] = None
        elif tok in "0123456789" and len(tok) == 1 and len(p["digits"]) < 4:
            p["digits"] += tok
            p["msg"] = ""
            if len(p["digits"]) == 4:
                p["submit_at"] = now + 0.15

    def pin_submit(self):
        p = self.pin
        d, p["digits"], p["submit_at"] = p["digits"], "", None
        if len(d) != 4 or any(c not in "0123456789" for c in d):
            p["msg"] = "Saisissez exactement 4 chiffres"
            return
        if p["purpose"] == "unlock":
            if C.check_pin(self.cfg, d):
                back = p.get("back", "config")
                self.pin, self.pin_fails = None, 0
                self.after_login(back)
            else:
                self.pin_fails += 1
                p["msg"] = "Code incorrect"
                if self.pin_fails >= 3:
                    self.pin_fails = 0
                    self.pin_lock_until = time.time() + 30
            return
        if p["first"] is None:
            p["first"], p["msg"] = d, ""
        elif d == p["first"]:
            old_salt, old_hash = self.cfg["pin_salt"], self.cfg["pin_hash"]
            C.set_pin(self.cfg, d)
            if not self.save():
                self.cfg["pin_salt"], self.cfg["pin_hash"] = old_salt, old_hash
                p["first"] = None
                p["msg"] = "Code non enregistré. Réessayez."
                return
            purpose, back, self.pin = p["purpose"], p.get("back", "config"), None
            if purpose == "create":
                self.after_login(back)
            else:
                self.mode, self.tab = "config", "Système"
            self.show_toast("Code enregistré ✔")
        else:
            p["first"], p["msg"] = None, "Les deux codes sont différents, recommencez"

    def draw_pin(self):
        S, p = self.S, self.pin
        self.screen.fill(BG)
        if p["purpose"] == "unlock":
            title = "Code d'accès"
        elif p["first"] is None:
            title = "Choisissez un code à 4 chiffres"
        else:
            title = "Confirmez le code"
        self.text(title, 38, WHITE, center=(self.W // 2, S(70)))
        if p["purpose"] == "create":
            self.text("Ce code protège le menu de réglages.", 22, GREY, center=(self.W // 2, S(112)))
        for i in range(4):
            c = (self.W // 2 + int((i - 1.5) * S(74)), S(170))
            pygame.draw.circle(self.screen, ACCENT if i < len(p["digits"]) else PANEL2, c, S(22), 0 if i < len(p["digits"]) else 3)
        remaining = self.pin_lock_until - time.time()
        if p["purpose"] == "unlock" and remaining > 0:
            self.text(f"Trop d'essais. Patientez {int(remaining) + 1} s", 26, RED, center=(self.W // 2, S(228)))
        elif p["msg"]:
            self.text(p["msg"], 26, RED, center=(self.W // 2, S(228)))
        kw, kh, gap = S(150), S(84), S(14)
        y0 = S(262)
        for r, row in enumerate([["1", "2", "3"], ["4", "5", "6"], ["7", "8", "9"], ["ANNULER", "0", "EFF"]]):
            for c, tok in enumerate(row):
                x = self.W // 2 - (3 * kw + 2 * gap) // 2 + c * (kw + gap)
                lab = {"ANNULER": "Annuler", "EFF": "Effacer"}.get(tok, tok)
                self.button((x, y0 + r * (kh + gap), kw, kh), lab, lambda t=tok: self.pin_key(t),
                            size=36 if len(lab) == 1 else 22, fill=RED if tok == "ANNULER" else None)

    # ------------------------------------------------------------ menu de configuration
    def open_config(self):
        self.mode = "config"
        self.tab = "Fond"
        self.printers = HW.list_printers()
        self.ip = HW.local_ip()
        self.dirty = True

    def close_config(self):
        self.save()
        self.kb = None
        self.picker = None
        self.mode = "home"
        self.gear_t0 = None

    def thumb(self, key, loader, size):
        k = (key, size)
        if k not in self.thumbs:
            img = loader()
            img = ImageOps.fit(img.convert("RGB"), size, LANCZOS)
            self.thumbs[k] = to_surface(img)
        return self.thumbs[k]

    def refresh_preview(self):
        n = self.cfg["num_photos"]
        img = C.compose(self.cfg, self.placeholders[:n])
        pw = int(self.W * 0.42)
        ph = int(pw * 2 / 3)                       # cadre de l'aperçu (3:2) ; une planche portrait s'y centre
        k = min(pw / img.width, ph / img.height)
        small = to_surface(img.resize((int(img.width * k), int(img.height * k)), LANCZOS))
        surf = pygame.Surface((pw, ph))
        surf.fill(PANEL)
        surf.blit(small, small.get_rect(center=(pw // 2, ph // 2)))
        self.preview_surf = surf
        self.dirty = False

    def draw_config(self):
        S = self.S
        if self.dirty:
            self.refresh_preview()
        overlay = self.kb is not None or self.picker is not None
        self.reg = not overlay
        self.screen.fill(BG)

        # barre d'onglets
        x = S(20)
        for name in TABS:
            self.button((x, S(12), S(120), S(56)), name, lambda n=name: self.set_tab(n), active=self.tab == name, size=22)
            x += S(128)
        self.button((self.W - S(150), S(12), S(130), S(56)), "Terminé", self.close_config, fill=GREEN, size=24)
        self.button((self.W - S(150) - S(8) - S(170), S(12), S(170), S(56)), "Déconnecter", self.logout,
                    fill=(200, 120, 30), size=22)

        # aperçu à droite
        pw = self.preview_surf.get_width()
        px = self.W - pw - S(20)
        py = S(90)
        pygame.draw.rect(self.screen, PANEL, (px - S(8), py - S(8), pw + S(16), self.preview_surf.get_height() + S(16)),
                         border_radius=S(8))
        self.screen.blit(self.preview_surf, (px, py))
        self.text("Aperçu de la planche imprimée", 20, GREY, midtop=(px + pw // 2, py + self.preview_surf.get_height() + S(14)))

        # contenu de l'onglet
        x0, y0, w = S(20), S(92), self.W - pw - S(70)
        {"Fond": self.tab_fond, "Photos": self.tab_photos, "Texte": self.tab_texte,
         "Stockage": self.tab_stockage, "Système": self.tab_systeme}[self.tab](x0, y0, w)

        self.reg = True
        if self.kb is not None:
            self.draw_keyboard()
        elif self.picker is not None:
            self.draw_picker()

    def set_tab(self, name):
        self.tab = name
        self.quit_armed = False

    # --- onglet Fond
    def tab_fond(self, x, y, w):
        S = self.S
        names = C.list_backgrounds()
        cols, gap = 3, S(12)
        tw = (w - gap * (cols - 1)) // cols
        th = int(tw * 2 / 3)
        per = cols * 2
        pages = max(1, math.ceil(len(names) / per))
        self.bg_page = min(self.bg_page, pages - 1)
        for i, name in enumerate(names[self.bg_page * per:(self.bg_page + 1) * per]):
            r = pygame.Rect(x + (i % cols) * (tw + gap), y + (i // cols) * (th + gap), tw, th)
            self.screen.blit(self.thumb(("bg", name), lambda n=name: C.load_background(n), (tw, th)), r)
            cap = pygame.Surface((tw, S(24)), pygame.SRCALPHA)
            cap.fill((0, 0, 0, 150))
            self.screen.blit(cap, (r.x, r.bottom - S(24)))
            self.text(C.pretty_name(name), 17, WHITE, midleft=(r.x + S(8), r.bottom - S(12)))
            if name == self.cfg["background"]:
                pygame.draw.rect(self.screen, ACCENT, r, 6, border_radius=4)
            self.hit(r, lambda n=name: self.set_bg(n))
        yy = y + 2 * (th + gap) + S(6)
        if pages > 1:
            self.button((x, yy, S(70), S(52)), "<", lambda: self.page(-1, pages), size=28)
            self.text(f"Page {self.bg_page + 1}/{pages}", 22, GREY, center=(x + S(150), yy + S(26)))
            self.button((x + S(230), yy, S(70), S(52)), ">", lambda: self.page(1, pages), size=28)
        yy += S(66)
        self.button((x, yy, w, S(62)), "Importer une image depuis une clé USB", self.open_picker, size=24)
        yy += S(78)
        if self.web and self.ip:
            self.text("Ou depuis un téléphone (même Wi-Fi, code requis) :", 20, GREY, topleft=(x, yy))
            self.text(f"http://{self.ip}:8080", 28, ACCENT, topleft=(x, yy + S(30)))
        else:
            self.text("Astuce : copiez vos images dans le dossier backgrounds/", 20, GREY, topleft=(x, yy))

    def page(self, d, pages):
        self.bg_page = (self.bg_page + d) % pages

    def set_bg(self, name):
        self.cfg["background"] = name
        self.save()

    # --- sélecteur d'images USB
    def open_picker(self):
        self.picker = HW.find_usb_images()
        self.picker_page = 0

    def draw_picker(self):
        S = self.S
        self.screen.fill(BG)
        self.text("Choisissez l'image à importer comme fond", 32, WHITE, midtop=(self.W // 2, S(16)))
        self.button((self.W - S(210), S(12), S(190), S(56)), "Annuler", self.close_picker, size=24)
        if not self.picker:
            self.text("Aucune image trouvée.", 30, GREY, center=(self.W // 2, self.H // 2 - S(20)))
            self.text("Branchez une clé USB contenant des fichiers .jpg ou .png.", 24, GREY,
                      center=(self.W // 2, self.H // 2 + S(25)))
            return
        cols, rows, gap = 4, 3, S(14)
        tw = (self.W - S(40) - gap * (cols - 1)) // cols
        th = int(tw * 2 / 3)
        per = cols * rows
        pages = math.ceil(len(self.picker) / per)
        self.picker_page = min(self.picker_page, pages - 1)
        for i, path in enumerate(self.picker[self.picker_page * per:(self.picker_page + 1) * per]):
            r = pygame.Rect(S(20) + (i % cols) * (tw + gap), S(85) + (i // cols) * (th + gap), tw, th)

            def loader(p=path):
                im = Image.open(p)
                im.draft("RGB", (tw * 2, th * 2))
                return ImageOps.exif_transpose(im)
            try:
                self.screen.blit(self.thumb(("usb", path), loader, (tw, th)), r)
            except Exception:
                pygame.draw.rect(self.screen, PANEL, r)
            self.hits.append((r, lambda p=path: self.import_from(p)))
        if pages > 1:
            yy = self.H - S(64)
            self.button((S(20), yy, S(90), S(52)), "<", lambda: self.picker_nav(-1, pages), size=28)
            self.text(f"Page {self.picker_page + 1}/{pages}", 22, GREY, center=(S(190), yy + S(26)))
            self.button((S(270), yy, S(90), S(52)), ">", lambda: self.picker_nav(1, pages), size=28)

    def picker_nav(self, d, pages):
        self.picker_page = (self.picker_page + d) % pages

    def close_picker(self):
        self.picker = None

    def import_from(self, path):
        try:
            name = C.import_background(path)
        except Exception as e:
            self.show_toast(f"Import impossible : {e}")
            self.picker = None
            return
        self.cfg["background"] = name
        self.picker = None
        self.save()
        self.show_toast("Fond importé ✔")

    # --- onglet Photos
    def tab_photos(self, x, y, w):
        S = self.S
        self.text("Nombre de photos sur la planche", 26, WHITE, topleft=(x, y))
        y += S(44)
        gap = S(14)
        bw = (w - 2 * gap) // 3
        bh = S(210)
        for i, n in enumerate((1, 2, 3)):
            r = pygame.Rect(x + i * (bw + gap), y, bw, bh)
            act = self.cfg["num_photos"] == n
            pygame.draw.rect(self.screen, ACCENT if act else PANEL2, r, border_radius=S(12))
            cs = C.canvas_size(n)
            f = min((bw - S(30)) / cs[0], (bh - S(64)) / cs[1])
            ox = r.x + (bw - cs[0] * f) / 2
            oy = r.y + S(14) + ((bh - S(64)) - cs[1] * f) / 2
            pygame.draw.rect(self.screen, (235, 235, 235) if act else (110, 110, 130),
                             (ox, oy, cs[0] * f, cs[1] * f), border_radius=3)
            for (x0, y0, x1, y1) in C.layout_rects(n):
                pygame.draw.rect(self.screen, (60, 60, 60) if act else (190, 190, 205),
                                 (ox + x0 * f, oy + y0 * f, (x1 - x0) * f, (y1 - y0) * f))
            self.text(f"{n} photo" + ("s" if n > 1 else ""), 24, DARK if act else WHITE,
                      center=(r.centerx, r.bottom - S(24)))
            self.hit(r, lambda n=n: self.set_num_photos(n))
        y += bh + S(36)
        self.text("Décompte avant la prise de vue", 26, WHITE, topleft=(x, y))
        y += S(44)
        gap = S(7)
        countdown_w = (w - 9 * gap) // 10
        for i, seconds in enumerate(range(1, 11)):
            self.button((x + i * (countdown_w + gap), y, countdown_w, S(60)), f"{seconds} s",
                        lambda seconds=seconds: self.set_countdown(seconds),
                        active=self.cfg["countdown"] == seconds, size=20)
        y += S(100)
        self.text("Chaque photo est recadrée au format indiqué par le cadre blanc pendant la prise de vue.",
                  19, GREY, topleft=(x, y), max_w=w)

    def set_num_photos(self, n):
        self.cfg["num_photos"] = n
        self.save()

    def step_countdown(self, d):
        self.cfg["countdown"] = min(10, max(1, self.cfg["countdown"] + d))
        self.save()

    def set_countdown(self, seconds):
        self.cfg["countdown"] = min(10, max(1, int(seconds)))
        self.save()

    # --- onglet Texte
    def tab_texte(self, x, y, w):
        S = self.S
        cfg = self.cfg
        self.text("Lignes de texte", 24, GREY, midleft=(x, y + S(26)))
        bw = S(150)
        self.button((x + S(190), y, bw, S(52)), "1 ligne", lambda: self.set_lines(1), active=cfg["num_lines"] == 1)
        self.button((x + S(190) + bw + S(10), y, bw, S(52)), "2 lignes", lambda: self.set_lines(2),
                    active=cfg["num_lines"] == 2)
        y += S(66)
        for i in range(cfg["num_lines"]):
            line = cfg["lines"][i]
            label = f"Ligne {i + 1}"
            placeholder = ("Votre texte pour la première ligne" if i == 0
                           else "Votre texte pour la seconde ligne")
            self.text(label, 22, ACCENT, midleft=(x, y + S(28)))
            tr = self.button((x + S(100), y, w - S(100), S(56)), line["text"] or placeholder,
                             lambda i=i: self.open_keyboard(i), size=26, fill=PANEL)
            pygame.draw.rect(self.screen, PANEL2, tr, 2, border_radius=S(12))
            y += S(68)
            # taille
            self.text("Taille", 20, GREY, midtop=(x + S(100), y - S(2)))
            self.button((x, y + S(26), S(62), S(52)), "–", lambda i=i: self.step_size(i, -4), size=30)
            self.text(str(line["size"]), 26, WHITE, center=(x + S(115), y + S(52)))
            self.button((x + S(168), y + S(26), S(62), S(52)), "+", lambda i=i: self.step_size(i, 4), size=30)
            # couleurs
            sw, sg = S(38), S(8)
            for k, (nm, rgb) in enumerate(C.PALETTE):
                r = pygame.Rect(x + S(260) + (k % 7) * (sw + sg), y + (k // 7) * (sw + sg), sw, sw)
                pygame.draw.rect(self.screen, rgb, r, border_radius=S(8))
                if list(rgb) == list(line["color"]):
                    pygame.draw.rect(self.screen, ACCENT, r.inflate(S(8), S(8)), 4, border_radius=S(10))
                elif rgb in ((25, 15, 15),):
                    pygame.draw.rect(self.screen, PANEL2, r, 1, border_radius=S(8))
                self.hit(r, lambda i=i, rgb=rgb: self.set_color(i, rgb))
            y += S(102)
        fonts = C.list_fonts()
        cur = C.resolve_font(cfg.get("font"))
        idx = next((k for k, (_, p) in enumerate(fonts) if p == cur), 0)
        self.text("Police", 24, GREY, midleft=(x, y + S(26)))
        if fonts:
            self.button((x + S(100), y, S(62), S(52)), "<", lambda: self.step_font(-1), size=28)
            self.text(fonts[idx][0], 22, WHITE, max_w=w - S(320), center=(x + S(100) + S(62) + (w - S(100) - S(124)) // 2, y + S(26)))
            self.button((x + w - S(62), y, S(62), S(52)), ">", lambda: self.step_font(1), size=28)
        y += S(64)
        self.text("Astuce : ajoutez vos polices (.ttf) dans le dossier fonts/", 19, GREY, topleft=(x, y))

    def set_lines(self, n):
        self.cfg["num_lines"] = n
        self.save()

    def step_size(self, i, d):
        v = self.cfg["lines"][i]["size"] + d
        self.cfg["lines"][i]["size"] = min(160, max(20, v))
        self.save()

    def set_color(self, i, rgb):
        self.cfg["lines"][i]["color"] = list(rgb)
        self.save()

    def step_font(self, d):
        fonts = C.list_fonts()
        if not fonts:
            return
        cur = C.resolve_font(self.cfg.get("font"))
        idx = next((k for k, (_, p) in enumerate(fonts) if p == cur), 0)
        self.cfg["font"] = fonts[(idx + d) % len(fonts)][1]
        self.save()

    # --- clavier tactile
    def open_keyboard(self, line):
        t = self.cfg["lines"][line]["text"]
        self.kb = {"line": line, "text": t, "shift": t == ""}

    def kb_type(self, ch):
        if len(self.kb["text"]) < 44:
            self.kb["text"] += ch.upper() if (self.kb["shift"] and ch.isalpha()) else ch
        self.kb["shift"] = False

    def kb_ok(self):
        self.cfg["lines"][self.kb["line"]]["text"] = self.kb["text"].strip()
        self.kb = None
        self.save()

    def kb_key(self, tok):
        if tok == "EFF":
            self.kb["text"] = self.kb["text"][:-1]
        elif tok == "VIDER":
            self.kb["text"] = ""
            self.kb["shift"] = True
        elif tok == "MAJ":
            self.kb["shift"] = not self.kb["shift"]
        elif tok == "ESPACE":
            self.kb_type(" ")
        elif tok == "OK":
            self.kb_ok()
        elif tok == "ANNULER":
            self.kb = None
        else:
            self.kb_type(tok)

    def draw_keyboard(self):
        S = self.S
        self.screen.fill(BG)
        self.text(f"Texte de la ligne {self.kb['line'] + 1}", 26, GREY, topleft=(S(24), S(14)))
        field = pygame.Rect(S(20), S(52), self.W - S(40), S(76))
        pygame.draw.rect(self.screen, PANEL, field, border_radius=S(12))
        pygame.draw.rect(self.screen, ACCENT, field, 2, border_radius=S(12))
        cursor = "|" if int(time.time() * 2) % 2 == 0 else " "
        self.text(self.kb["text"] + cursor, 40, WHITE, max_w=field.w - S(30), midleft=(field.x + S(16), field.centery))
        unit_total = 12.0
        gap = S(8)
        unit = (self.W - S(40) - gap * 11) / unit_total
        kh = min(S(84), (self.H - S(160) - gap * 6) // 6)
        y = S(146)
        for row in KB_ROWS:
            tot = sum(wt for _, wt in row) * unit + gap * (len(row) - 1)
            x = (self.W - tot) / 2
            for tok, wt in row:
                wpx = wt * unit
                label = tok
                if len(tok) == 1 and tok.isalpha() and self.kb["shift"]:
                    label = tok.upper()
                lab = {"EFF": "Effacer", "MAJ": "MAJ", "ESPACE": "Espace", "ANNULER": "Annuler", "VIDER": "Tout effacer"}.get(label, label)
                fill = None
                if tok == "OK":
                    fill = GREEN
                elif tok == "ANNULER":
                    fill = RED
                elif tok == "MAJ" and self.kb["shift"]:
                    fill = ACCENT
                self.button((x, y, wpx, kh), lab, lambda t=tok: self.kb_key(t), size=30 if len(lab) == 1 else 22,
                            fill=fill, active=False)
                x += wpx + gap
            y += kh + gap

    # --- onglet Stockage
    def tab_stockage(self, x, y, w):
        S = self.S
        cfg = self.cfg
        self.text("Enregistrement des photos", 24, GREY, topleft=(x, y))
        y += S(34)
        lab = {"usb": "Clé USB + copie interne", "local": "Copie interne seulement"}[cfg["storage"]]
        self.button((x, y, w, S(56)), lab, self.cycle_storage, size=24)
        y += S(72)
        if self.usb_mount:
            free = f" – {self.usb_free / 1e9:.1f} Go libres" if self.usb_free is not None else ""
            self.text(f"Clé détectée : {os.path.basename(self.usb_mount) or self.usb_mount}{free}", 22, (120, 220, 150),
                      topleft=(x, y), max_w=w)
            if self.sync_running:
                self.text("Copie des photos en cours…", 20, ACCENT, topleft=(x, y + S(28)))
        else:
            self.text("Aucune clé USB détectée", 22, (255, 170, 60), topleft=(x, y))
        y += S(62)
        self.button((x, y, w, S(56)), "Copier les photos vers la clé maintenant", self.manual_sync,
                    enabled=bool(self.usb_mount), size=22)
        y += S(68)
        self.button((x, y, w, S(56)), "Éjecter la clé USB en toute sécurité", self.eject_key,
                    enabled=bool(self.usb_mount), size=22)
        y += S(78)
        self.text(f"{len(self.gal_files)} planche(s) enregistrée(s) sur cet appareil", 22, WHITE, topleft=(x, y), max_w=w)
        y += S(40)
        self.text("Les invités consultent la galerie depuis l'accueil.", 19, GREY, topleft=(x, y), max_w=w)
        self.text("Seul l'administrateur connecté peut supprimer une photo.", 19, GREY, topleft=(x, y + S(26)), max_w=w)

    def cycle_storage(self):
        self.cfg["storage"] = "local" if self.cfg["storage"] == "usb" else "usb"
        self.save()
        if self.cfg["storage"] == "usb":
            self.start_sync()

    def manual_sync(self):
        self.start_sync(manual=True)

    def eject_key(self):
        if self.sync_running or self.eject_running:
            self.show_toast("Opération USB en cours, réessayez dans un instant")
            return
        if not self.usb_mount:
            return
        mount = self.usb_mount
        self.eject_running = True
        self.show_toast("Éjection de la clé en cours…")

        def job():
            try:
                ok, msg = HW.eject_usb(mount)
            except Exception as ex:
                ok, msg = False, f"Éjection impossible : {ex}"

            def completed():
                self.eject_running = False
                if ok:
                    self.usb_mount = None
                self.storage_t = 0
                self.show_toast(msg, 6)
            self.ui_queue.put(completed)

        threading.Thread(target=job, daemon=True).start()

    # --- onglet Système
    def tab_systeme(self, x, y, w):
        S = self.S
        cfg = self.cfg
        self.text("Imprimante", 24, GREY, topleft=(x, y))
        y += S(34)
        label = cfg["printer"] or "(imprimante par défaut)"
        self.button((x, y, w - S(190), S(56)), label, self.cycle_printer, size=24)
        self.button((x + w - S(180), y, S(180), S(56)), "Actualiser", self.refresh_printers, size=22)
        y += S(62)
        if self.printer_ok is None:
            self.text("Imprimante : vérification…", 19, GREY, topleft=(x, y))
        elif self.printer_ok:
            self.text(f"Imprimante : {self.printer_detail}", 19, (120, 220, 150), topleft=(x, y), max_w=w)
        else:
            self.text(f"Imprimante non connectée : {self.printer_detail}", 19, (255, 170, 60), topleft=(x, y), max_w=w)
        y += S(30)
        self.text("Copies", 24, GREY, midleft=(x, y + S(28)))
        self.button((x + S(130), y, S(62), S(56)), "–", lambda: self.step_copies(-1), size=30)
        self.text(str(cfg["copies"]), 28, WHITE, center=(x + S(222), y + S(28)))
        self.button((x + S(254), y, S(62), S(56)), "+", lambda: self.step_copies(1), size=30)
        y += S(76)
        self.text("Après la prise de vue", 24, GREY, topleft=(x, y))
        y += S(34)
        lab = dict(PRINT_MODES)[cfg["print_mode"]]
        self.button((x, y, w, S(56)), lab, self.cycle_print_mode, size=24)
        y += S(68)
        self.text("Délai avant impression", 24, GREY, midleft=(x, y + S(28)))
        self.button((x + S(300), y, S(62), S(56)), "–", lambda: self.step_delay(-1), size=30,
                    enabled=cfg["print_mode"] == "auto")
        self.text(f"{cfg['print_delay']} s", 28, WHITE, center=(x + S(392), y + S(28)))
        self.button((x + S(424), y, S(62), S(56)), "+", lambda: self.step_delay(1), size=30,
                    enabled=cfg["print_mode"] == "auto")
        y += S(68)
        guest_label = ("Galerie : impression autorisée aux invités" if cfg["guest_gallery_print"]
                       else "Galerie : impression réservée à l’administrateur")
        self.button((x, y, w, S(56)), guest_label, self.toggle_guest_gallery_print,
                    active=cfg["guest_gallery_print"], size=21)
        y += S(68)
        self.text(f"Caméra : {self.camera.name}", 20, GREY, topleft=(x, y), max_w=w)
        y += S(30)
        if self.ip:
            self.text(f"Adresse du photobooth : {self.ip}", 20, GREY, topleft=(x, y), max_w=w)
        y += S(46)
        self.button((x, y, S(330), S(56)), "Changer le code d'accès", self.change_pin, size=22)
        y += S(72)
        self.button((x, y, S(330), S(56)), "Confirmer : quitter ?" if self.quit_armed else "Quitter le programme",
                    self.quit_app, fill=RED if self.quit_armed else PANEL2, size=22)

    def cycle_printer(self):
        opts = [""] + self.printers
        cur = self.cfg["printer"]
        i = opts.index(cur) if cur in opts else 0
        self.cfg["printer"] = opts[(i + 1) % len(opts)]
        self.save()
        self.printer_ok, self.printer_detail = None, "vérification…"
        self.poll_printer(time.time(), force=True)

    def refresh_printers(self):
        self.printers = HW.list_printers()
        self.poll_printer(time.time(), force=True)
        self.show_toast(f"{len(self.printers)} imprimante(s) trouvée(s)")

    def step_copies(self, d):
        self.cfg["copies"] = min(5, max(1, self.cfg["copies"] + d))
        self.save()

    def step_delay(self, d):
        self.cfg["print_delay"] = min(10, max(1, self.cfg["print_delay"] + d))
        self.save()

    def cycle_print_mode(self):
        modes = [m for m, _ in PRINT_MODES]
        self.cfg["print_mode"] = modes[(modes.index(self.cfg["print_mode"]) + 1) % len(modes)]
        self.save()

    def toggle_guest_gallery_print(self):
        self.cfg["guest_gallery_print"] = not self.cfg["guest_gallery_print"]
        self.save()

    def quit_app(self):
        if self.quit_armed:
            self.close_config()
            self.running = False
        else:
            self.quit_armed = True

    # ------------------------------------------------------------ clé USB (sauvegarde)
    def poll_storage(self, now):
        if self.eject_running or now - self.storage_t < 3:
            return
        self.storage_t = now
        mount = HW.find_usb_mount(self.cfg.get("usb_path", ""))
        if mount != self.usb_mount:
            self.usb_mount = mount
            if mount and self.cfg["storage"] == "usb":
                self.show_toast("Clé USB détectée")
                self.start_sync()
            elif not mount and self.cfg["storage"] == "usb":
                self.show_toast("Clé USB retirée")
        self.usb_free = None
        if mount:
            try:
                self.usb_free = shutil.disk_usage(mount).free
            except OSError:
                pass

    def start_sync(self, manual=False):
        if self.eject_running:
            if manual:
                self.show_toast("Éjection en cours")
            return
        if not self.usb_mount:
            if manual:
                self.show_toast("Aucune clé USB détectée")
            return
        if self.sync_running:
            self.sync_again = True
            return
        self.sync_running = True
        mount = self.usb_mount

        def job():
            msg = ""
            try:
                while True:
                    self.sync_again = False
                    n = HW.sync_to_usb(mount)
                    if manual:
                        msg = f"{n} fichier(s) copié(s) sur la clé"
                    if not self.sync_again:
                        break
            except Exception as ex:
                msg = f"Erreur de copie sur la clé : {ex}"
            finally:
                self.sync_running = False
            if msg:
                self.show_toast(msg, 5)

        threading.Thread(target=job, daemon=True).start()

    def pill(self, txt, col, y):
        surf = self.font(20 * self.s).render(txt, True, col)
        r = surf.get_rect(topleft=(self.S(20), y))
        pill = pygame.Surface((r.w + self.S(24), r.h + self.S(12)), pygame.SRCALPHA)
        pygame.draw.rect(pill, (0, 0, 0, 150), pill.get_rect(), border_radius=pill.get_height() // 2)
        self.screen.blit(pill, (r.x - self.S(12), r.y - self.S(6)))
        self.screen.blit(surf, r)

    def draw_usb_badge(self):
        y = self.S(20)
        if self.cfg["storage"] == "usb":
            if self.usb_mount:
                txt, col = ("Clé USB : copie…" if self.sync_running else "Clé USB : OK"), (120, 220, 150)
            else:
                txt, col = "Pas de clé USB", (255, 170, 60)
            self.pill(txt, col, y)
            y += self.S(38)
        if self.cfg["print_mode"] == "auto":
            if self.printer_ok is None:
                txt, col = "Imprimante : vérification…", GREY
            elif self.printer_ok:
                txt, col = "Imprimante : OK", (120, 220, 150)
            else:
                txt, col = "Imprimante non connectée", (255, 170, 60)
            self.pill(txt, col, y)

    # ------------------------------------------------------------ galerie
    def refresh_gallery(self):
        self.gal_files = C.list_gallery()
        self.gal_idx = min(self.gal_idx, max(0, len(self.gal_files) - 1))

    def open_gallery(self):
        self.refresh_gallery()
        self.gal_idx = max(0, len(self.gal_files) - 1)       # on commence par la plus récente
        self.gal_confirm = False
        self.swipe = None
        self.last_touch = time.time()
        self.mode = "gallery"

    def close_gallery(self):
        self.gal_confirm = False
        self.gal_cache.clear()
        self.mode = "home"

    def gal_step(self, d):
        if self.gal_files:
            self.gal_idx = min(len(self.gal_files) - 1, max(0, self.gal_idx + d))

    def gal_surface(self, path, box):
        key = (path, box)
        surf = self.gal_cache.get(key)
        if surf is None:
            img = Image.open(path).convert("RGB")
            k = min(box[0] / img.width, box[1] / img.height)
            surf = to_surface(img.resize((int(img.width * k), int(img.height * k)), LANCZOS))
            if len(self.gal_cache) > 6:
                self.gal_cache.pop(next(iter(self.gal_cache)))
            self.gal_cache[key] = surf
        return surf

    def gal_print(self):
        """Réimprime une planche si l'utilisateur courant y est autorisé."""
        if (not self.admin and not self.cfg["guest_gallery_print"]) or not self.gal_files:
            return
        if self.admin:
            self.admin_last = time.time()
        if self.printer_ok is False:
            self.show_toast(f"Imprimante non connectée : {self.printer_detail}", 5)
            return
        path, cfg = self.gal_files[self.gal_idx], self.cfg
        self.show_toast("Impression en cours…", 3)

        def job():
            ok, msg = HW.print_file(path, cfg["printer"], cfg["copies"], cfg["print_options"])
            self.show_toast("Impression lancée" if ok else f"Erreur d'impression : {msg}", 5)

        threading.Thread(target=job, daemon=True).start()

    def gal_ask_delete(self):
        if self.admin and self.gal_files:
            self.gal_confirm = True

    def gal_cancel_delete(self):
        self.gal_confirm = False

    def gal_delete(self):
        self.gal_confirm = False
        if not self.admin or not self.gal_files:          # sécurité : jamais sans administrateur connecté
            return
        path = self.gal_files[self.gal_idx]
        C.delete_photo(path, self.usb_mount)
        self.admin_last = time.time()
        self.gal_cache.clear()
        self.refresh_gallery()
        self.show_toast("Photo supprimée")

    def draw_gallery(self):
        S, n = self.S, len(self.gal_files)
        self.reg = not self.gal_confirm
        self.screen.fill(BG)
        if n:
            path = self.gal_files[self.gal_idx]
            self.text(f"{self.gal_idx + 1} / {n}   ·   {C.photo_label(path)}", 26, WHITE, center=(self.W // 2, S(30)))
        else:
            self.text("Galerie", 28, WHITE, center=(self.W // 2, S(30)))
        if self.admin:
            self.text("Mode administrateur", 20, ACCENT, midleft=(S(20), S(30)))
            self.button((self.W - S(200), S(6), S(180), S(48)), "Déconnecter", self.logout, fill=(200, 120, 30), size=20)
        elif C.has_pin(self.cfg):
            self.button((self.W - S(160), S(6), S(140), S(48)), "Admin", lambda: self.login("gallery"), fill=PANEL, size=20)
        area = (self.W - S(40), self.H - S(60) - S(120))
        if n:
            surf = self.gal_surface(path, area)
            self.screen.blit(surf, surf.get_rect(center=(self.W // 2, S(60) + area[1] // 2)))
        else:
            self.text("Aucune photo pour l'instant", 32, GREY, center=(self.W // 2, self.H // 2))
        btns = [("<  Précédent", lambda: self.gal_step(-1), n > 0 and self.gal_idx > 0, None),
                ("Quitter", self.close_gallery, True, None),
                ("Suivant  >", lambda: self.gal_step(1), n > 0 and self.gal_idx < n - 1, None)]
        if n and (self.admin or self.cfg["guest_gallery_print"]):
            btns.append(("Imprimer", self.gal_print, True, GREEN))
        if self.admin and n:
            btns.append(("Supprimer", self.gal_ask_delete, True, RED))
        gap = S(14)
        bw = min(S(300), (self.W - S(40) - gap * (len(btns) - 1)) // len(btns))
        x = (self.W - (bw * len(btns) + gap * (len(btns) - 1))) // 2
        for lab, cb, en, fill in btns:
            self.button((x, self.H - S(104), bw, S(88)), lab, cb, enabled=en, fill=fill, size=28)
            x += bw + gap
        if self.gal_confirm:
            self.reg = True
            dim = pygame.Surface((self.W, self.H), pygame.SRCALPHA)
            dim.fill((0, 0, 0, 190))
            self.screen.blit(dim, (0, 0))
            panel = pygame.Rect(0, 0, S(640), S(300))
            panel.center = (self.W // 2, self.H // 2)
            pygame.draw.rect(self.screen, PANEL, panel, border_radius=S(16))
            self.text("Supprimer cette photo ?", 36, WHITE, center=(panel.centerx, panel.y + S(60)))
            self.text("Cette action est définitive.", 22, GREY, center=(panel.centerx, panel.y + S(105)))
            self.button((panel.x + S(30), panel.bottom - S(120), S(280), S(80)), "Oui, supprimer", self.gal_delete,
                        fill=RED, size=26)
            self.button((panel.right - S(310), panel.bottom - S(120), S(280), S(80)), "Annuler", self.gal_cancel_delete, size=26)

    # ------------------------------------------------------------ boucle
    def draw(self):
        self.hits = []
        self.hits_mode = self.mode
        self.reg = True
        if self.mode == "home":
            self.draw_home()
        elif self.mode == "countdown":
            self.draw_countdown()
        elif self.mode == "result":
            self.draw_result()
        elif self.mode == "config":
            self.draw_config()
        elif self.mode == "pin":
            self.draw_pin()
        elif self.mode == "gallery":
            self.draw_gallery()
        msg, until = self.toast
        if msg and time.time() < until and self.phase != "flash":
            surf = self.font(26 * self.s).render(msg, True, DARK)
            r = surf.get_rect(midtop=(self.W // 2, self.S(84)))
            pygame.draw.rect(self.screen, ACCENT, r.inflate(self.S(40), self.S(20)), border_radius=self.S(20))
            self.screen.blit(surf, r)

    def run(self):
        while self.running:
            for e in pygame.event.get():
                self.handle(e)
            self.update()
            self.draw()
            pygame.display.flip()
            self.clock.tick(30)
        try:
            self.camera.stop()
        finally:
            pygame.quit()


def main():
    ap = argparse.ArgumentParser(description="Photobooth tactile")
    ap.add_argument("--windowed", action="store_true", help="fenêtre au lieu du plein écran (tests)")
    ap.add_argument("--size", default="1280x800", help="taille de la fenêtre en mode --windowed")
    ap.add_argument("--camera", default="auto", choices=["auto", "picamera", "webcam", "fake"])
    ap.add_argument("--no-web", action="store_true", help="désactive l'envoi de fonds depuis un téléphone")
    App(ap.parse_args()).run()


if __name__ == "__main__":
    main()
