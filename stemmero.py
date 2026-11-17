"""
Stemmero advarer, når du taler for højt i headsettet.

Programmet måler mikrofonens lydniveau og viser en gul, orange eller rød
advarsel, hvis du taler for højt i længere tid end reaktionstiden.

Kun Windows.  Kræver:  pip install sounddevice numpy
"""
import collections
import ctypes
import json
import math
import os
import sys
import threading
import time
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from ctypes import wintypes

import numpy as np
import sounddevice as sd

from warning_audio import WarningAudio, SOUND_KEYS, SPOKEN_MESSAGES, default_sound, import_custom_sound, wav_duration

APP_NAME = "Stemmero"
APP_VERSION = "1.1.0"
CONFIG_DIR = os.path.join(os.environ.get("APPDATA", os.path.expanduser("~")), APP_NAME)
CONFIG_PATH = os.path.join(CONFIG_DIR, "config.json")

DB_MIN = -60.0

DEFAULTS = {
    "device_label": None,
    "yellow": -24.0,
    "orange": -17.0,
    "red": -10.0,
    "hold_ms": 350,       # hvor længe der skal tales højt før der advares
    "release_ms": 1200,   # hvor længe advarslen bliver hængende
    "sound": True,
    "sound_yellow": "",
    "sound_orange": "",
    "sound_red": "",
    "cooldown_s": 4.0,    # mindste tid mellem lyde på samme niveau
    "position": "Top",
    "active": True,
}

# (nøgle, tekst, farve)
LEVELS = [
    ("yellow", "Lidt højt", "#FFD400"),
    ("orange", "Du taler for højt", "#FF8A00"),
    ("red", "ALT FOR HØJT!", "#FF2A2A"),
]


# ---------------------------------------------------------------- config
def load_config():
    cfg = dict(DEFAULTS)
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            stored = json.load(f)
            if isinstance(stored, dict):
                for key, default in DEFAULTS.items():
                    value = stored.get(key, default)
                    if default is None:
                        if value is None or isinstance(value, str):
                            cfg[key] = value
                    elif type(value) is type(default):
                        cfg[key] = value
                    elif type(default) is float and type(value) is int:
                        cfg[key] = float(value)
    except (OSError, ValueError):
        pass
    for key in ("yellow", "orange", "red"):
        if not math.isfinite(cfg[key]):
            cfg[key] = DEFAULTS[key]
        cfg[key] = max(DB_MIN, min(0.0, cfg[key]))
    cfg["yellow"], cfg["orange"], cfg["red"] = sorted(
        cfg[key] for key in ("yellow", "orange", "red")
    )
    cfg["hold_ms"] = max(100, min(2000, cfg["hold_ms"]))
    cfg["release_ms"] = max(0, min(10000, cfg["release_ms"]))
    if not math.isfinite(cfg["cooldown_s"]):
        cfg["cooldown_s"] = DEFAULTS["cooldown_s"]
    cfg["cooldown_s"] = max(0.5, min(60.0, cfg["cooldown_s"]))
    if cfg["position"] not in ("Top", "Midt", "Bund"):
        cfg["position"] = DEFAULTS["position"]
    return cfg


def save_config(cfg):
    try:
        os.makedirs(CONFIG_DIR, exist_ok=True)
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=2, ensure_ascii=False)
    except OSError:
        pass


# ---------------------------------------------------------------- lyd ind
def input_devices():
    """Liste af (index, label) for alle mikrofoner."""
    apis = sd.query_hostapis()
    out = []
    for i, d in enumerate(sd.query_devices()):
        if d["max_input_channels"] > 0:
            out.append((i, f'{d["name"]}  [{apis[d["hostapi"]]["name"]}]'))
    return out


class MicListener:
    """Læser mikrofonen og gemmer energien for hver lille blok (20 ms)."""

    def __init__(self):
        self.stream = None
        self.blocks = collections.deque(maxlen=500)  # (tid, middel-kvadrat)
        self.lock = threading.Lock()

    def _callback(self, indata, frames, t, status):
        ms = float(np.mean(np.square(indata[:, 0], dtype=np.float64)))
        with self.lock:
            self.blocks.append((time.monotonic(), ms))

    def start(self, device):
        self.stop()
        info = sd.query_devices(device, "input")
        sr = int(info["default_samplerate"])
        self.stream = sd.InputStream(
            device=device, channels=1, samplerate=sr,
            blocksize=max(256, int(sr * 0.02)), dtype="float32",
            callback=self._callback,
        )
        self.stream.start()

    def stop(self):
        if self.stream is not None:
            try:
                self.stream.stop()
                self.stream.close()
            except Exception:
                pass
            self.stream = None
        with self.lock:
            self.blocks.clear()

    def level_db(self, window_ms):
        """Gennemsnitligt niveau (dBFS) over de sidste window_ms."""
        cutoff = time.monotonic() - window_ms / 1000.0
        with self.lock:
            vals = [ms for (t, ms) in self.blocks if t >= cutoff]
        if not vals:
            return DB_MIN
        mean = sum(vals) / len(vals)
        if mean <= 1e-12:
            return DB_MIN
        return max(DB_MIN, min(0.0, 10.0 * math.log10(mean)))


# ---------------------------------------------------------------- overlay
def windows_user32():
    """Brug pointerstore vindueshåndtag på både 32-bit og 64-bit Windows."""
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    user32.GetParent.argtypes = [wintypes.HWND]
    user32.GetParent.restype = wintypes.HWND
    user32.FindWindowW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR]
    user32.FindWindowW.restype = wintypes.HWND
    user32.GetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int]
    user32.GetWindowLongW.restype = wintypes.LONG
    user32.SetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int, wintypes.LONG]
    user32.SetWindowLongW.restype = wintypes.LONG
    user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
    user32.SetForegroundWindow.argtypes = [wintypes.HWND]
    return user32


def make_click_through(win):
    """Gør vinduet gennemsigtigt for klik og holder det ude af Alt+Tab."""
    if sys.platform != "win32":
        return
    win.update_idletasks()
    user32 = windows_user32()
    hwnd = user32.GetParent(win.winfo_id()) or win.winfo_id()
    GWL_EXSTYLE = -20
    WS_EX_LAYERED = 0x00080000
    WS_EX_TRANSPARENT = 0x00000020
    WS_EX_TOOLWINDOW = 0x00000080
    WS_EX_NOACTIVATE = 0x08000000
    style = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
    user32.SetWindowLongW(
        hwnd, GWL_EXSTYLE,
        style | WS_EX_LAYERED | WS_EX_TRANSPARENT | WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE,
    )


class Overlay:
    def __init__(self, root):
        self.win = tk.Toplevel(root)
        self.win.title("Stemmero overlay")
        self.win.overrideredirect(True)
        self.win.attributes("-topmost", True)
        self.win.attributes("-alpha", 0.9)
        self.win.configure(bg="#111111")
        self.frame = tk.Frame(self.win, bg="#FFD400", padx=6, pady=6)
        self.frame.pack(fill="both", expand=True)
        self.label = tk.Label(
            self.frame, text="", font=("Segoe UI", 30, "bold"),
            fg="#111111", bg="#FFD400", padx=48, pady=16,
        )
        self.label.pack(fill="both", expand=True)
        self.win.withdraw()
        self.visible = False
        self._click_through = False

    def show(self, text, color, position):
        self.label.config(text=text, bg=color)
        self.frame.config(bg=color)
        self.win.update_idletasks()
        w, h = self.win.winfo_reqwidth(), self.win.winfo_reqheight()
        sw, sh = self.win.winfo_screenwidth(), self.win.winfo_screenheight()
        x = (sw - w) // 2
        y = {"Top": 40, "Midt": (sh - h) // 2}.get(position, sh - h - 90)
        self.win.geometry(f"{w}x{h}+{x}+{y}")
        if not self.visible:
            self.win.deiconify()
            self.visible = True
        if not self._click_through:
            make_click_through(self.win)
            self._click_through = True
        self.win.attributes("-topmost", True)
        self.win.lift()

    def hide(self):
        if self.visible:
            self.win.withdraw()
            self.visible = False


# ---------------------------------------------------------------- app
class WarningGate:
    """Kræv et vedvarende niveau før en advarsel eller en optrapning."""

    def __init__(self):
        self.since = [None] * len(LEVELS)

    def update(self, level, now, hold_ms):
        result = -1
        for i in range(len(LEVELS)):
            if level < i:
                self.since[i] = None
            else:
                if self.since[i] is None:
                    self.since[i] = now
                if now - self.since[i] >= hold_ms / 1000.0:
                    result = i
        return result


class App:
    POLL_MS = 40

    def __init__(self):
        self.cfg = load_config()
        self.root = tk.Tk()
        self.root.title(APP_NAME)
        self.root.resizable(False, False)
        self.root.protocol("WM_DELETE_WINDOW", self.quit)

        self.mic = MicListener()
        self.audio = WarningAudio()
        self.warning_gate = WarningGate()
        self.overlay = Overlay(self.root)

        self.current = -1           # aktuelt advarselsniveau (-1 = ingen)
        self.last_at_level = 0.0    # sidst niveauet stadig var nået
        self.last_sound = {}         # niveau -> tidspunkt
        self.test_until = 0.0

        self.next_retry = 0.0

        self._build_ui()
        self._start_selected_device()
        if "--minimized" in sys.argv:
            self.root.iconify()
        self.root.after(self.POLL_MS, self._tick)

    # ---------- UI
    def _build_ui(self):
        pad = {"padx": 10, "pady": 4}
        main = ttk.Frame(self.root, padding=12)
        main.pack(fill="both", expand=True)

        ttk.Label(main, text="Mikrofon:").grid(row=0, column=0, sticky="w", **pad)
        try:
            self.devices = input_devices()
        except sd.PortAudioError:
            self.devices = []
        labels = [lbl for _, lbl in self.devices]
        self.device_var = tk.StringVar(value=self._pick_default_device(labels))
        cb = ttk.Combobox(main, textvariable=self.device_var, values=labels,
                          state="readonly", width=58)
        self.device_combo = cb
        cb.grid(row=0, column=1, columnspan=3, sticky="we", **pad)
        cb.bind("<<ComboboxSelected>>", lambda e: self._start_selected_device())

        ttk.Label(main, text="Niveau nu:").grid(row=1, column=0, sticky="w", **pad)
        self.meter = tk.Canvas(main, width=440, height=30, bg="#222222",
                               highlightthickness=0)
        self.meter.grid(row=1, column=1, columnspan=3, sticky="w", **pad)

        self.sliders = {}
        for r, (key, text, color) in enumerate(LEVELS, start=2):
            lbl = tk.Label(main, text=f"  {text}  ", bg=color, fg="#111111",
                           font=("Segoe UI", 9, "bold"))
            lbl.grid(row=r, column=0, sticky="w", **pad)
            var = tk.DoubleVar(value=self.cfg[key])
            s = tk.Scale(main, from_=DB_MIN, to=0, resolution=1, orient="horizontal",
                         variable=var, length=440, showvalue=True,
                         command=lambda v, k=key: self._set(k, float(v)))
            s.grid(row=r, column=1, columnspan=3, sticky="w", **pad)
            self.sliders[key] = var

        opts = ttk.Frame(main)
        opts.grid(row=5, column=0, columnspan=4, sticky="we", pady=(8, 0))

        self.active_var = tk.BooleanVar(value=self.cfg["active"])
        ttk.Checkbutton(opts, text="Aktiv", variable=self.active_var,
                        command=lambda: self._set("active", self.active_var.get())
                        ).pack(side="left", padx=6)

        self.sound_var = tk.BooleanVar(value=self.cfg["sound"])
        ttk.Checkbutton(opts, text="Afspil lyd", variable=self.sound_var,
                        command=lambda: self._set("sound", self.sound_var.get())
                        ).pack(side="left", padx=6)

        ttk.Label(opts, text="Placering:").pack(side="left", padx=(16, 4))
        self.pos_var = tk.StringVar(value=self.cfg["position"])
        pos = ttk.Combobox(opts, textvariable=self.pos_var, values=["Top", "Midt", "Bund"],
                           state="readonly", width=6)
        pos.pack(side="left")
        pos.bind("<<ComboboxSelected>>", lambda e: self._set("position", self.pos_var.get()))

        ttk.Label(opts, text="Reaktionstid (ms):").pack(side="left", padx=(16, 4))
        self.hold_var = tk.IntVar(value=self.cfg["hold_ms"])
        hold = ttk.Spinbox(opts, from_=100, to=2000, increment=50, width=6,
                           textvariable=self.hold_var,
                           command=lambda: self._set("hold_ms", self.hold_var.get()))
        hold.pack(side="left")

        sounds = ttk.LabelFrame(main, text="Advarselslyde", padding=8)
        sounds.grid(row=6, column=0, columnspan=4, sticky="we", pady=(12, 0))
        sounds.columnconfigure(1, weight=1)
        self.sound_labels = {}
        self.sound_reset_buttons = {}
        for row, (key, name) in enumerate(zip(SOUND_KEYS, ("Gul", "Orange", "Rød"))):
            ttk.Label(sounds, text=name).grid(row=row, column=0, sticky="w", padx=(0, 12), pady=4)
            label = ttk.Label(sounds, wraplength=300)
            label.grid(row=row, column=1, sticky="w", padx=(0, 8), pady=4)
            self.sound_labels[key] = label
            ttk.Button(sounds, text="Vælg WAV...", command=lambda k=key: self._choose_sound(k)).grid(
                row=row, column=2, padx=4, pady=4)
            ttk.Button(sounds, text="Afspil", command=lambda k=key: self._preview_sound(k)).grid(
                row=row, column=3, padx=4, pady=4)
            reset = ttk.Button(sounds, text="Gendan", command=lambda k=key: self._reset_sound(k))
            reset.grid(row=row, column=4, padx=(4, 0), pady=4)
            self.sound_reset_buttons[key] = reset
            self._refresh_sound_label(key)
        self.audio_note = tk.StringVar(value="Dansk tale følger med. Egne lyde skal være WAV, højst 30 sekunder og 10 MB.")
        ttk.Label(sounds, textvariable=self.audio_note, wraplength=650).grid(
            row=3, column=0, columnspan=5, sticky="w", pady=(8, 0))
        ttk.Button(sounds, text="Stop lyd", command=self.audio.stop).grid(
            row=4, column=0, columnspan=2, sticky="w", pady=(8, 0))

        btns = ttk.Frame(main)
        btns.grid(row=7, column=0, columnspan=4, sticky="we", pady=(10, 0))
        ttk.Button(btns, text="Test bannere", command=self._test).pack(side="left", padx=6)
        self.status = ttk.Label(btns, text="", foreground="#666666")
        self.status.pack(side="left", padx=12)

        ttk.Label(main, foreground="#666666", text=(
            "Tip: tal normalt og se hvor bjælken ligger. Sæt gul lidt over det. "
            "Spil i 'borderless/vindue', ikke eksklusiv fuldskærm."
        ), wraplength=650).grid(row=8, column=0, columnspan=4, sticky="w", pady=(10, 0))

    def _refresh_sound_label(self, key):
        custom = self.cfg[f"sound_{key}"]
        self.sound_labels[key].config(text="Egen WAV-fil" if custom else SPOKEN_MESSAGES[key])
        self.sound_reset_buttons[key].config(state="normal" if custom else "disabled")

    def _choose_sound(self, key):
        selected = filedialog.askopenfilename(
            parent=self.root, title=f"Vælg lyd til {dict(zip(SOUND_KEYS, ('gul', 'orange', 'rød')))[key]}",
            filetypes=[("WAV-lydfiler", "*.wav"), ("Alle filer", "*.*")])
        if not selected:
            return
        self.audio.stop()
        try:
            imported = import_custom_sound(selected, key, CONFIG_DIR)
        except (OSError, ValueError) as error:
            self.audio_note.set(str(error))
            messagebox.showerror("Lyden kunne ikke vælges", str(error), parent=self.root)
            return
        self._set(f"sound_{key}", imported)
        self._refresh_sound_label(key)
        self.audio_note.set(f"Valgt: {os.path.basename(selected)}. En kopi er gemt med dine indstillinger.")

    def _reset_sound(self, key):
        self.audio.stop()
        self._set(f"sound_{key}", "")
        self._refresh_sound_label(key)
        self.audio_note.set("Den danske standardstemme er gendannet.")

    def _preview_sound(self, key):
        self.audio.play(key, self.cfg[f"sound_{key}"], preview=True)
        self.audio_note.set(self.audio.last_error or "Afspiller den valgte lyd. Brug Stop lyd for at afbryde.")

    def _pick_default_device(self, labels):
        saved = self.cfg.get("device_label")
        if saved in labels:
            return saved
        for lbl in labels:
            if "headset" in lbl.lower():
                return lbl
        try:
            default_idx = sd.default.device[0]
            for i, lbl in self.devices:
                if i == default_idx:
                    return lbl
        except Exception:
            pass
        return labels[0] if labels else ""

    def _reconnect(self):
        """Headset taget ud/sat i: genindlæs enheder og prøv igen."""
        self.mic.stop()
        try:
            sd._terminate()
            sd._initialize()
        except Exception:
            pass
        self.devices = input_devices()
        labels = [lbl for _, lbl in self.devices]
        self.device_combo.config(values=labels)
        saved = self.cfg.get("device_label")
        if saved in labels:
            self.device_var.set(saved)
        elif labels and self.device_var.get() not in labels:
            self.device_var.set(self._pick_default_device(labels))
        self._start_selected_device()

    def _start_selected_device(self):
        label = self.device_var.get()
        idx = next((i for i, lbl in self.devices if lbl == label), None)
        if idx is None:
            self.status.config(text="Ingen mikrofon fundet. prøver igen ...")
            return
        try:
            self.mic.start(idx)
            self.cfg["device_label"] = label
            save_config(self.cfg)
            self.status.config(text="Lytter ...")
        except Exception as e:
            self.status.config(text=f"Kunne ikke åbne mikrofonen: {e}")

    def _set(self, key, value):
        self.cfg[key] = value
        if key in ("sound", "active") and not value:
            self.audio.stop()
        save_config(self.cfg)

    def _test(self):
        self.audio.stop()
        self.test_until = time.monotonic() + 3.0

    # ---------- logik
    def _classify(self, db):
        idx = -1
        for i, (key, *_rest) in enumerate(LEVELS):
            if db >= self.cfg[key]:
                idx = i
        return idx

    def _tick(self):
        now = time.monotonic()
        stream = self.mic.stream
        if (stream is None or not stream.active) and now >= self.next_retry:
            self.next_retry = now + 5.0
            try:
                self._reconnect()
            except Exception as e:
                self.status.config(text=f"Venter på mikrofon ... ({e})")
        try:
            hold = int(self.hold_var.get())
        except (tk.TclError, ValueError):
            hold = self.cfg["hold_ms"]
        self.cfg["hold_ms"] = hold

        meter_db = self.mic.level_db(80)
        self._draw_meter(meter_db)

        raw_level = self._classify(meter_db) if self.cfg["active"] else -1
        held_level = self.warning_gate.update(raw_level, now, max(100, min(2000, hold)))

        if now < self.test_until:
            # gennemløb gul -> orange -> rød på 3 sek.
            level = min(2, int((3.0 - (self.test_until - now)) / 1.0))
        elif self.cfg["active"]:
            level = held_level
        else:
            level = -1

        if level > self.current:                      # stiger: advar med det samme
            self.current = level
            self.last_at_level = now
            self._alert(level, now, force_sound=True)
        elif level >= 0 and level == self.current:   # holder niveauet
            self.last_at_level = now
            self._alert(level, now, force_sound=False)
        elif now - self.last_at_level > self.cfg["release_ms"] / 1000.0:
            self.current = level                      # falder efter et øjeblik
            if level >= 0:
                self.last_at_level = now
                self._alert(level, now, force_sound=False)
            else:
                self.overlay.hide()

        self.root.after(self.POLL_MS, self._tick)

    def _alert(self, level, now, force_sound):
        key, text, color = LEVELS[level]
        self.overlay.show(text, color, self.cfg["position"])
        if not self.cfg["sound"] or now < self.test_until:
            return
        last = self.last_sound.get(level, 0.0)
        if force_sound or now - last >= self.cfg["cooldown_s"]:
            self.audio.play(key, self.cfg[f"sound_{key}"])
            self.last_sound[level] = now
            if self.audio.last_error:
                self.audio_note.set(self.audio.last_error)

    def _draw_meter(self, db):
        c = self.meter
        c.delete("all")
        w, h = int(c["width"]), int(c["height"])

        def x(v):
            return int((v - DB_MIN) / (0 - DB_MIN) * w)

        lvl = self._classify(db)
        fill = LEVELS[lvl][2] if lvl >= 0 else "#3DBE5A"
        c.create_rectangle(0, 0, x(db), h, fill=fill, width=0)
        for key, _t, color in LEVELS:
            xx = x(self.cfg[key])
            c.create_line(xx, 0, xx, h, fill=color, width=2)
        c.create_text(w - 6, h // 2, text=f"{db:5.1f} dB", anchor="e",
                      fill="#FFFFFF", font=("Consolas", 10))

    def quit(self):
        save_config(self.cfg)
        self.audio.stop()
        self.mic.stop()
        self.root.destroy()

    def run(self):
        self.root.mainloop()


_MUTEX = None


def already_running():
    """Sørger for at der kun kører én Stemmero ad gangen."""
    global _MUTEX
    if sys.platform != "win32":
        return False
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.CreateMutexW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR]
    k32.CreateMutexW.restype = wintypes.HANDLE
    _MUTEX = k32.CreateMutexW(None, False, "Local\\Stemmero")
    if not _MUTEX:
        raise ctypes.WinError(ctypes.get_last_error())
    return ctypes.get_last_error() == 183  # ERROR_ALREADY_EXISTS


def smoke_test():
    """Kontrollér den pakkede app uden mikrofonoptagelse eller autostart."""
    root = tk.Tk()
    root.withdraw()
    overlay = Overlay(root)
    overlay.show("Test", LEVELS[0][2], "Top")
    root.update()
    overlay.hide()
    try:
        devices = len(input_devices())
    except sd.PortAudioError:
        devices = 0
    report = {"app": APP_NAME, "version": APP_VERSION, "microphones": devices,
              "numpy": np.__version__, "sounddevice": sd.__version__, "ok": True}
    report["sounds"] = {key: wav_duration(default_sound(key)) for key in SOUND_KEYS}
    with open("smoke-test.json", "w", encoding="utf-8") as f:
        json.dump(report, f)
    root.destroy()


if __name__ == "__main__":
    if "--smoke-test" in sys.argv:
        smoke_test()
        sys.exit(0)
    if already_running():
        # Kører allerede (fx startet fra Start-menuen): vis det åbne vindue
        if "--minimized" not in sys.argv:
            u32 = windows_user32()
            hwnd = u32.FindWindowW("TkTopLevel", APP_NAME)
            if hwnd:
                u32.ShowWindow(hwnd, 9)  # SW_RESTORE
                u32.SetForegroundWindow(hwnd)
        sys.exit(0)
    if sys.platform == "win32":
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except Exception:
            pass
    App().run()
