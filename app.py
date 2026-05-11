import ctypes
import json
import queue
import sys
import threading
import time
import tkinter as tk
from pathlib import Path
from tkinter import messagebox, ttk

import keyboard
import numpy as np
import pyperclip
import pystray
import requests
import sounddevice as sd
import soundfile as sf
from PIL import Image, ImageDraw

BASE_DIR = Path(__file__).parent
# In a PyInstaller onefile build sys.executable is the .exe itself;
# config.json must live next to it, not inside _MEIPASS.
if getattr(sys, "frozen", False):
    CONFIG_PATH = Path(sys.executable).parent / "config.json"
else:
    CONFIG_PATH = BASE_DIR / "config.json"


def _resource(filename: str) -> Path:
    """Resolve path to a bundled resource (works in PyInstaller onefile and dev)."""
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        return Path(meipass) / filename
    return BASE_DIR / filename


DEFAULT_CONFIG = {
    "whisper_url": "http://localhost:8009/transcribe",
    "language": "de",
    "response_format": "text",
    "sample_rate": 16000,
    "channels": 1,
    "input_device": None,
    "hotkey_keys": ["ctrl", "linke windows"],
    "restore_clipboard": True,
    "audio_filename": "recording.wav",
    "auto_elevate": False,
    "start_with_windows": False,
}


def is_admin():
    try:
        return ctypes.windll.shell32.IsUserAnAdmin()
    except Exception:
        return False


def auto_elevate_if_needed(config):
    if not config.get("auto_elevate", False):
        return

    if is_admin():
        return

    exe = sys.executable
    args = " ".join([f'"{a}"' for a in sys.argv])
    ctypes.windll.shell32.ShellExecuteW(None, "runas", exe, args, None, 1)
    sys.exit(0)


def load_config():
    if not CONFIG_PATH.exists():
        CONFIG_PATH.write_text(json.dumps(DEFAULT_CONFIG, indent=2), encoding="utf-8")

    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)

    merged = DEFAULT_CONFIG.copy()
    merged.update(data)
    return merged


def save_config(data):
    CONFIG_PATH.write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )


class Config:
    def __init__(self):
        self.reload()

    def reload(self):
        data = load_config()
        self.raw = data
        self.whisper_url = data["whisper_url"]
        self.language = data["language"]
        self.response_format = data["response_format"]
        self.sample_rate = int(data["sample_rate"])
        self.channels = int(data["channels"])
        self.input_device = data.get("input_device", None)
        self.hotkey_keys = data["hotkey_keys"]
        self.restore_clipboard = bool(data["restore_clipboard"])
        self.audio_filename = data["audio_filename"]


class Overlay:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("EuroWisprFlow")
        self.root.overrideredirect(True)
        self.root.attributes("-topmost", True)
        self.root.attributes("-alpha", 0.92)

        self.label = tk.Label(
            self.root,
            text="Bereit",
            font=("Segoe UI", 18),
            bg="white",
            fg="#2a671b",
            padx=24,
            pady=14,
        )
        self.root.configure(bg="white")
        self.label.pack()

        icon_path = _resource("tray_icon.png")
        if icon_path.exists():
            try:
                img = tk.PhotoImage(file=str(icon_path))
                self.root.iconphoto(True, img)
            except Exception:
                pass

        self.root.withdraw()

    def show(self, text):
        self.label.config(text=text)
        self.root.update_idletasks()
        width = self.root.winfo_reqwidth()
        height = self.root.winfo_reqheight()
        screen_w = self.root.winfo_screenwidth()
        screen_h = self.root.winfo_screenheight()
        x = (screen_w - width) // 2
        y = screen_h - height - 60
        self.root.geometry(f"+{x}+{y}")
        self.root.deiconify()
        self.root.update()

    def set_text(self, text):
        self.label.config(text=text)
        self.root.update()

    def hide(self):
        self.root.withdraw()
        self.root.update()

    def loop(self):
        self.root.mainloop()


class Recorder:
    def __init__(self, config):
        self.config = config
        self.frames = []
        self.stream = None
        self.recording = False
        self.lock = threading.Lock()

    def _callback(self, indata, frames, time_info, status):
        with self.lock:
            if self.recording:
                self.frames.append(indata.copy())

    def start(self):
        with self.lock:
            self.frames = []
            self.recording = True

        self.stream = sd.InputStream(
            device=self.config.input_device,
            samplerate=self.config.sample_rate,
            channels=self.config.channels,
            dtype="float32",
            callback=self._callback,
        )
        self.stream.start()

    def stop(self):
        with self.lock:
            self.recording = False

        if self.stream:
            self.stream.stop()
            self.stream.close()
            self.stream = None

        audio_path = BASE_DIR / self.config.audio_filename

        with self.lock:
            if not self.frames:
                raise RuntimeError("Keine Audiodaten aufgenommen")
            audio = np.concatenate(self.frames, axis=0)

        sf.write(str(audio_path), audio, self.config.sample_rate)
        return audio_path


class WhisperClient:
    def __init__(self, config):
        self.config = config

    def transcribe(self, audio_path):
        with open(audio_path, "rb") as f:
            response = requests.post(
                self.config.whisper_url,
                files={"file": (audio_path.name, f, "audio/wav")},
                data={
                    "language": self.config.language,
                    "response_format": self.config.response_format,
                },
                timeout=600,
            )

        response.raise_for_status()

        if self.config.response_format == "text":
            return response.text.strip()

        return response.json().get("text", "").strip()


class TextInserter:
    def __init__(self, config):
        self.config = config

    def insert_text(self, text):
        if not text:
            return

        old_clipboard = None
        if self.config.restore_clipboard:
            try:
                old_clipboard = pyperclip.paste()
            except Exception:
                pass

        pyperclip.copy(text)
        time.sleep(0.08)
        keyboard.press_and_release("ctrl+v")
        time.sleep(0.15)

        if self.config.restore_clipboard and old_clipboard is not None:
            pyperclip.copy(old_clipboard)


class SettingsWindow:
    def __init__(self, app):
        self.app = app
        self.win = None

    def open(self):
        if self.win and self.win.winfo_exists():
            self.win.lift()
            return

        cfg = load_config()

        self.win = tk.Toplevel(self.app.overlay.root)
        self.win.title("EuroWisprFlow Einstellungen")
        self.win.geometry("650x430")
        self.win.attributes("-topmost", True)

        frm = ttk.Frame(self.win, padding=16)
        frm.pack(fill="both", expand=True)

        self.url_var = tk.StringVar(value=cfg["whisper_url"])
        self.lang_var = tk.StringVar(value=cfg["language"])
        self.rate_var = tk.StringVar(value=str(cfg["sample_rate"]))
        self.channels_var = tk.StringVar(value=str(cfg["channels"]))
        self.hotkey_var = tk.StringVar(value="+".join(cfg["hotkey_keys"]))
        self.restore_var = tk.BooleanVar(value=cfg["restore_clipboard"])
        self.elevate_var = tk.BooleanVar(value=cfg.get("auto_elevate", False))

        devices = []
        selected_index = 0
        current = cfg.get("input_device", None)

        for i, d in enumerate(sd.query_devices()):
            if d["max_input_channels"] > 0:
                label = f"{i}: {d['name']} ({d['max_input_channels']} ch)"
                devices.append((i, label))
                if current == i:
                    selected_index = len(devices) - 1

        self.devices = devices
        self.device_var = tk.StringVar(
            value=devices[selected_index][1] if devices else ""
        )

        row = 0
        ttk.Label(frm, text="Whisper URL").grid(row=row, column=0, sticky="w")
        ttk.Entry(frm, textvariable=self.url_var, width=70).grid(
            row=row, column=1, sticky="ew", pady=4
        )

        row += 1
        ttk.Label(frm, text="Sprache").grid(row=row, column=0, sticky="w")
        ttk.Entry(frm, textvariable=self.lang_var).grid(
            row=row, column=1, sticky="w", pady=4
        )

        row += 1
        ttk.Label(frm, text="Mikrofon").grid(row=row, column=0, sticky="w")
        ttk.Combobox(
            frm, textvariable=self.device_var, values=[x[1] for x in devices], width=60
        ).grid(row=row, column=1, sticky="ew", pady=4)

        row += 1
        ttk.Label(frm, text="Sample Rate").grid(row=row, column=0, sticky="w")
        ttk.Entry(frm, textvariable=self.rate_var).grid(
            row=row, column=1, sticky="w", pady=4
        )

        row += 1
        ttk.Label(frm, text="Kanäle").grid(row=row, column=0, sticky="w")
        ttk.Entry(frm, textvariable=self.channels_var).grid(
            row=row, column=1, sticky="w", pady=4
        )

        row += 1
        ttk.Label(frm, text="Hotkey").grid(row=row, column=0, sticky="w")
        ttk.Entry(frm, textvariable=self.hotkey_var, width=40).grid(
            row=row, column=1, sticky="w", pady=4
        )
        ttk.Label(frm, text="Beispiel: ctrl+linke windows").grid(
            row=row + 1, column=1, sticky="w"
        )

        row += 2
        ttk.Checkbutton(
            frm,
            text="Clipboard nach Einfügen wiederherstellen",
            variable=self.restore_var,
        ).grid(row=row, column=1, sticky="w")

        row += 1
        ttk.Checkbutton(
            frm,
            text="Beim Start automatisch Admin-Rechte anfordern",
            variable=self.elevate_var,
        ).grid(row=row, column=1, sticky="w")

        row += 1
        btns = ttk.Frame(frm)
        btns.grid(row=row, column=1, sticky="w", pady=18)

        ttk.Button(btns, text="Mikrofon testen", command=self.test_microphone).pack(
            side="left", padx=4
        )
        ttk.Button(btns, text="Whisper testen", command=self.test_whisper).pack(
            side="left", padx=4
        )
        ttk.Button(btns, text="Speichern", command=self.save).pack(side="left", padx=4)
        ttk.Button(btns, text="Schließen", command=self.win.destroy).pack(
            side="left", padx=4
        )

        frm.columnconfigure(1, weight=1)

    def selected_device_id(self):
        label = self.device_var.get()
        for device_id, device_label in self.devices:
            if device_label == label:
                return device_id
        return None

    def save(self):
        cfg = load_config()
        cfg["whisper_url"] = self.url_var.get().strip()
        cfg["language"] = self.lang_var.get().strip()
        cfg["sample_rate"] = int(self.rate_var.get())
        cfg["channels"] = int(self.channels_var.get())
        cfg["input_device"] = self.selected_device_id()
        cfg["hotkey_keys"] = [
            x.strip() for x in self.hotkey_var.get().split("+") if x.strip()
        ]
        cfg["restore_clipboard"] = bool(self.restore_var.get())
        cfg["auto_elevate"] = bool(self.elevate_var.get())

        save_config(cfg)
        self.app.reload_config()
        messagebox.showinfo(
            "Gespeichert", "Einstellungen gespeichert. Hotkey ist sofort aktualisiert."
        )

    def test_microphone(self):
        try:
            device_id = self.selected_device_id()
            samplerate = int(self.rate_var.get())
            channels = int(self.channels_var.get())

            sd.check_input_settings(
                device=device_id, samplerate=samplerate, channels=channels
            )

            self.app.overlay.show("🎙 Mikrofontest 3 Sekunden…")
            audio = sd.rec(
                int(3 * samplerate),
                samplerate=samplerate,
                channels=channels,
                dtype="float32",
                device=device_id,
            )
            sd.wait()

            peak = float(np.max(np.abs(audio))) if audio.size else 0.0
            self.app.overlay.set_text(f"✅ Pegel: {peak:.3f}")
            self.app.overlay.root.after(2000, self.app.overlay.hide)

            if peak < 0.01:
                messagebox.showwarning(
                    "Mikrofontest", f"Sehr niedriger Pegel: {peak:.3f}"
                )
            else:
                messagebox.showinfo(
                    "Mikrofontest", f"Mikrofon funktioniert. Pegel: {peak:.3f}"
                )

        except Exception as e:
            messagebox.showerror("Mikrofontest fehlgeschlagen", str(e))

    def test_whisper(self):
        try:
            device_id = self.selected_device_id()
            samplerate = int(self.rate_var.get())
            channels = int(self.channels_var.get())

            self.app.overlay.show("🎙 Sprich 3 Sekunden…")
            audio = sd.rec(
                int(3 * samplerate),
                samplerate=samplerate,
                channels=channels,
                dtype="float32",
                device=device_id,
            )
            sd.wait()

            test_path = BASE_DIR / "mic_test.wav"
            sf.write(str(test_path), audio, samplerate)

            temp_cfg = Config()
            temp_cfg.whisper_url = self.url_var.get().strip()
            temp_cfg.language = self.lang_var.get().strip()
            temp_cfg.response_format = "text"

            self.app.overlay.set_text("⏳ Whisper-Test…")
            text = WhisperClient(temp_cfg).transcribe(test_path)
            self.app.overlay.set_text("✅ Test fertig")
            self.app.overlay.root.after(1500, self.app.overlay.hide)

            messagebox.showinfo("Whisper-Test", text or "Kein Text erkannt")

        except Exception as e:
            messagebox.showerror("Whisper-Test fehlgeschlagen", str(e))

        finally:
            if "test_path" in dir() and test_path.exists():
                try:
                    test_path.unlink()
                except Exception:
                    pass


class Tray:
    def __init__(self, app):
        self.app = app
        self.icon = None

    def make_image(self):
        icon_path = _resource("tray_icon.png")
        if icon_path.exists():
            return Image.open(icon_path).convert("RGBA")
        # Fallback: generiertes Icon
        image = Image.new("RGB", (64, 64), "black")
        draw = ImageDraw.Draw(image)
        draw.ellipse((12, 8, 52, 48), fill="white")
        draw.rectangle((28, 42, 36, 56), fill="white")
        draw.rectangle((20, 54, 44, 60), fill="white")
        return image

    def run(self):
        menu = pystray.Menu(
            pystray.MenuItem("Einstellungen", lambda: self.app.open_settings()),
            pystray.MenuItem("Mikrofon testen", lambda: self.app.open_settings()),
            pystray.MenuItem("Beenden", lambda: self.app.quit()),
        )
        self.icon = pystray.Icon(
            "EuroWisprFlow", self.make_image(), "EuroWisprFlow", menu
        )
        self.icon.run()

    def stop(self):
        if self.icon:
            self.icon.stop()


class App:
    def __init__(self):
        raw_cfg = load_config()
        auto_elevate_if_needed(raw_cfg)

        self.config = Config()
        self.overlay = Overlay()
        self.recorder = Recorder(self.config)
        self.client = WhisperClient(self.config)
        self.inserter = TextInserter(self.config)
        self.settings = SettingsWindow(self)
        self.tray = Tray(self)

        self.is_recording = False
        self.is_busy = False
        self.event_queue = queue.Queue()
        self.running = True

    def reload_config(self):
        self.config.reload()
        self.recorder = Recorder(self.config)
        self.client = WhisperClient(self.config)
        self.inserter = TextInserter(self.config)

    def hotkey_pressed(self):
        _ALIASES = {"left windows": "linke windows", "linke windows": "left windows"}

        def is_key_pressed(k):
            try:
                if keyboard.is_pressed(k):
                    return True
            except Exception:
                pass
            try:
                if keyboard.is_pressed(_ALIASES.get(k.lower(), k)):
                    return True
            except Exception:
                pass
            return False

        try:
            return all(is_key_pressed(k) for k in self.config.hotkey_keys)
        except Exception:
            return False

    def monitor_hotkey(self):
        was_pressed = False
        while self.running:
            pressed = self.hotkey_pressed()

            if pressed and not was_pressed:
                self.event_queue.put("start")

            if not pressed and was_pressed:
                self.event_queue.put("stop")

            was_pressed = pressed
            time.sleep(0.03)

    def process_events(self):
        try:
            while True:
                event = self.event_queue.get_nowait()
                if event == "start":
                    self.start_recording()
                elif event == "stop":
                    self.stop_recording()
                elif event == "settings":
                    self.settings.open()
                elif event == "quit":
                    self._quit_mainthread()
        except queue.Empty:
            pass

        if self.running:
            self.overlay.root.after(50, self.process_events)

    def start_recording(self):
        if self.is_recording or self.is_busy:
            return

        try:
            self.is_recording = True
            self.recorder.start()
            self.overlay.show("🎙 Aufnahme läuft…")
        except Exception as e:
            self.is_recording = False
            self.overlay.show(f"Fehler: {e}")
            self.overlay.root.after(2500, self.overlay.hide)

    def stop_recording(self):
        if not self.is_recording:
            return

        self.is_recording = False
        self.is_busy = True
        self.overlay.set_text("⏳ Transkribiere…")
        threading.Thread(target=self.transcribe_and_insert, daemon=True).start()

    def transcribe_and_insert(self):
        audio_path = None
        try:
            audio_path = self.recorder.stop()
            text = self.client.transcribe(audio_path)

            if text:
                self.overlay.set_text("✅ Füge Text ein…")
                time.sleep(0.1)
                self.inserter.insert_text(text)
                self.overlay.set_text("✅ Fertig")
            else:
                self.overlay.set_text("⚠ Kein Text erkannt")

        except Exception as e:
            self.overlay.set_text(f"Fehler: {e}")

        finally:
            if audio_path and audio_path.exists():
                try:
                    audio_path.unlink()
                except Exception:
                    pass
            self.is_busy = False
            self.overlay.root.after(1500, self.overlay.hide)

    def open_settings(self):
        self.event_queue.put("settings")

    def quit(self):
        self.event_queue.put("quit")

    def _quit_mainthread(self):
        self.running = False
        try:
            self.tray.stop()
        except Exception:
            pass
        self.overlay.root.quit()
        self.overlay.root.destroy()

    def run(self):
        threading.Thread(target=self.monitor_hotkey, daemon=True).start()
        threading.Thread(target=self.tray.run, daemon=True).start()
        self.overlay.root.after(50, self.process_events)
        self.overlay.loop()


if __name__ == "__main__":
    print("Starte EuroWisprFlow…")
    App().run()
