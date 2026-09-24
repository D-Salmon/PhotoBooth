import copy
import os
import queue
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch
from argparse import Namespace
os.environ['SDL_VIDEODRIVER'] = 'dummy'
os.environ['SDL_AUDIODRIVER'] = 'dummy'
import pygame
import composer as C
import hardware as H
from photobooth import App

class RegressionTests(unittest.TestCase):
    def test_invalid_config(self):
        with tempfile.TemporaryDirectory() as d, patch.object(C, 'CONFIG_PATH', Path(d)/'config.json'):
            for value in ('[]', '{"lines":null,"num_photos":"abc"}', '{"lines":[{"color":[1],"size":null,"text":4}]}', '{'):
                C.CONFIG_PATH.write_text(value)
                cfg = C.load_config()
                self.assertEqual(cfg['num_photos'], 3)
                self.assertEqual(len(cfg['lines'][0]['color']), 3)
                C.compose(cfg, [C.make_placeholder(0)])

    def test_guest_gallery_print_config(self):
        with tempfile.TemporaryDirectory() as d, patch.object(C, 'CONFIG_PATH', Path(d)/'config.json'):
            C.CONFIG_PATH.write_text('{"guest_gallery_print":true}')
            self.assertTrue(C.load_config()['guest_gallery_print'])
            C.CONFIG_PATH.write_text('{"guest_gallery_print":"oui"}')
            self.assertFalse(C.load_config()['guest_gallery_print'])

    def test_guest_gallery_print_permission(self):
        app = App.__new__(App)
        app.admin = False
        app.gal_files = ['photo.jpg']
        app.gal_idx = 0
        app.printer_ok = True
        app.cfg = dict(C.DEFAULT_CONFIG)
        app.show_toast = lambda *args: None
        with patch.object(H, 'print_file', return_value=(True, 'OK')) as print_file:
            app.cfg['guest_gallery_print'] = False
            app.gal_print()
            print_file.assert_not_called()
            app.cfg['guest_gallery_print'] = True
            app.gal_print()
            for thread in threading.enumerate():
                if thread is not threading.current_thread():
                    thread.join(1)
            print_file.assert_called_once()

    def test_countdown_selection(self):
        app = App.__new__(App)
        app.cfg = dict(C.DEFAULT_CONFIG)
        app.save = lambda: True
        app.set_countdown(7)
        self.assertEqual(app.cfg['countdown'], 7)
        app.set_countdown(99)
        self.assertEqual(app.cfg['countdown'], 10)

    def test_atomic_config_failure(self):
        with tempfile.TemporaryDirectory() as d, patch.object(C, 'CONFIG_PATH', Path(d)/'config.json'):
            C.CONFIG_PATH.write_text('{"copies":2}')
            with patch.object(C.os, 'replace', side_effect=OSError('disk error')):
                with self.assertRaises(OSError): C.save_config(C.DEFAULT_CONFIG)
            self.assertEqual(C.load_config()['copies'], 2)
            self.assertEqual(len(list(Path(d).iterdir())), 1)

    def test_pin_backspace(self):
        app = App.__new__(App)
        app.pin = dict(purpose='create', digits='', first=None, submit_at=None, msg='')
        for digit in '1234': app.pin_key(digit)
        app.pin_key('EFF')
        self.assertIsNone(app.pin['submit_at'])
        app.pin_submit()
        self.assertIsNone(app.pin['first'])
        with self.assertRaises(ValueError): C.set_pin({}, '123')

    def test_cups_locale(self):
        with patch.object(H.subprocess, 'run') as run:
            run.return_value.returncode = 0
            run.return_value.stdout = 'printer ready'
            run.return_value.stderr = ''
            H._run(['lpstat', '-d'])
            self.assertEqual(run.call_args.kwargs['env']['LC_ALL'], 'C')

    def test_usb_nonblocking(self):
        app = App.__new__(App)
        app.sync_running = app.eject_running = False
        app.usb_mount = '/test'; app.ui_queue = queue.Queue()
        entered, release = threading.Event(), threading.Event()
        def eject(mount):
            entered.set(); release.wait(3); return True, 'OK'
        with patch.object(H, 'eject_usb', side_effect=eject):
            try:
                app.eject_key()
                self.assertTrue(entered.wait(1))
                self.assertTrue(app.eject_running)
                app.start_sync()
                self.assertFalse(app.sync_running)
            finally: release.set()
            app.ui_queue.get(timeout=3)()
        self.assertFalse(app.eject_running)
        self.assertIsNone(app.usb_mount)

    def test_session_save_retry_and_screens(self):
        with tempfile.TemporaryDirectory() as d, patch.object(C, 'PHOTO_DIR', Path(d)), patch.object(C, 'RAW_DIR', Path(d)/'raw'):
            app = App(Namespace(windowed=True, size='1280x800', camera='fake', no_web=True))
            try:
                app.cfg['storage'] = 'local'; app.cfg['print_mode'] = 'off'
                app.update(); app.draw()
                for n in (1, 2, 3):
                    app.cfg['num_photos'] = n
                    app.shots = [app.camera.capture() for _ in range(n)]
                    with patch.object(C, 'save_outputs', side_effect=OSError('disque plein')):
                        app.finish_session()
                    self.assertEqual(app.print_state, 'saveerror')
                    app.result_t0 = 0
                    app.update(); app.draw()
                    self.assertEqual(app.mode, 'result')
                    self.assertEqual(len(app.shots), n)
                    app.finish_session(); app.draw()
                    self.assertEqual(app.print_state, 'saved')
                    self.assertTrue(Path(app.result_path).exists())
                    self.assertEqual(app.result_img.size, C.canvas_size(n))
                app.open_config()
                for tab in ('Fond','Photos','Texte','Stockage','Système'):
                    app.tab = tab; app.draw()
                app.open_gallery(); app.draw()
            finally:
                app.camera.stop(); pygame.quit()

    def test_manual_start_between_photos(self):
        with tempfile.TemporaryDirectory() as d, patch.object(C, 'PHOTO_DIR', Path(d)), patch.object(C, 'RAW_DIR', Path(d)/'raw'):
            app = App(Namespace(windowed=True, size='1280x800', camera='fake', no_web=True))
            try:
                app.cfg['num_photos'] = 3
                app.update()
                app.start_session()
                self.assertEqual(app.phase, 'count')
                app.pending = app.camera.capture(); app.shot_surf = app.shot_display(app.pending)
                app.phase = 'review'
                app.keep_shot()
                self.assertEqual(app.phase, 'ready')      # attend un appui
                app.update(); app.draw()
                self.assertEqual(app.phase, 'ready')
                app.on_down((10, 10))                     # trop tôt : ignoré (anti double appui)
                self.assertEqual(app.phase, 'ready')
                app.ready_t0 -= 1
                app.on_down((10, 10))
                self.assertEqual(app.phase, 'count')
                # dernière photo : pas d'attente, on compose
                app.shots = [app.camera.capture(), app.camera.capture()]
                app.pending = app.camera.capture(); app.phase = 'review'
                app.keep_shot()
                self.assertEqual(app.phase, 'compose')
                # sans appui pendant longtemps : retour accueil
                app.go_home(); app.start_session(); app.phase = 'ready'
                app.ready_t0 = app.last_touch = 0
                app.update()
                self.assertEqual(app.mode, 'home')
            finally:
                app.camera.stop(); pygame.quit()

if __name__ == '__main__': unittest.main()
