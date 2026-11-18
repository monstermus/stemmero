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
import tempfile
import time
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from ctypes import wintypes

import numpy as np
import sounddevice as sd

from warning_audio import WarningAudio, SOUND_KEYS, SPOKEN_MESSAGES, default_sound, import_custom_sound, wav_duration
from microphone_selection import build_input_devices, choose_input_device, windows_input_signature, windows_capture_device_ids
from parental_pin import PinStore
from parental_ui import ParentControls
from warning_policy import PolicyConfig, WarningPolicy, WindowsActions

APP_NAME = "Stemmero"
APP_VERSION = "1.2.2"
POLICY_ACTION_LABELS = {"lock": "Lås skærmen", "shutdown": "Sluk computeren"}
POLICY_MODE_LABELS = {"all": "Alle farver", "orange_red": "Kun orange og rød"}
CONFIG_DIR = os.path.join(os.environ.get("APPDATA", os.path.expanduser("~")), APP_NAME)
CONFIG_PATH = os.path.join(CONFIG_DIR, "config.json")

DB_MIN = -60.0

DEFAULTS = {
    "device_label": None,
    "device_mode": "auto",
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
    "policy_enabled": False,
    "policy_count": 5,
    "policy_minutes": 10,
    "policy_action": "lock",
    "policy_mode": "all",
    "policy_countdown": 60,
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
    for key, choices in (("device_mode", ("auto", "manual")),
                         ("policy_action", ("lock", "shutdown")),
                         ("policy_mode", ("all", "orange_red"))):
        if cfg[key] not in choices:
            cfg[key] = DEFAULTS[key]
    cfg["policy_count"] = max(1, min(1000, cfg["policy_count"]))
    cfg["policy_minutes"] = max(1, min(1440, cfg["policy_minutes"]))
    cfg["policy_countdown"] = max(0, min(300, cfg["policy_countdown"]))
    return cfg


def save_config(cfg):
    temporary = None
    try:
        os.makedirs(CONFIG_DIR, exist_ok=True)
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=CONFIG_DIR, delete=False) as f:
            temporary = f.name
            json.dump(cfg, f, indent=2, ensure_ascii=False)
            f.flush()
            os.fsync(f.fileno())
        os.replace(temporary, CONFIG_PATH)
        return True
    except OSError:
        return False
    finally:
        if temporary and os.path.exists(temporary):
            try:
                os.unlink(temporary)
            except OSError:
                pass


# ---------------------------------------------------------------- lyd ind
def input_devices():
    """Liste af (index, label) for alle mikrofoner."""
    return build_input_devices(sd.query_devices(), sd.query_hostapis())


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
            stream, self.stream = self.stream, None
            try:
                stream.stop()
            except Exception:
                pass
            try:
                stream.close()
            except Exception:
                pass
        with self.lock:
            self.blocks.clear()

    def running(self):
        try:
            return self.stream is not None and bool(self.stream.active)
        except (sd.PortAudioError, OSError):
            return False

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
        self.root.protocol("WM_DELETE_WINDOW", self.hide_settings)

        self.mic = MicListener()
        self.audio = WarningAudio()
        self.warning_gate = WarningGate()
        self.overlay = Overlay(self.root)

        self.current = -1           # aktuelt advarselsniveau (-1 = ingen)
        self.last_at_level = 0.0    # sidst niveauet stadig var nået
        self.last_sound = {}         # niveau -> tidspunkt
        self.test_until = 0.0
        self.preview_until = 0.0

        self.next_retry = 0.0
        self.next_device_check = 0.0
        self.last_device_refresh = time.monotonic()
        self.device_signature = windows_input_signature()
        self.selected_device = None
        self.input_endpoint_ids = None
        self.settings_states = {}
        self.parent_dialog_open = False
        self.pending_window = None
        self.pin_store = PinStore(os.path.join(CONFIG_DIR, "parental-pin.json"))
        self.parents = ParentControls(self.root, self.pin_store, self._unlock_settings, self._lock_settings)
        self.parents.frame.pack(fill="x", padx=12, pady=(8, 0))

        self._build_ui()
        self._capture_settings_states(self.settings_frame)
        self._lock_settings()
        history_path = os.path.join(CONFIG_DIR, "warning-history.json")
        protected = self.pin_store.configured and not self.pin_store.damaged
        self.policy = WarningPolicy(history_path, None if os.path.exists(history_path) else self._policy_config(),
                                    executor=WindowsActions() if protected else None)
        saved_rule = self.policy.config
        self.cfg.update(policy_enabled=saved_rule.enabled, policy_count=saved_rule.count,
                        policy_minutes=max(1, saved_rule.window_seconds // 60), policy_action=saved_rule.action,
                        policy_mode=saved_rule.mode, policy_countdown=saved_rule.countdown_seconds)
        self._sync_form_values()
        self._start_selected_device()
        self.root.bind("<FocusOut>", self._focus_out, add="+")
        self.root.bind("<Unmap>", self._unmap, add="+")
        self.root.bind("<KeyPress>", self._touch_settings, add="+")
        self.root.bind("<ButtonPress>", self._touch_settings, add="+")
        if "--minimized" in sys.argv:
            self.root.iconify()
        self.root.after(self.POLL_MS, self._tick)

    # ---------- UI
    def _build_ui(self):
        pad = {"padx": 10, "pady": 4}
        outer = ttk.Frame(self.root, padding=12)
        outer.pack(fill="both", expand=True)
        self.settings_frame = outer
        tabs = ttk.Notebook(outer)
        tabs.pack(fill="both", expand=True)
        main = ttk.Frame(tabs, padding=8)
        tabs.add(main, text="Mikrofon og grænser")

        ttk.Label(main, text="Mikrofon:").grid(row=0, column=0, sticky="w", **pad)
        try:
            self.devices = input_devices()
        except sd.PortAudioError:
            self.devices = []
        labels = [lbl for _, lbl in self.devices]
        self.device_var = tk.StringVar(value=self._pick_default_device(labels))
        mic_line = ttk.Frame(main)
        mic_line.grid(row=0, column=1, columnspan=3, sticky="we", **pad)
        cb = ttk.Combobox(mic_line, textvariable=self.device_var, values=labels,
                          state="readonly", width=44)
        self.device_combo = cb
        cb.pack(side="left")
        cb.bind("<<ComboboxSelected>>", self._manual_device_selected)
        self.auto_device_var = tk.BooleanVar(value=self.cfg["device_mode"] == "auto")
        ttk.Checkbutton(mic_line, text="Vælg automatisk", variable=self.auto_device_var,
                        command=self._change_device_mode).pack(side="left", padx=(8, 0))

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
        hold.bind("<FocusOut>", self._apply_hold)
        hold.bind("<Return>", self._apply_hold)

        sounds = ttk.Frame(tabs, padding=12)
        tabs.add(sounds, text="Advarselslyde")
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
        ttk.Button(sounds, text="Stop lyd", command=self._stop_preview).grid(
            row=4, column=0, columnspan=2, sticky="w", pady=(8, 0))

        btns = ttk.Frame(main)
        btns.grid(row=7, column=0, columnspan=4, sticky="we", pady=(10, 0))
        ttk.Button(btns, text="Test bannere", command=self._test).pack(side="left", padx=6)
        self.status = ttk.Label(btns, text="", foreground="#555555", wraplength=500)
        self.status.pack(side="left", padx=12)

        ttk.Label(main, foreground="#666666", text=(
            "Tip: tal normalt og se hvor bjælken ligger. Sæt gul lidt over det. "
            "Spil i 'borderless/vindue', ikke eksklusiv fuldskærm."
        ), wraplength=650).grid(row=8, column=0, columnspan=4, sticky="w", pady=(10, 0))
        self._build_policy_ui(tabs)

    def _refresh_sound_label(self, key):
        custom = self.cfg[f"sound_{key}"]
        self.sound_labels[key].config(text="Egen WAV-fil" if custom else SPOKEN_MESSAGES[key])
        editable = self._parent_session_open()
        self.sound_reset_buttons[key].config(state="normal" if custom and editable else "disabled")

    def _choose_sound(self, key):
        if not self._require_parent():
            return
        self.parent_dialog_open = True
        try:
            selected = filedialog.askopenfilename(
                parent=self.root, title=f"Vælg lyd til {dict(zip(SOUND_KEYS, ('gul', 'orange', 'rød')))[key]}",
                filetypes=[("WAV-lydfiler", "*.wav"), ("Alle filer", "*.*")])
        finally:
            self.parent_dialog_open = False
        if not selected or not self._require_parent():
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
        if not self._require_parent():
            return
        self.audio.stop()
        self._set(f"sound_{key}", "")
        self._refresh_sound_label(key)
        self.audio_note.set("Den danske standardstemme er gendannet.")

    def _preview_sound(self, key):
        if not self._require_parent():
            return
        self.audio.play(key, self.cfg[f"sound_{key}"], preview=True)
        until = getattr(self.audio, "until", 0.0)
        self.preview_until = max(time.monotonic(), until if type(until) in (int, float) else 0.0) + 0.5
        self.audio_note.set(self.audio.last_error or "Afspiller den valgte lyd. Brug Stop lyd for at afbryde.")

    def _stop_preview(self):
        if self._require_parent():
            self.audio.stop()
            self.preview_until = time.monotonic() + 0.5

    def _parent_session_open(self):
        parents = getattr(self, 'parents', None)
        return bool(parents and parents.unlocked and time.monotonic() < parents.unlocked_until)

    def _require_parent(self):
        if self._parent_session_open():
            return True
        parents = getattr(self, 'parents', None)
        if parents is not None and parents.unlocked:
            parents.lock()
        return False

    def _capture_settings_states(self, widget):
        for child in widget.winfo_children():
            if isinstance(child, (ttk.Button, ttk.Checkbutton, ttk.Combobox, ttk.Spinbox, ttk.Entry, tk.Scale)):
                self.settings_states[child] = str(child.cget('state'))
            self._capture_settings_states(child)

    def _sync_form_values(self):
        for key, var in self.sliders.items():
            var.set(self.cfg[key])
        for name, key in (('active_var', 'active'), ('sound_var', 'sound'),
                          ('pos_var', 'position'), ('hold_var', 'hold_ms')):
            getattr(self, name).set(self.cfg[key])
        self.auto_device_var.set(self.cfg['device_mode'] == 'auto')
        for key, var in self.policy_vars.items():
            labels = POLICY_ACTION_LABELS if key == 'policy_action' else POLICY_MODE_LABELS if key == 'policy_mode' else {}
            var.set(labels.get(self.cfg[key], self.cfg[key]))

    def _lock_settings(self):
        for widget in getattr(self, 'settings_states', {}):
            widget.configure(state='disabled')
        if hasattr(self, 'sliders'):
            self._sync_form_values()

    def _unlock_settings(self):
        for widget, state in self.settings_states.items():
            widget.configure(state=state)
        for key in SOUND_KEYS:
            self._refresh_sound_label(key)
        self.device_combo.configure(state='readonly' if self.cfg['device_mode'] == 'manual' else 'disabled')

    def _touch_settings(self, _event=None):
        if self._parent_session_open():
            self.parents.unlocked_until = time.monotonic() + 120

    def _focus_out(self, _event=None):
        self.root.after(150, self._lock_if_unfocused)

    def _lock_if_unfocused(self):
        if not self.parents.busy and not self.parent_dialog_open and self.root.focus_displayof() is None:
            self.parents.lock()

    def _unmap(self, event):
        if event.widget == self.root and self.root.state() in ('iconic', 'withdrawn'):
            self.parents.lock()

    def hide_settings(self):
        self.parents.lock()
        self.root.iconify()

    def _pick_default_device(self, labels):
        selected = self._input_choice()
        return selected[1] if selected else ''

    def _input_choice(self):
        try:
            default = sd.default.device[0]
        except (sd.PortAudioError, IndexError):
            default = None
        if getattr(self, 'input_endpoint_ids', None) is None:
            mapping = windows_capture_device_ids(getattr(sd, '_libname', None), [index for index, _ in self.devices])
            self.input_endpoint_ids = mapping if mapping is not None else {}
        signature = getattr(self, 'device_signature', None)
        return choose_input_device(
            self.devices, default, self.cfg.get('device_label'), self.cfg['device_mode'],
            windows_default_id=signature[0] if signature is not None else None,
            endpoint_ids=self.input_endpoint_ids,
            active_endpoint_ids=signature[1] if signature is not None else None,
        )

    def _manual_device_selected(self, _event=None):
        if not self._require_parent() or self.cfg['device_mode'] != 'manual':
            return
        self._set('device_label', self.device_var.get())
        self._start_selected_device()

    def _change_device_mode(self):
        if not self._require_parent():
            return
        self._set('device_mode', 'auto' if self.auto_device_var.get() else 'manual')
        self.device_combo.configure(state='disabled' if self.auto_device_var.get() else 'readonly')
        self._start_selected_device()

    def _reconnect(self):
        self.mic.stop()
        self.selected_device = None
        self.input_endpoint_ids = None
        self.warning_gate = WarningGate()
        sd._terminate()
        sd._initialize()
        self.last_device_refresh = time.monotonic()
        self.devices = input_devices()
        self.device_combo.configure(values=[label for _, label in self.devices])
        self._start_selected_device()

    def _start_selected_device(self):
        selected = self._input_choice()
        if selected is None:
            self.mic.stop()
            self.selected_device = None
            self.device_var.set('')
            self.status.configure(text='Ingen mikrofon fundet. Prøver automatisk igen ...')
            return
        index, label = selected
        self.device_var.set(label)
        if selected == self.selected_device and self.mic.running():
            return
        try:
            self.mic.start(index)
            self.selected_device = selected
            prefix = 'Automatisk' if self.cfg['device_mode'] == 'auto' else 'Lytter'
            self.status.configure(text=f'{prefix}: {label}')
        except (sd.PortAudioError, OSError) as error:
            self.selected_device = None
            self.status.configure(text=f'Kunne ikke åbne mikrofonen: {error}')

    def _check_microphone(self, now):
        if now < self.next_device_check:
            return
        self.next_device_check = now + 2
        signature = windows_input_signature()
        changed = signature is not None and signature != self.device_signature
        if signature is not None:
            self.device_signature = signature
        unavailable = not self.mic.running()
        # En COM-fejl må ikke afbryde en rask lydstrøm ved hvert tjek.
        if changed or unavailable and now >= self.next_retry:
            self.next_retry = now + 5
            try:
                self._reconnect()
            except (sd.PortAudioError, OSError) as error:
                self.status.configure(text=f'Venter på mikrofon ... ({error})')

    def _apply_hold(self, _event=None):
        if not self._require_parent():
            return
        try:
            value = max(100, min(2000, int(self.hold_var.get())))
        except (ValueError, tk.TclError):
            value = self.cfg['hold_ms']
        self.hold_var.set(value)
        self._set('hold_ms', value)

    def _build_policy_ui(self, tabs):
        panel = ttk.Frame(tabs, padding=12)
        tabs.add(panel, text='Gentagne advarsler')
        self.policy_vars = {
            key: (tk.BooleanVar(value=self.cfg[key]) if key == 'policy_enabled' else tk.StringVar(value=(POLICY_ACTION_LABELS if key == 'policy_action' else POLICY_MODE_LABELS if key == 'policy_mode' else {}).get(self.cfg[key], self.cfg[key])))
            for key in ('policy_enabled', 'policy_count', 'policy_minutes', 'policy_action', 'policy_mode', 'policy_countdown')
        }
        ttk.Checkbutton(panel, text='Aktivér konsekvens efter gentagne advarsler',
                        variable=self.policy_vars['policy_enabled']).grid(row=0, column=0, columnspan=2, sticky='w', pady=8)
        for row, (key, label, maximum) in enumerate((('policy_count', 'Antal advarsler', 1000),
                                                    ('policy_minutes', 'Inden for minutter', 1440),
                                                    ('policy_countdown', 'Nedlukning efter sekunder, 0 = straks', 300)), start=1):
            ttk.Label(panel, text=label).grid(row=row, column=0, sticky='w', padx=(0, 16), pady=6)
            minimum = 0 if key == 'policy_countdown' else 1
            ttk.Spinbox(panel, from_=minimum, to=maximum, textvariable=self.policy_vars[key], width=8).grid(row=row, column=1, sticky='w')
        for row, (key, label, values) in enumerate((('policy_action', 'Handling', tuple(POLICY_ACTION_LABELS.values())),
                                                   ('policy_mode', 'Advarsler der tælles', tuple(POLICY_MODE_LABELS.values()))), start=4):
            ttk.Label(panel, text=label).grid(row=row, column=0, sticky='w', pady=6)
            ttk.Combobox(panel, textvariable=self.policy_vars[key], values=values, state='readonly', width=18).grid(row=row, column=1, sticky='w')
        ttk.Label(panel, text='0 sekunder betyder nedlukning straks uden nedtælling. Ved en positiv tid kan en voksen annullere nedtællingen med PIN.',
                  wraplength=620).grid(row=6, column=0, columnspan=2, sticky='w', pady=(8, 0))
        ttk.Label(panel, text='Et sammenhængende udbrud tæller én gang. Tælleren og en nedtælling bevares ved genstart. Nedlukning tvinger ikke åbne programmer til at lukke.',
                  wraplength=620).grid(row=7, column=0, columnspan=2, sticky='w', pady=8)
        ttk.Button(panel, text='Gem regel', command=self._save_policy).grid(row=8, column=0, sticky='w', pady=8)
        ttk.Button(panel, text='Nulstil tæller med PIN', command=self._cancel_policy).grid(row=8, column=1, sticky='w')
        self.policy_note = tk.StringVar(value='Konsekvenser er slået fra, indtil en voksen aktiverer og gemmer reglen.')
        ttk.Label(panel, textvariable=self.policy_note, wraplength=620).grid(row=9, column=0, columnspan=2, sticky='w', pady=8)

    def _policy_config(self):
        enabled = self.cfg['policy_enabled'] and self.pin_store.configured and not self.pin_store.damaged
        return PolicyConfig(enabled=bool(enabled), count=self.cfg['policy_count'],
                            window_seconds=self.cfg['policy_minutes'] * 60, action=self.cfg['policy_action'],
                            countdown_seconds=self.cfg['policy_countdown'], mode=self.cfg['policy_mode'],
                            quiet_seconds=max(0.1, self.cfg['release_ms'] / 1000))

    def _save_policy(self):
        if not self._require_parent():
            return
        old = dict(self.cfg)
        try:
            for key, var in self.policy_vars.items():
                value = var.get()
                if key in ('policy_action', 'policy_mode'):
                    labels = POLICY_ACTION_LABELS if key == 'policy_action' else POLICY_MODE_LABELS
                    value = {label: code for code, label in labels.items()}[value]
                self.cfg[key] = value if key in ('policy_enabled', 'policy_action', 'policy_mode') else int(value)
            if not 0 <= self.cfg['policy_countdown'] <= 300:
                raise ValueError('Angiv 0 til 300 sekunder. 0 betyder straks.')
            config = self._policy_config()
            self.policy.configure(config)
            self.policy.executor = WindowsActions() if self.pin_store.configured and not self.pin_store.damaged else None
            if not save_config(self.cfg):
                self.policy_note.set('Reglen er gemt, men de øvrige indstillinger kunne ikke gemmes.')
                return
        except (ValueError, KeyError, OSError, RuntimeError, tk.TclError) as error:
            self.cfg = old
            self.policy_note.set(f'Reglen kunne ikke gemmes: {error}')
            return
        self.policy_note.set('Reglen er gemt.')

    def _cancel_policy(self):
        if self.pending_window is not None:
            self.pending_window.attributes('-topmost', False)
        self.root.deiconify()
        self.root.lift()
        try:
            if not self.parents.fresh_auth():
                return
            self.policy.cancel()
            self.policy_note.set('Tælleren og den ventende handling er nulstillet med PIN.')
        except (OSError, RuntimeError) as error:
            self.policy_note.set(str(error))
        finally:
            if self.pending_window is not None:
                self.pending_window.attributes('-topmost', True)

    def _show_policy_status(self):
        status = self.policy.status
        if status.error:
            self.policy_note.set(status.error)
        elif status.pending_action:
            label = 'Nedlukning' if status.pending_action == 'shutdown' else 'Skærmlås'
            self.policy_note.set(f'{label} om {status.remaining_seconds} sekunder. Annullering kræver PIN.')
        elif self.policy.config.enabled:
            self.policy_note.set(f'{status.count} af {self.policy.config.count} advarsler i de seneste {self.cfg["policy_minutes"]} minutter.')
        else:
            self.policy_note.set('Konsekvenser er slået fra.')
        if status.pending_action and not status.action_failed and status.pending_action == 'shutdown':
            if self.pending_window is None:
                self.pending_window = tk.Toplevel(self.root)
                self.pending_window.title('Stemmero: nedlukning')
                self.pending_window.attributes('-topmost', True)
                self.pending_window.protocol('WM_DELETE_WINDOW', lambda: None)
                self.pending_text = tk.StringVar()
                ttk.Label(self.pending_window, textvariable=self.pending_text, padding=20, wraplength=420).pack()
                ttk.Button(self.pending_window, text='Annullér med PIN', command=self._cancel_policy).pack(pady=(0, 20))
            self.pending_text.set(f'Computeren anmodes om at slukke om {status.remaining_seconds} sekunder.\nEn voksen kan annullere med PIN.')
        elif self.pending_window is not None:
            self.pending_window.destroy()
            self.pending_window = None

    def _set(self, key, value):
        if not self._require_parent():
            return
        self.cfg[key] = value
        if key in ("sound", "active") and not value:
            self.audio.stop()
        if not save_config(self.cfg):
            self.audio_note.set('Indstillingerne kunne ikke gemmes. Kontrollér adgang til programmets datamappe.')

    def _test(self):
        if not self._require_parent():
            return
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
        self._check_microphone(now)
        if self.parents.unlocked and now >= self.parents.unlocked_until:
            self.parents.lock()
        if now >= getattr(self, 'next_parent_refresh', 0):
            self.next_parent_refresh = now + 1
            self.parents.refresh()
            if self.pin_store.damaged or not self.pin_store.configured:
                self.policy.executor = None
        hold = self.cfg['hold_ms']
        monitoring = self.mic.running() and self.cfg['active']

        meter_db = self.mic.level_db(80)
        self._draw_meter(meter_db)

        raw_level = self._classify(meter_db) if monitoring else -1
        held_level = self.warning_gate.update(raw_level, now, max(100, min(2000, hold)))
        try:
            self.policy.observe(held_level, monitoring=monitoring,
                                test=now < self.test_until or now < getattr(self, 'preview_until', 0), quiet=raw_level < 0)
            self.policy.tick()
        except (OSError, RuntimeError) as error:
            self.policy_note.set(str(error))
        self._show_policy_status()

        if now < self.test_until:
            # gennemløb gul -> orange -> rød på 3 sek.
            level = min(2, int((3.0 - (self.test_until - now)) / 1.0))
        elif now < getattr(self, 'preview_until', 0):
            level = -1
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
        if not self.cfg["sound"] or now < self.test_until or now < getattr(self, 'preview_until', 0):
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


def already_running(name="Stemmero"):
    """Sørger for at der kun kører én Stemmero ad gangen."""
    global _MUTEX
    if sys.platform != "win32":
        return False
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.CreateMutexW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR]
    k32.CreateMutexW.restype = wintypes.HANDLE
    _MUTEX = k32.CreateMutexW(None, False, f"Local\\{name}")
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
    if "--watchdog" in sys.argv:
        from watchdog import child_command, supervise
        if already_running("Stemmero-Watchdog"):
            sys.exit(0)
        supervise(child_command(sys.executable, os.path.abspath(__file__)),
                  os.path.join(CONFIG_DIR, "supervisor.stop"))
        sys.exit(0)
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
