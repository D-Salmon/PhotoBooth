"""Caméra, impression (CUPS), clé USB et envoi de fonds depuis un téléphone."""
import glob
import logging
import math
import os
import re
import shlex
import shutil
import socket
import subprocess
import threading
import time
from pathlib import Path
from urllib.parse import urlparse

import numpy as np
from PIL import Image, ImageDraw

import composer

IMG_EXT = (".jpg", ".jpeg", ".png")


# ------------------------------------------------------------------ caméras
class PiCamera:
    """Raspberry Pi Camera Module (picamera2). Aperçu 1280x720, photo 2304x1296."""
    name = "Raspberry Pi Camera"

    def __init__(self, preview_size=(1280, 720), still_size=(2304, 1296)):
        from picamera2 import Picamera2
        self.cam = Picamera2()
        # « BGR888 » donne des tableaux dans l'ordre R,G,B (particularité de picamera2).
        # Si les couleurs sont inversées, remplacer par "RGB888".
        fmt = "BGR888"
        self.prev_cfg = self.cam.create_preview_configuration(
            main={"size": preview_size, "format": fmt}, buffer_count=3)
        self.still_cfg = self.cam.create_still_configuration(main={"size": still_size, "format": fmt})
        self.cam.configure(self.prev_cfg)
        self.cam.start()
        try:                                     # autofocus continu (Module 3)
            self.cam.set_controls({"AfMode": 2})
        except Exception:
            pass

    def frame(self):
        return self.cam.capture_array("main")

    def capture(self):
        arr = self.cam.switch_mode_and_capture_array(self.still_cfg, "main")
        return Image.fromarray(arr)

    def stop(self):
        try:
            self.cam.stop()
        except Exception:
            pass


class Webcam:
    """Webcam USB via OpenCV."""
    name = "Webcam USB"

    def __init__(self, index=0):
        import cv2
        self.cv2 = cv2
        self.cap = cv2.VideoCapture(index)
        self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1920)
        self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 1080)
        ok, _ = self.cap.read()
        if not ok:
            raise RuntimeError("webcam introuvable")

    def _read(self):
        ok, frame = self.cap.read()
        return self.cv2.cvtColor(frame, self.cv2.COLOR_BGR2RGB) if ok else None

    def frame(self):
        return self._read()

    def capture(self):
        for _ in range(3):
            self.cap.read()
        arr = self._read()
        return Image.fromarray(arr)

    def stop(self):
        self.cap.release()


class FakeCamera:
    """Caméra de test (aucun matériel nécessaire)."""
    name = "Caméra de TEST (aucune caméra détectée)"

    def __init__(self):
        self.count = 0

    def _scene(self, size, label, t, tone=0):
        w, h = size
        img = Image.new("RGB", size, (70 + tone * 15, 85, 105))
        d = ImageDraw.Draw(img)
        for k in range(3):
            x = w * (0.28 + 0.22 * k) + math.sin(t * 1.5 + k) * w * 0.01
            d.ellipse((x - w * 0.14, h * 0.62, x + w * 0.14, h * 1.35), fill=[(60, 110, 150), (190, 70, 90), (235, 235, 235)][(k + tone) % 3])
            d.ellipse((x - w * 0.06, h * 0.25, x + w * 0.06, h * 0.68), fill=(226, 178, 150))
        d.text((20, 20), label, fill=(255, 255, 255))
        return img

    def frame(self):
        return np.asarray(self._scene((1280, 720), "CAMERA DE TEST", time.time()))

    def capture(self):
        self.count += 1
        return self._scene((1920, 1080), f"PHOTO TEST {self.count}", 0, tone=self.count)

    def stop(self):
        pass


def make_camera(kind="auto"):
    if kind in ("auto", "picamera"):
        try:
            return PiCamera()
        except Exception as e:
            print("picamera2 indisponible :", e)
            if kind == "picamera":
                raise
    if kind in ("auto", "webcam"):
        try:
            return Webcam()
        except Exception as e:
            print("webcam indisponible :", e)
            if kind == "webcam":
                raise
    return FakeCamera()


# ------------------------------------------------------------------ impression
def list_printers():
    try:
        out = subprocess.run(["lpstat", "-e"], capture_output=True, text=True, timeout=5).stdout
        return [l.strip() for l in out.splitlines() if l.strip()]
    except Exception:
        return []


def _run(cmd, timeout=5):
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout,
                           env={**os.environ, "LC_ALL": "C", "LANG": "C"})
        return r.returncode, r.stdout + r.stderr
    except FileNotFoundError:
        return None, ""
    except Exception as e:
        return -1, str(e)


def _tcp_ok(host, port, timeout=2.0):
    try:
        socket.create_connection((host, port), timeout=timeout).close()
        return True
    except OSError:
        return False


def printer_status(printer="", host=""):
    """L'imprimante est-elle connectée ? Renvoie (bool, détail). Appel bloquant : à lancer dans un thread."""
    if host:
        return (True, "connectée") if _tcp_ok(host, 631) else (False, f"injoignable ({host})")
    name = printer
    if not name:
        rc, out = _run(["lpstat", "-d"])
        if rc is None:
            return False, "CUPS non installé"
        m = re.search(r"destination:\s*(\S+)", out)
        name = m.group(1) if m else ""
    if not name:
        return False, "aucune imprimante définie"
    rc, out = _run(["lpstat", "-p", name])
    if rc is None:
        return False, "CUPS non installé"
    if rc != 0:
        return False, "imprimante inconnue de CUPS"
    if "disabled" in out.lower():
        return False, "imprimante désactivée (éteinte ou débranchée)"
    rc, out = _run(["lpstat", "-v", name])
    m = re.search(r"device for [^:]+:\s*(\S+)", out)
    uri = m.group(1) if m else ""
    scheme = uri.split(":", 1)[0]
    ports = {"ipp": 631, "ipps": 631, "http": 80, "https": 443, "socket": 9100, "lpd": 515}
    if scheme in ports:
        u = urlparse(uri)
        if u.hostname and not _tcp_ok(u.hostname, u.port or ports[scheme]):
            return False, "imprimante injoignable sur le réseau"
        return True, "connectée"
    if scheme == "usb":
        rc, out = _run(["lpinfo", "--include-schemes", "usb", "-v"], timeout=8)
        if rc == 0 and uri.split("?")[0] not in out:
            return False, "câble USB non détecté"
        return True, "connectée"
    return True, "connectée (état CUPS)"     # dnssd, etc. : voir « printer_host » dans config.json


def print_file(path, printer="", copies=1, options="fit-to-page"):
    cmd = ["lp"]
    if printer:
        cmd += ["-d", printer]
    cmd += ["-n", str(int(copies))]
    for opt in shlex.split(options or ""):
        cmd += ["-o", opt]
    cmd.append(path)
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        if r.returncode == 0:
            return True, r.stdout.strip()
        return False, (r.stderr or r.stdout).strip()
    except FileNotFoundError:
        return False, "commande « lp » introuvable (CUPS non installé)"
    except Exception as e:
        return False, str(e)


# ------------------------------------------------------------------ sauvegarde sur clé USB
USB_DIRNAME = "Photobooth"


def find_usb_mount(forced=""):
    """Dossier de la clé USB branchée (inscriptible), ou None."""
    if forced and os.path.isdir(forced) and os.access(forced, os.W_OK):
        return forced
    found = []
    for pattern in ("/media/*/*", "/run/media/*/*", "/media/*", "/mnt/*"):
        for p in glob.glob(pattern):
            if os.path.ismount(p) and os.access(p, os.W_OK):
                found.append(p)
    return sorted(set(found))[0] if found else None


def _safe_copy(src, dst):
    tmp = dst.with_name(dst.name + ".part")
    with open(src, "rb") as fi, open(tmp, "wb") as fo:
        shutil.copyfileobj(fi, fo)
        fo.flush()
        os.fsync(fo.fileno())
    os.replace(tmp, dst)          # le fichier n'apparaît sur la clé que lorsqu'il est complet


def sync_to_usb(mount, local_dir=None):
    """Copie sur la clé les planches et photos individuelles qui n'y sont pas encore. Renvoie le nombre copié."""
    local = Path(local_dir or composer.PHOTO_DIR)
    dest = Path(mount) / USB_DIRNAME
    (dest / "raw").mkdir(parents=True, exist_ok=True)
    copied = 0
    jobs = [(p, dest / p.name) for p in sorted(local.glob("planche_*.jpg"))]
    jobs += [(p, dest / "raw" / p.name) for p in sorted((local / "raw").glob("*.jpg"))]
    for src, dst in jobs:
        if not dst.exists() or dst.stat().st_size != src.stat().st_size:
            _safe_copy(src, dst)
            copied += 1
    return copied


def eject_usb(mount):
    """Démonte la clé proprement. Renvoie (ok, message)."""
    try:
        subprocess.run(["sync"], timeout=120)
        dev = None
        with open("/proc/mounts") as f:
            for line in f:
                parts = line.split()
                if len(parts) > 1 and parts[1].replace("\\040", " ") == mount:
                    dev = parts[0]
        if dev:
            r = subprocess.run(["udisksctl", "unmount", "-b", dev], capture_output=True, text=True, timeout=30)
            if r.returncode == 0:
                return True, "Vous pouvez retirer la clé USB."
        r = subprocess.run(["umount", mount], capture_output=True, text=True, timeout=30)
        if r.returncode == 0:
            return True, "Vous pouvez retirer la clé USB."
        return False, "Éjection impossible : " + (r.stderr.strip() or "clé occupée")
    except Exception as e:
        return False, f"Éjection impossible : {e}"


# ------------------------------------------------------------------ clé USB / réseau
def find_usb_images(limit=60):
    roots = ["/media", "/run/media", "/mnt"]
    found = []
    for root in roots:
        if not os.path.isdir(root):
            continue
        base_depth = root.rstrip("/").count("/")
        for dirpath, dirs, files in os.walk(root):
            if dirpath.count("/") - base_depth >= 3:
                dirs[:] = []
            for f in sorted(files):
                if f.lower().endswith(IMG_EXT) and not f.startswith("."):
                    found.append(os.path.join(dirpath, f))
                    if len(found) >= limit:
                        return found
    return found


def local_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("10.255.255.255", 1))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return None


PAGE = """<!doctype html><html lang="fr"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>Photobooth – nouveau fond</title>
<style>body{font-family:sans-serif;max-width:480px;margin:30px auto;padding:0 16px;text-align:center}
button,input{font-size:18px;margin:12px 0}button{padding:14px 28px;border-radius:10px;border:0;background:#d4af37}
.msg{color:#0a7d33;font-weight:bold}</style></head><body>
<h2>Envoyer un fond</h2><p class="msg"><!--MSG--></p>
<form method="post" action="/upload" enctype="multipart/form-data">
<input type="password" name="pin" inputmode="numeric" placeholder="Code du photobooth" required><br>
<input type="file" name="file" accept="image/*" required><br><button>Envoyer</button></form>
<p>Format idéal : paysage 3:2 (ex. 1800×1200). L'image est recadrée au centre.</p></body></html>"""


def start_web_upload(on_uploaded, check_pin, port=8080):
    """Petit site pour envoyer un fond depuis un téléphone (même réseau Wi-Fi).
    L'envoi exige le code d'accès du photobooth (check_pin(code) -> bool)."""
    try:
        from flask import Flask, request
    except ImportError:
        return None
    logging.getLogger("werkzeug").setLevel(logging.ERROR)
    app = Flask(__name__)
    app.config["MAX_CONTENT_LENGTH"] = 40 * 1024 * 1024

    @app.get("/")
    def index():
        return PAGE

    fails = {"n": 0, "until": 0.0}

    @app.post("/upload")
    def upload():
        if time.time() < fails["until"]:
            return PAGE.replace("<!--MSG-->", "Trop d'essais, patientez une minute."), 429
        if not check_pin(request.form.get("pin", "")):
            fails["n"] += 1
            if fails["n"] >= 5:
                fails["n"], fails["until"] = 0, time.time() + 60
            return PAGE.replace("<!--MSG-->", "Code incorrect (ou aucun code défini sur le photobooth)."), 403
        fails["n"] = 0
        f = request.files.get("file")
        if not f:
            return PAGE.replace("<!--MSG-->", "Aucun fichier reçu."), 400
        try:
            name = composer.import_background(f.stream)
        except Exception:
            return PAGE.replace("<!--MSG-->", "Ce fichier n'est pas une image valide."), 400
        on_uploaded(name)
        return PAGE.replace("<!--MSG-->", "Fond envoyé ✔ Il est déjà sélectionné sur le photobooth.")

    threading.Thread(
        target=lambda: app.run(host="0.0.0.0", port=port, threaded=True, use_reloader=False),
        daemon=True).start()
    return app
