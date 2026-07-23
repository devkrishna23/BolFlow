"""BolFlow - voice dictation for Bharat. Hold a hotkey, speak (in any of 22
Indian languages, English, or code-mixed Hinglish), release: clean text
appears at the cursor. A personal productivity/accessibility tool; STT runs
on Sarvam AI's Saaras model over their API (needs SARVAM_API_KEY).

Run:  pythonw app.py  (no console - the normal way, via the app shortcut)
      python app.py   (with console, for debugging)
Stop: the tray icon's Quit menu (or Ctrl+C when run with a console).
"""

import os
import queue
import sys
import threading
import time

import config

# Under pythonw / the windowed exe there is no console; log to a file in
# the writable data dir (APPDATA when installed, project folder in dev).
if sys.stdout is None or sys.stderr is None:
    _log = open(os.path.join(config.DATA_DIR, "bolflow.log"),
                "a", buffering=1, encoding="utf-8")
    sys.stdout = sys.stderr = _log

# Single-instance guard: a second copy (double-click, startup folder + manual
# launch, ...) would double-record and double-paste every utterance. A bound
# localhost socket is a reliable cross-process lock (the OS releases it if
# the process dies, and unlike GetLastError it can't be clobbered by ctypes).
import socket
_instance_lock = socket.socket()
try:
    _instance_lock.bind(("127.0.0.1", 47821))
except OSError:
    print("BolFlow is already running - this second instance will exit.")
    sys.exit(0)

import pyperclip
from pynput import keyboard

import cleaner
import injector
import tray
from audio_capture import MicStream
from hud import Hud


def resolve_hotkey(name: str):
    try:
        return getattr(keyboard.Key, name)
    except AttributeError:
        return keyboard.KeyCode.from_char(name)


def ensure_onboarded() -> bool:
    """First run: no API key -> open the onboarding window and wait for the
    key to land in settings.json (the window stays open for its live-test
    step while we continue booting). False = user closed it without a key."""
    if config.SARVAM_API_KEY:
        return True
    import subprocess
    proc = subprocess.Popen(config.tool_command("onboarding"),
                            cwd=config.RESOURCE_DIR)
    while True:
        time.sleep(1)
        config.load_user_settings()
        if config.SARVAM_API_KEY:
            return True
        if proc.poll() is not None:
            return False


class App:
    def __init__(self):
        from transcriber import Transcriber, StreamingTranscriber
        self.stt = Transcriber()  # raises with a clear message if no API key
        self.streamer = None
        if config.SARVAM_STREAMING:
            try:
                self.streamer = StreamingTranscriber()
            except Exception as e:
                print(f"  [streaming unavailable, using REST: {e}]")
        self.session = None       # live StreamingSession while recording
        print(f"Sarvam STT ready: {config.SARVAM_MODEL} "
              f"mode={config.SARVAM_MODE} "
              f"({'streaming' if self.streamer else 'REST'})")
        self.mic = MicStream()
        self.hud = Hud(level_source=lambda: self.mic.level)
        self.hud.on_cancel = self._cancel_dictation  # click the card = cancel
        names = config.HOTKEY if isinstance(config.HOTKEY, (tuple, list)) \
            else (config.HOTKEY,)
        self.chord = frozenset(resolve_hotkey(n) for n in names)
        self._held = set()               # chord keys currently down
        self.recording = False           # also debounces key auto-repeat
        self.paused = False              # toggled from the tray menu
        self.jobs = queue.Queue()        # utterances process sequentially
        threading.Thread(target=self._worker, daemon=True).start()
        threading.Thread(target=self._watch_settings, daemon=True).start()

    def _watch_settings(self):
        """Hot-reload settings.json (written by the settings window)."""
        last = None
        while True:
            try:
                mtime = os.path.getmtime(config.SETTINGS_PATH)
            except OSError:
                mtime = None
            if mtime != last:
                if last is not None:
                    config.load_user_settings()
                    names = config.HOTKEY \
                        if isinstance(config.HOTKEY, (tuple, list)) \
                        else (config.HOTKEY,)
                    self.chord = frozenset(resolve_hotkey(n) for n in names)
                    print(f"(settings reloaded: hotkey "
                          f"{'+'.join(names)}, mode {config.SARVAM_MODE})")
                last = mtime
            time.sleep(2)

    # --- hotkey (pynput listener thread) -----------------------------------
    def _on_press(self, key):
        if key in self.chord and not self.paused:
            self._held.add(key)
            if self._held == self.chord and not self.recording:
                self.recording = True
                if self.streamer:
                    try:
                        self.session = self.streamer.start_session()
                    except Exception as e:
                        print(f"  [streaming session failed, REST it is: {e}]")
                        self.session = None
                self.mic.start_recording(
                    chunk_sink=self.session.feed if self.session else None)
                self.stt.warm()          # keep the REST fallback path warm too
                self.hud.text_source = self.session.live_text \
                    if self.session and config.SHOW_LIVE_TRANSCRIPT else None
                self.hud.state = "recording"
        elif key == keyboard.Key.esc and self.recording:
            self._cancel_dictation()

    def _cancel_dictation(self):
        """Discard the in-flight utterance: paste nothing. Esc or card-click."""
        if not self.recording:
            return
        self.recording = False
        self.mic.stop_recording()
        if self.session:
            self.session.cancel()
            self.session = None
        self.hud.text_source = None
        self.hud.state = "idle"

    def _on_release(self, key):
        if key in self.chord:
            self._held.discard(key)      # releasing either chord key stops
            if self.recording:
                self.recording = False
                audio = self.mic.stop_recording()
                session, self.session = self.session, None
                target = injector.focused_window()  # paste goes here, not
                                                    # wherever focus drifts to
                self.hud.state = "processing"
                self.jobs.put((audio, session, target, time.perf_counter()))

    # --- pipeline (worker thread) -------------------------------------------
    def _worker(self):
        while True:
            audio, session, target, t_release = self.jobs.get()
            try:
                self._process(audio, session, target, t_release)
            except Exception as e:
                print(f"  [pipeline error: {e}]")
                self.hud.state = "error"  # red flash: nothing was pasted
            # _process sets "done" on success (the HUD flashes green and
            # hides itself); only clear a leftover "processing" state, and
            # don't clobber "recording" if the user is already speaking again
            if not self.recording:
                self.hud.text_source = None
            if self.jobs.empty() and not self.recording \
                    and self.hud.state == "processing":
                self.hud.state = "idle"

    def _process(self, audio, session, target, t_release):
        seconds = len(audio) / config.SAMPLE_RATE
        if seconds < config.MIN_UTTERANCE_SECONDS:  # accidental chord tap
            if session is not None:
                session.cancel()
            return
        raw, langs, engine = "", set(), "ws"
        if session is not None:
            try:
                raw, langs = session.finish()
            except Exception as e:
                print(f"  [streaming failed, falling back to REST: {e}]")
                session = None
        if session is None:
            engine = "rest"
            raw = self.stt.transcribe(audio)
            langs = {self.stt.last_language} if self.stt.last_language else set()
        t_stt = time.perf_counter()
        if not raw:
            print(f"({seconds:.1f}s audio: no speech detected)")
            return
        text = cleaner.light_clean(raw)
        t_llm = time.perf_counter()
        # Never paste while the user is already dictating the next utterance:
        # the held chord would corrupt the synthetic Ctrl+V into Ctrl+Alt+V.
        deadline = time.perf_counter() + 10.0
        while self.recording and time.perf_counter() < deadline:
            time.sleep(0.05)
        if self.recording:
            pyperclip.copy(text)
            print("  [still dictating after 10s - text left on the clipboard]")
            return
        pasted = injector.paste_at_cursor(text, target)
        t_paste = time.perf_counter()
        if pasted:
            if self.hud.state == "processing":
                self.hud.state = "done"
        else:
            self.hud.state = "error"  # focus lost: text is on the clipboard
        print(f"[{seconds:4.1f}s audio, {'+'.join(sorted(langs)) or '??'}, "
              f"{engine}] stt {t_stt - t_release:.2f}s | "
              f"cleanup {t_llm - t_stt:.2f}s | paste {t_paste - t_llm:.2f}s | "
              f"total {t_paste - t_release:.2f}s\n"
              f"  raw   -> {raw}\n  final -> {text}")

    def quit(self):
        self.hud.stop()  # ends the Tk main loop; run() then cleans up

    def run(self):
        listener = keyboard.Listener(on_press=self._on_press,
                                     on_release=self._on_release)
        listener.start()
        icon = tray.start_tray(self)
        chord = " + ".join(config.HOTKEY) \
            if isinstance(config.HOTKEY, (tuple, list)) else config.HOTKEY
        print(f"\nReady. Hold [{chord}] and speak; release to paste. "
              f"Quit from the tray icon.")
        try:
            self.hud.run()  # Tk main loop (blocks)
        except KeyboardInterrupt:
            pass
        finally:
            icon.stop()
            listener.stop()
            self.mic.close()


if __name__ == "__main__":
    if not ensure_onboarded():
        print("Onboarding closed without an API key - nothing to run. "
              "Start BolFlow again to retry.")
        sys.exit(0)
    App().run()
