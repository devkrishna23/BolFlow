"""System tray icon: shows the app is alive, offers Pause and Quit.

pystray runs its own win32 message loop in a daemon thread; menu callbacks
only flip flags on the app or schedule the Tk shutdown - no direct Tk calls.
"""

import os
import subprocess
import threading

import pystray
from PIL import Image, ImageDraw

import config

# label -> Saaras output mode; switching applies from the next utterance
_MODES = [
    ("Hinglish (romanized)", "translit"),
    ("Mixed script", "codemix"),
    ("Native script (Devanagari)", "transcribe"),
    ("Translate to English", "translate"),
]


def mic_image(size: int = 64) -> Image.Image:
    ico = os.path.join(config.RESOURCE_DIR, "app.ico")
    if os.path.exists(ico):
        img = Image.open(ico)
        img.size = max(img.info.get("sizes", {(64, 64)}))  # largest layer
        return img.convert("RGBA").resize((size, size), Image.LANCZOS)
    # fallback if app.ico is missing: hand-drawn tricolor mic
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.ellipse([2, 2, size - 2, size - 2], fill="#111114")
    d.rounded_rectangle([25, 12, 39, 36], radius=7, fill="#ff9933")
    d.arc([18, 20, 46, 46], 0, 180, fill="#ff9933", width=4)
    d.line([32, 46, 32, 51], fill="#ff9933", width=4)
    d.line([24, 52, 40, 52], fill="#138808", width=4)
    return img


def start_tray(app) -> pystray.Icon:
    def toggle_pause(icon, item):
        app.paused = not app.paused

    def quit_app(icon, item):
        icon.visible = False
        app.quit()

    def set_mode(mode):
        def cb(icon, item):
            config.SARVAM_MODE = mode
            # persist, and keep the settings window's file in sync
            import json
            data = {}
            try:
                with open(config.SETTINGS_PATH, encoding="utf-8") as f:
                    data = json.load(f)
            except (OSError, ValueError):
                pass
            data["SARVAM_MODE"] = mode
            with open(config.SETTINGS_PATH, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
        return cb

    def open_settings(icon, item):
        subprocess.Popen(config.tool_command("settings"),
                         cwd=config.RESOURCE_DIR)

    def open_log(icon, item):
        path = os.path.join(config.DATA_DIR, "bolflow.log")
        if not os.path.exists(path):   # console runs don't create the log
            open(path, "a", encoding="utf-8").close()
        os.startfile(path)

    mode_menu = pystray.Menu(*[
        pystray.MenuItem(label, set_mode(mode), radio=True,
                         checked=lambda item, m=mode: config.SARVAM_MODE == m)
        for label, mode in _MODES
    ])

    icon = pystray.Icon(
        "bolflow", mic_image(), "BolFlow dictation",
        pystray.Menu(
            pystray.MenuItem("Pause dictation", toggle_pause,
                             checked=lambda item: app.paused),
            pystray.MenuItem("Settings", open_settings),
            pystray.MenuItem("Output style", mode_menu),
            pystray.MenuItem("Open log", open_log),
            pystray.MenuItem("Quit", quit_app),
        ),
    )
    threading.Thread(target=icon.run, daemon=True).start()
    return icon
