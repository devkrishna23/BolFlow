"""Settings for the dictation app.

Defaults live here; user overrides live in settings.json (written by the
settings window, `settings.py`). The running app reloads settings.json
automatically within ~2 s of a change - no restart needed (except the
microphone device, which applies on the next mic reopen/app start).
"""

# --- Hotkey ---------------------------------------------------------------
# Push-to-talk: hold to record, release to transcribe + paste.
# A two-key chord (hold BOTH; releasing either stops): avoids the Windows
# Sticky Keys popup that repeated Shift presses trigger, and two modifiers
# held together type nothing and fire no app shortcuts.
# Accepts a single pynput key name ("ctrl_r", "f9", "pause", ...) or a
# tuple of two to require them held together. Avoid shift_l/shift_r.
HOTKEY = ("ctrl_l", "alt_l")

# --- Audio ----------------------------------------------------------------
MIC_DEVICE = None            # None = system default; or a device-name string
                             # (sounddevice matches it as a substring)
SAMPLE_RATE = 16000          # 16 kHz mono is what the STT API expects
PRE_ROLL_SECONDS = 0.3       # audio kept from *before* the key-press, so the
                             # first word isn't clipped by stream start-up
MIN_UTTERANCE_SECONDS = 0.4  # shorter than this = accidental tap, discard

# --- Speech-to-text (Sarvam API) ------------------------------------------
import os
SARVAM_API_KEY = os.environ.get("SARVAM_API_KEY", "")
SARVAM_MODEL = "saaras:v3"
# Output mode for Indian-language / mixed speech:
#   "translit"   - everything romanized: Hindi comes out as Hinglish (default;
#                  measured 2026-07-21: "codemix" produced Devanagari)
#   "codemix"    - mixed script (Hindi in Devanagari, English in English)
#   "transcribe" - native script (Hindi -> Devanagari)
#   "translate"  - everything translated to English
#   "verbatim"   - word-for-word, fillers kept (rarely wanted)
SARVAM_MODE = "translit"
SARVAM_LANGUAGE = "unknown"  # auto-detect among 22 Indian languages
SARVAM_TIMEOUT = 30.0        # seconds; a hung request must not wedge the app
# Stream audio over the WebSocket while speaking: the transcript is mostly
# ready at key-release (only the last VAD segment still processes). Falls
# back to the one-shot REST call automatically if a session fails.
SARVAM_STREAMING = True

# --- HUD ------------------------------------------------------------------
SHOW_LIVE_TRANSCRIPT = True  # word-by-word transcript card while dictating

# --- Injection ------------------------------------------------------------
CLIPBOARD_RESTORE_DELAY = 0.6  # seconds after Ctrl+V before restoring the
                               # old clipboard (apps may read it lazily)

# --- Paths (dev: project folder; installed exe: APPDATA + install dir) ------
import sys
FROZEN = bool(getattr(sys, "frozen", False))
if FROZEN:
    # Program Files is not writable - user data goes to %APPDATA%\BolFlow
    DATA_DIR = os.path.join(os.environ.get("APPDATA", "."), "BolFlow")
    os.makedirs(DATA_DIR, exist_ok=True)
    RESOURCE_DIR = os.path.dirname(sys.executable)   # app.ico etc.
else:
    DATA_DIR = os.path.dirname(os.path.abspath(__file__))
    RESOURCE_DIR = DATA_DIR

# --- User overrides (settings.json, written by settings.py) ----------------
SETTINGS_PATH = os.path.join(DATA_DIR, "settings.json")


def tool_command(name):
    """Command list to launch a companion window ('settings'/'onboarding')
    as its own process - a sibling exe when installed, the .py in dev."""
    if FROZEN:
        exe = {"settings": "BolFlow-Settings.exe",
               "onboarding": "BolFlow-Onboarding.exe"}[name]
        return [os.path.join(RESOURCE_DIR, exe)]
    return [sys.executable, os.path.join(RESOURCE_DIR, f"{name}.py")]
_USER_KEYS = ("HOTKEY", "SARVAM_MODE", "MIC_DEVICE", "SHOW_LIVE_TRANSCRIPT")


def load_user_settings():
    """Overlay settings.json onto this module. Called at import and again
    by the app whenever the file changes on disk."""
    import json
    try:
        with open(SETTINGS_PATH, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return
    g = globals()
    for key in _USER_KEYS:
        if key in data:
            g[key] = tuple(data[key]) if key == "HOTKEY" \
                and isinstance(data[key], list) else data[key]
    # API key from onboarding; the SARVAM_API_KEY env var wins if set
    if data.get("SARVAM_API_KEY") and not os.environ.get("SARVAM_API_KEY"):
        g["SARVAM_API_KEY"] = data["SARVAM_API_KEY"]


load_user_settings()
