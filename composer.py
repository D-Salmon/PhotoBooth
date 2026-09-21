"""Configuration, fonds et composition de la planche photo (1800x1200 px = 10x15 cm à 300 dpi)."""
import hashlib
import hmac
import json
import os
import tempfile
import random
import re
import secrets
import time
from functools import lru_cache
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageOps

LANCZOS = getattr(Image, "Resampling", Image).LANCZOS

BASE = Path(__file__).resolve().parent
BG_DIR = BASE / "backgrounds"
FONT_DIR = BASE / "fonts"
PHOTO_DIR = BASE / "photos"
RAW_DIR = PHOTO_DIR / "raw"
CONFIG_PATH = BASE / "config.json"

LANDSCAPE = (1800, 1200)      # 10x15 cm en paysage (1 ou 3 photos), 300 dpi
PORTRAIT = (1200, 1800)       # 10x15 cm en portrait (2 photos)
CANVAS = LANDSCAPE


def canvas_size(n):
    return PORTRAIT if n == 2 else LANDSCAPE


def text_zone(n):
    """(centre vertical, hauteur maximale) de la zone de texte, sous les photos."""
    return (1696, 190) if n == 2 else (1068, 240)

DEFAULT_CONFIG = {
    "background": "01_or.jpg",
    "num_photos": 3,
    "num_lines": 2,
    "lines": [
        {"text": "Votre texte pour la première ligne", "size": 72, "color": [25, 15, 15]},
        {"text": "Votre texte pour la seconde ligne", "size": 52, "color": [25, 15, 15]},
    ],
    "font": "",
    "countdown": 3,
    "print_mode": "auto",        # auto = impression après un délai (annulable) | off = pas d'impression
    "print_delay": 3,            # secondes avant impression (l'invité peut annuler)
    "printer": "",
    "printer_host": "",          # facultatif : adresse IP de l'imprimante pour tester sa présence
    "copies": 1,
    "print_options": "fit-to-page",
    "guest_gallery_print": False, # autorise les invités à imprimer depuis la galerie
    "storage": "usb",            # usb = copie sur clé USB + copie interne | local = copie interne seulement
    "usb_path": "",              # facultatif : forcer un dossier au lieu de la détection automatique
    "pin_salt": "",              # code d'accès au menu (stocké sous forme de hachage)
    "pin_hash": "",
}

PALETTE = [
    ("Noir", (25, 15, 15)), ("Blanc", (255, 255, 255)), ("Or", (212, 175, 55)),
    ("Or foncé", (150, 110, 20)), ("Argent", (192, 192, 200)), ("Gris", (110, 110, 118)),
    ("Crème", (245, 232, 200)), ("Rouge", (185, 30, 40)), ("Bordeaux", (110, 20, 40)),
    ("Rose", (230, 120, 160)), ("Orange", (230, 130, 30)), ("Vert", (30, 130, 80)),
    ("Bleu", (40, 110, 200)), ("Bleu marine", (20, 40, 90)),
]


# ------------------------------------------------------------------ configuration
def _bounded(value, default, low, high):
    try:
        return min(high, max(low, int(value)))
    except (TypeError, ValueError, OverflowError):
        return default


def load_config():
    cfg = json.loads(json.dumps(DEFAULT_CONFIG))
    try:
        data = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        data = {}
    if not isinstance(data, dict):
        data = {}
    for key, default in DEFAULT_CONFIG.items():
        if isinstance(default, str) and isinstance(data.get(key), str):
            cfg[key] = data[key]
        elif isinstance(default, bool) and isinstance(data.get(key), bool):
            cfg[key] = data[key]
    for key, low, high in (("num_photos", 1, 3), ("num_lines", 1, 2),
                           ("countdown", 1, 10), ("copies", 1, 5), ("print_delay", 1, 10)):
        cfg[key] = _bounded(data.get(key), cfg[key], low, high)
    for key, choices in (("print_mode", ("auto", "off")), ("storage", ("usb", "local"))):
        if cfg[key] not in choices:
            cfg[key] = DEFAULT_CONFIG[key]
    lines = data.get("lines")
    if isinstance(lines, list):
        for dest, source in zip(cfg["lines"], lines):
            if not isinstance(source, dict):
                continue
            if isinstance(source.get("text"), str):
                dest["text"] = source["text"]
            dest["size"] = _bounded(source.get("size"), dest["size"], 20, 160)
            color = source.get("color")
            if isinstance(color, (list, tuple)) and len(color) == 3:
                dest["color"] = [_bounded(v, d, 0, 255) for v, d in zip(color, dest["color"])]
    return cfg


def _atomic_write(path, writer):
    """Publie un fichier complet, sans écraser l'ancien en cas d'échec."""
    path = Path(path)
    fd, name = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            writer(stream)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
    finally:
        try:
            os.unlink(name)
        except FileNotFoundError:
            pass


def save_config(cfg):
    content = json.dumps(cfg, indent=2, ensure_ascii=False).encode("utf-8")
    _atomic_write(CONFIG_PATH, lambda stream: stream.write(content))


# ------------------------------------------------------------------ code d'accès
def _hash_pin(pin, salt):
    return hashlib.pbkdf2_hmac("sha256", pin.encode(), salt.encode(), 100_000).hex()


def has_pin(cfg):
    return bool(cfg.get("pin_hash"))


def set_pin(cfg, pin):
    if not re.fullmatch(r"[0-9]{4}", pin):
        raise ValueError("Le code doit contenir exactement 4 chiffres")
    cfg["pin_salt"] = secrets.token_hex(8)
    cfg["pin_hash"] = _hash_pin(pin, cfg["pin_salt"])


def check_pin(cfg, pin):
    if not has_pin(cfg) or not pin:
        return False
    return hmac.compare_digest(_hash_pin(str(pin).strip(), cfg["pin_salt"]), cfg["pin_hash"])


# ------------------------------------------------------------------ polices
SYSTEM_FONTS = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSerif-Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSerif.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSerif-BoldItalic.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSerif-Bold.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    "/usr/share/fonts/truetype/freefont/FreeSerifBoldItalic.ttf",
    "C:/Windows/Fonts/arial.ttf",
    "C:/Windows/Fonts/calibri.ttf",
    "C:/Windows/Fonts/segoeui.ttf",
]


def list_fonts():
    """[(libellé, chemin)] : polices du dossier fonts/ puis polices système courantes."""
    found = []
    if FONT_DIR.exists():
        for p in sorted(FONT_DIR.iterdir()):
            if p.suffix.lower() in (".ttf", ".otf"):
                found.append((p.stem.replace("-", " ").replace("_", " "), str(p)))
    for p in SYSTEM_FONTS:
        if Path(p).exists():
            found.append((Path(p).stem.replace("-", " "), p))
    return found


def resolve_font(path):
    fonts = list_fonts()
    for _, p in fonts:
        if p == path:
            return p
    return fonts[0][1] if fonts else None


@lru_cache(maxsize=64)
def get_font(path, size):
    if path:
        try:
            return ImageFont.truetype(path, size)
        except Exception:
            pass
    try:
        return ImageFont.load_default(size)
    except TypeError:
        return ImageFont.load_default()


# ------------------------------------------------------------------ fonds
def pretty_name(filename):
    stem = Path(filename).stem
    stem = re.sub(r"^\d+_", "", stem)
    if stem.startswith("perso_"):
        return "Perso"
    return stem.replace("_", " ").capitalize()


def list_backgrounds():
    if not BG_DIR.exists():
        return []
    return sorted(p.name for p in BG_DIR.iterdir() if p.suffix.lower() in (".jpg", ".jpeg", ".png"))


def _bokeh_background(seed, top, bottom, bokeh, glitter, dark=False):
    rng = np.random.default_rng(seed)
    W, H = CANVAS
    y = np.linspace(0, 1, H)[:, None, None]
    base = np.array(top, float) * (1 - y) + np.array(bottom, float) * y
    base = base * np.ones((1, W, 1))
    low = rng.normal(0, 1, (H // 60 + 2, W // 60 + 2))
    low = np.asarray(Image.fromarray(((low - low.min()) / (np.ptp(low)) * 255).astype(np.uint8)).resize((W, H), Image.BICUBIC), float) / 255 - 0.5
    base += low[..., None] * (30 if not dark else 18)
    img = Image.fromarray(np.clip(base, 0, 255).astype(np.uint8)).convert("RGBA")

    # zones (haut et bas) plus riches en paillettes
    yy = np.abs(np.linspace(-1, 1, H))[:, None] ** 1.6
    noise = rng.random((H, W))
    sparkle = (noise > (1 - 0.06 * (0.15 + yy))) * 1.0
    sparkle = np.asarray(Image.fromarray((sparkle * 255).astype(np.uint8)).filter(ImageFilter.GaussianBlur(1.1)), float) / 255
    layer = np.zeros((H, W, 4), np.uint8)
    layer[..., :3] = glitter
    layer[..., 3] = np.clip(sparkle * 255 * 2.2, 0, 255).astype(np.uint8)
    img.alpha_composite(Image.fromarray(layer, "RGBA"))

    # bokeh
    ov = Image.new("RGBA", CANVAS, (0, 0, 0, 0))
    d = ImageDraw.Draw(ov)
    for _ in range(110):
        r = int(rng.choice([10, 14, 20, 28, 40, 56]))
        cx = int(rng.uniform(0, W))
        cy = int(rng.beta(0.55, 0.55) * H)
        col = bokeh[int(rng.integers(len(bokeh)))]
        a = int(rng.uniform(35, 120))
        d.ellipse((cx - r, cy - r, cx + r, cy + r), fill=col + (a,))
        if rng.random() < 0.4:
            d.ellipse((cx - r, cy - r, cx + r, cy + r), outline=col + (min(255, a + 60),), width=2)
    ov = ov.filter(ImageFilter.GaussianBlur(1.6))
    img.alpha_composite(ov)
    return img.convert("RGB")


DEFAULT_BACKGROUNDS = [
    ("01_or.jpg", dict(seed=1, top=(218, 168, 42), bottom=(190, 138, 28), bokeh=[(255, 240, 170), (255, 214, 110)], glitter=(255, 236, 160))),
    ("02_argent.jpg", dict(seed=2, top=(196, 198, 206), bottom=(150, 155, 166), bokeh=[(255, 255, 255), (222, 228, 242)], glitter=(255, 255, 255))),
    ("03_rose.jpg", dict(seed=3, top=(236, 156, 176), bottom=(200, 112, 142), bokeh=[(255, 222, 232), (255, 190, 210)], glitter=(255, 230, 236))),
    ("04_bleu_nuit.jpg", dict(seed=4, top=(18, 30, 78), bottom=(8, 12, 42), bokeh=[(150, 180, 255), (255, 255, 255), (120, 140, 230)], glitter=(205, 218, 255), dark=True)),
    ("05_noir_et_or.jpg", dict(seed=5, top=(24, 20, 16), bottom=(10, 8, 8), bokeh=[(230, 190, 80), (255, 225, 140)], glitter=(255, 215, 120), dark=True)),
    ("06_blanc.jpg", dict(seed=6, top=(252, 249, 242), bottom=(236, 229, 216), bokeh=[(255, 255, 255), (226, 210, 180)], glitter=(232, 216, 180))),
    ("07_emeraude.jpg", dict(seed=7, top=(24, 96, 74), bottom=(10, 56, 46), bokeh=[(180, 240, 200), (255, 255, 255)], glitter=(200, 245, 215), dark=True)),
]


def ensure_default_backgrounds():
    BG_DIR.mkdir(exist_ok=True)
    for name, kw in DEFAULT_BACKGROUNDS:
        if not (BG_DIR / name).exists():
            print(f"Création du fond {name}…")
            _bokeh_background(**kw).save(BG_DIR / name, quality=92)


_bg_cache = {}


def load_background(name, size=None):
    """Fond au format demandé. Un fond paysage est pivoté de 90° pour une planche portrait (et inversement).
    Sans « size », renvoie le fond dans son orientation d'origine."""
    p = BG_DIR / name
    if not p.exists():
        names = list_backgrounds()
        if not names:
            return Image.new("RGB", size or LANDSCAPE, (200, 170, 60))
        p = BG_DIR / names[0]
    key = (str(p), p.stat().st_mtime)
    img = _bg_cache.get(key)
    if img is None:
        img = Image.open(p).convert("RGB")
        base = LANDSCAPE if img.width >= img.height else PORTRAIT
        if img.size != base:
            img = ImageOps.fit(img, base, LANCZOS)
        if len(_bg_cache) > 8:
            _bg_cache.clear()
        _bg_cache[key] = img
    if size and img.size != tuple(size):
        return img.transpose(Image.ROTATE_90)
    return img.copy()


def import_background(src):
    """Importe une image (chemin ou fichier ouvert) comme nouveau fond ; renvoie son nom."""
    img = ImageOps.exif_transpose(Image.open(src)).convert("RGB")
    base = LANDSCAPE if img.width >= img.height else PORTRAIT
    img = ImageOps.fit(img, base, LANCZOS)         # recadrage centré au format 3:2 (ou 2:3)
    BG_DIR.mkdir(exist_ok=True)
    name = f"perso_{time.strftime('%Y%m%d_%H%M%S')}_{random.randint(100, 999)}.jpg"
    img.save(BG_DIR / name, quality=93)
    return name


# ------------------------------------------------------------------ mise en page
def layout_rects(n):
    """Rectangles (x0, y0, x1, y1) des photos : planche 1800x1200 (1 ou 3 photos) ou 1200x1800 (2 photos)."""
    if n == 1:
        w, h = 1110, 742
        x = (LANDSCAPE[0] - w) // 2
        return [(x, 178, x + w, 178 + h)]
    if n == 2:                                    # portrait : deux photos 3:2 empilées
        return [(60, 78, 1140, 798), (60, 858, 1140, 1578)]
    return [(60, 178, 1170, 920), (1230, 178, 1742, 522), (1230, 576, 1742, 920)]


def photo_aspect(n):
    x0, y0, x1, y1 = layout_rects(n)[0]
    return (x1 - x0) / (y1 - y0)


def paste_framed(canvas, shot, rect, border=8):
    x0, y0, x1, y1 = rect
    w, h = x1 - x0, y1 - y0
    photo = ImageOps.fit(shot.convert("RGB"), (w, h), LANCZOS, centering=(0.5, 0.4))
    pad = 40
    layer = Image.new("RGBA", (w + 2 * pad, h + 2 * pad), (0, 0, 0, 0))
    ImageDraw.Draw(layer).rectangle(
        (pad - border + 2, pad - border + 8, pad + w + border + 4, pad + h + border + 10), fill=(0, 0, 0, 120))
    layer = layer.filter(ImageFilter.GaussianBlur(9))
    ImageDraw.Draw(layer).rectangle(
        (pad - border, pad - border, pad + w + border - 1, pad + h + border - 1), fill=(255, 255, 255, 255))
    layer.paste(photo, (pad, pad))
    canvas.alpha_composite(layer, (x0 - pad, y0 - pad))


def draw_text(canvas, cfg):
    lines = [l for l in cfg["lines"][:cfg["num_lines"]] if l["text"].strip()]
    if not lines:
        return
    path = resolve_font(cfg.get("font"))
    center_y, max_h = text_zone(cfg["num_photos"])
    sizes = [int(l["size"]) for l in lines]

    def measure():
        gap = int(sizes[0] * 0.25) if len(sizes) > 1 else 0
        return sum(int(s * 1.15) for s in sizes) + gap * (len(sizes) - 1), gap

    # on réduit si le bloc est trop haut ou si une ligne dépasse la largeur
    total, gap = measure()
    while total > max_h and max(sizes) > 16:
        sizes = [max(16, s - 2) for s in sizes]
        total, gap = measure()
    for i, l in enumerate(lines):
        while get_font(path, sizes[i]).getlength(l["text"]) > canvas.width - 120 and sizes[i] > 16:
            sizes[i] -= 2
    total, gap = measure()

    d = ImageDraw.Draw(canvas)
    y = center_y - total // 2
    for l, s in zip(lines, sizes):
        h = int(s * 1.15)
        d.text((canvas.width // 2, y + h // 2), l["text"], font=get_font(path, s),
               fill=tuple(l["color"]) + (255,), anchor="mm")
        y += h + gap


def compose(cfg, shots):
    n = cfg["num_photos"]
    canvas = load_background(cfg["background"], canvas_size(n)).convert("RGBA")
    for shot, rect in zip(shots, layout_rects(n)):
        paste_framed(canvas, shot, rect)
    draw_text(canvas, cfg)
    return canvas.convert("RGB")


def save_outputs(img, shots):
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d_%H%M%S")
    path = PHOTO_DIR / f"planche_{stamp}.jpg"
    _atomic_write(path, lambda f: img.save(f, format="JPEG", quality=95, dpi=(300, 300)))
    for i, s in enumerate(shots, 1):
        _atomic_write(RAW_DIR / f"{stamp}_{i}.jpg",
                      lambda f: s.convert("RGB").save(f, format="JPEG", quality=92))
    return str(path)


# ------------------------------------------------------------------ galerie
def list_gallery():
    """Planches enregistrées sur l'appareil, de la plus ancienne à la plus récente."""
    if not PHOTO_DIR.exists():
        return []
    return [str(p) for p in sorted(PHOTO_DIR.glob("planche_*.jpg"))]


def photo_stamp(path):
    m = re.match(r"planche_(\d{8}_\d{6})", Path(path).name)
    return m.group(1) if m else None


def photo_label(path):
    stamp = photo_stamp(path)
    if not stamp:
        return Path(path).name
    try:
        return time.strftime("%d/%m/%Y %H:%M", time.strptime(stamp, "%Y%m%d_%H%M%S"))
    except ValueError:
        return stamp


def delete_photo(path, usb_root=None):
    """Supprime la planche, ses photos individuelles et leurs copies sur la clé (si branchée)."""
    stamp = photo_stamp(path)
    targets = [Path(path)]
    if stamp:
        targets += list(RAW_DIR.glob(f"{stamp}_*.jpg"))
    if usb_root:
        d = Path(usb_root) / "Photobooth"
        targets.append(d / Path(path).name)
        if stamp:
            targets += list((d / "raw").glob(f"{stamp}_*.jpg"))
    removed = 0
    for t in targets:
        try:
            t.unlink()
            removed += 1
        except FileNotFoundError:
            pass
    return removed


def make_placeholder(i):
    """Fausse photo (silhouettes) pour l'aperçu dans le menu."""
    W, H = 1920, 1080
    img = Image.new("RGB", (W, H))
    d = ImageDraw.Draw(img)
    for yy in range(0, H, 4):
        c = int(228 - yy * 0.07)
        d.rectangle((0, yy, W, yy + 4), fill=(c, c - 6, c - 16))
    skins = [(226, 178, 150), (210, 160, 130), (238, 196, 170)]
    hairs = [(150, 110, 70), (90, 60, 45), (205, 175, 125)]
    shirts = [(60, 110, 150), (190, 70, 90), (240, 240, 240)]
    for k, x in enumerate([560, 960, 1360]):
        x += (i - 1) * 30 * (1 if k % 2 else -1)
        j = (k + i) % 3
        d.ellipse((x - 310, 760, x + 310, 1500), fill=shirts[j])
        d.ellipse((x - 130, 270, x + 130, 640), fill=hairs[j])
        d.ellipse((x - 105, 330, x + 105, 630), fill=skins[j])
    return img
