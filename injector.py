"""Paste text at the cursor of the focused app via clipboard + Ctrl+V.

This is standard dictation-software behavior (Dragon, Wispr Flow, Windows
Voice Access all inject text the same way). Per-keystroke SendInput is
unreliable in terminals, so clipboard-paste is the dependable path.

Handles the sharp edges:
- captures the target window at hotkey release; if focus moved during
  processing it re-focuses the target before pasting (or aborts safely),
- waits for the user's physically-held modifiers to lift so they can't
  combine with the simulated Ctrl+V,
- saves and restores the previous *text* clipboard after a delay (apps may
  read the clipboard lazily). A non-text clipboard (image/files) cannot be
  restored with this stack - documented v1 trade-off.
"""

import ctypes
import threading
import time

import pyperclip
from pynput.keyboard import Controller, Key

import config

_user32 = ctypes.windll.user32
_kb = Controller()
_restore_timer = None

# virtual-key codes: L/R shift, L/R ctrl, L/R alt, L/R win. The push-to-talk
# chord keys are deliberately NOT excluded: pasting while they are held would
# turn Ctrl+V into Ctrl+Alt+V in the target app. The worker defers pasting
# until recording has stopped, so this wait only covers the release residue.
_MODIFIER_VKS = [0xA0, 0xA1, 0xA2, 0xA3, 0xA4, 0xA5, 0x5B, 0x5C]


def focused_window() -> int:
    return _user32.GetForegroundWindow()


def _wait_modifiers_released(timeout: float = 1.5) -> None:
    deadline = time.perf_counter() + timeout
    while time.perf_counter() < deadline:
        if all(not (_user32.GetAsyncKeyState(vk) & 0x8000) for vk in _MODIFIER_VKS):
            return
        time.sleep(0.02)


def paste_at_cursor(text: str, target_hwnd: int) -> bool:
    """Paste text into the target window. Returns False if focus was lost
    and could not be recovered (text is left on the clipboard)."""
    if _user32.GetForegroundWindow() != target_hwnd:
        _user32.SetForegroundWindow(target_hwnd)
        time.sleep(0.15)
        if _user32.GetForegroundWindow() != target_hwnd:
            pyperclip.copy(text)
            print("  [focus changed during processing - text is on the clipboard, press Ctrl+V]")
            return False

    global _restore_timer
    if _restore_timer is not None:
        _restore_timer.cancel()   # a pending restore must not clobber this paste

    previous = pyperclip.paste()  # '' if clipboard held non-text content
    pyperclip.copy(text)
    _wait_modifiers_released()
    time.sleep(0.05)  # let the clipboard update settle

    _kb.press(Key.ctrl)
    _kb.press("v")
    _kb.release("v")
    _kb.release(Key.ctrl)

    if previous:
        # restore off the critical path: the target app reads the clipboard
        # within ~the delay, and blocking here would hold up the HUD's
        # "done" flash and the next utterance by 0.6 s. The restore is
        # conditional - if a newer paste already replaced the clipboard,
        # restoring `previous` over it would destroy that utterance
        # (Timer.cancel() can't stop a timer that is already firing).
        def _restore(expected=text, prev=previous):
            if pyperclip.paste() == expected:
                pyperclip.copy(prev)
        _restore_timer = threading.Timer(config.CLIPBOARD_RESTORE_DELAY,
                                         _restore)
        _restore_timer.daemon = True
        _restore_timer.start()
    return True
