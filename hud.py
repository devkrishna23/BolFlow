"""Fluid-ribbon HUD, Wispr-style, with motion physics.

A slim pill breathes at the bottom of the screen while idle. On recording it
springs open (damped harmonic bloom with a slight overshoot) into a capsule
of layered liquid waves driven by the live mic level; speech transients fire
ripples that travel outward along the ribbon. Processing calms it to an amber
swell; done sends a luminous sweep along the ribbon as it collapses, then the
pill melts back down. Colors cross-fade between states instead of snapping.

Frames render via PIL at 2x supersampling (anti-aliased, alpha-layered glow)
and blit to a borderless Tk window. Other threads only assign `state`.
Run `python hud.py` for a standalone demo that cycles all states.
"""

import math
import time
import tkinter as tk

from PIL import Image, ImageDraw, ImageFont, ImageTk

W, H = 520, 128
SS = 2
ACTIVE_MS = 16          # ~60 fps while animating
IDLE_MS = 80            # ~12 fps for the idle breathing
IDLE_W, IDLE_H = 64, 12
FULL_W, FULL_H = 260, 56
TEXT_W, TEXT_H = 500, 108   # card size while a live transcript is showing
DONE_SECONDS = 0.7
LEVEL_GAIN = 25         # mic RMS -> 0..1 ribbon drive; raise if ribbon is shy
N_POINTS = 56

_TEXT_COL = (228, 230, 238)
_DIM_COL = (150, 152, 162)


def _font(indic: bool = False):
    """Always Nirmala UI (covers Latin AND all Indic scripts): switching
    fonts when Devanagari arrives mid-utterance made the text visibly
    shrink, since Nirmala's glyphs run smaller than Segoe's. One font,
    sized up to match, means no mid-sentence jump."""
    f = _font.cache.get("f")
    if f is None:
        try:
            # Nirmala ships as a .ttc collection; index 0 = Nirmala UI
            f = ImageFont.truetype(r"C:\Windows\Fonts\Nirmala.ttc",
                                   17 * SS, index=0)
        except OSError:
            try:
                f = ImageFont.truetype("segoeui.ttf", 15 * SS)
            except OSError:
                f = ImageFont.load_default()
        _font.cache["f"] = f
    return f


_font.cache = {}


def _wrap_tail(text, font, max_w, max_lines=2):
    """Wrap text and keep only the last `max_lines` lines (the newest words),
    with a leading ellipsis when older text scrolled away."""
    lines, cur = [], ""
    for word in text.split():
        trial = (cur + " " + word).strip()
        if not cur or font.getlength(trial) <= max_w:
            cur = trial
        else:
            lines.append(cur)
            cur = word
    if cur:
        lines.append(cur)
    if len(lines) > max_lines:
        lines = lines[-max_lines:]
        lines[0] = "…" + lines[0]
    return lines

_PILL_FILL = (16, 16, 20, 235)
_KEY = "#010203"        # transparency key color for rounded corners
_KEY_RGB = (1, 2, 3)

_COLORS = {             # (glow, mid, core) per state
    "idle":       ((90, 90, 102), (120, 120, 134), (150, 150, 165)),
    "recording":  ((163, 45, 45), (226, 75, 74), (240, 149, 149)),
    "processing": ((133, 79, 11), (239, 159, 39), (250, 199, 117)),
    "done":       ((59, 109, 17), (151, 196, 89), (192, 221, 151)),
    "error":      ((120, 22, 34), (211, 47, 66), (245, 130, 140)),
}


def _lerp(a, b, f):
    return tuple(int(x + (y - x) * f) for x, y in zip(a, b))


class Hud:
    def __init__(self, level_source=None):
        self.state = "idle"
        self.text_source = None   # callable -> live transcript, or None
        self.on_cancel = None     # called when the card is clicked mid-recording
        self._level_source = level_source or (lambda: 0.0)
        self._prev_state = "idle"
        self._rec_since = None    # perf-counter time recording started
        self._reveal = 0.0        # words currently revealed (word-by-word)
        self._drive = 0.0
        self._w, self._h = float(IDLE_W), float(IDLE_H)
        self._wv = self._hv = 0.0          # spring velocities
        self._cols = list(_COLORS["idle"])  # current cross-faded colors
        self._ripples = []                  # [(birth_time, strength), ...]
        self._done_since = None
        self._last = time.perf_counter()
        self._t0 = self._last

        self.root = tk.Tk()
        self.root.overrideredirect(True)
        self.root.attributes("-topmost", True)
        self.root.attributes("-transparentcolor", _KEY)
        self.canvas = tk.Canvas(self.root, width=W, height=H,
                                bg=_KEY, highlightthickness=0)
        self.canvas.pack()
        self.canvas.bind("<Button-1>", self._click)
        self._photo = None
        self._img_item = self.canvas.create_image(0, 0, anchor="nw")

        self.root.update_idletasks()
        self._place()
        self._tick()

    def _place(self):
        """Wispr-style: fixed at screen-bottom-center, the pill's baseline
        sitting just above the taskbar (window bottom = work-area bottom)."""
        import ctypes

        class _R(ctypes.Structure):
            _fields_ = [("l", ctypes.c_long), ("t", ctypes.c_long),
                        ("r", ctypes.c_long), ("b", ctypes.c_long)]
        r = _R()
        if ctypes.windll.user32.SystemParametersInfoW(
                0x0030, 0, ctypes.byref(r), 0):     # SPI_GETWORKAREA
            bottom = r.b
        else:
            bottom = self.root.winfo_screenheight() - 48
        x = (self.root.winfo_screenwidth() - W) // 2
        self.root.geometry(f"{W}x{H}+{x}+{bottom - H}")

    # --- motion ------------------------------------------------------------

    def _spring(self, x, v, target, dt):
        v += (260.0 * (target - x) - 22.0 * v) * dt   # slight overshoot
        return x + v * dt, v

    def _ripple_offset(self, u, t):
        """Speech transients push traveling bumps outward from the center."""
        y = 0.0
        for birth, strength in self._ripples:
            age = t - birth
            pos = 0.55 * age                    # travel speed along ribbon
            decay = math.exp(-3.5 * age) * strength
            for center in (0.5 - pos, 0.5 + pos):
                y += decay * math.exp(-((u - center) ** 2) / 0.006)
        return y

    def _wave(self, u, t, layer, speed):
        env = 0.55 + 0.45 * math.sin(u * 2.3 - t * 1.7 + layer * 2.0)
        return env * (
            0.50 * math.sin(u * 7.3 - t * 4.1 * speed + layer * 1.35)
            + 0.28 * math.sin(u * 13.7 + t * 3.3 * speed + layer * 2.1)
            + 0.22 * math.sin(u * 23.1 - t * 5.9 * speed + layer * 0.7)
        )

    def _ribbon_points(self, layer, amp, speed, t, cy):
        span = (self._w - 36) * SS
        x0 = (W * SS - span) / 2
        pts = []
        for i in range(N_POINTS):
            u = i / (N_POINTS - 1)
            window = math.sin(u * math.pi)
            y = self._wave(u, t, layer, speed) * amp
            y += self._ripple_offset(u, t) * 14.0 * math.sin(u * math.pi)
            pts.append((x0 + u * span, cy + SS * window * y))
        return pts

    # --- rendering ---------------------------------------------------------

    def _render(self, state, amp, speed, t, live_text=""):
        img = Image.new("RGBA", (W * SS, H * SS), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        pw, ph = self._w * SS, self._h * SS
        # bottom-anchored, Wispr-style: the pill keeps a fixed baseline just
        # above the taskbar and the card grows UPWARD from it
        cx = W * SS / 2
        cy = H * SS - 8 * SS - ph / 2
        box = (cx - pw / 2, cy - ph / 2, cx + pw / 2, cy + ph / 2)
        # transcript mode: card is tall; ribbon lives in the lower band and
        # text in the upper band. Otherwise the ribbon is centered.
        texty = ph > (FULL_H + 14) * SS
        ry = box[3] - ph * 0.24 if texty else cy
        radius = min(ph / 2, 18 * SS) if texty else ph / 2

        glow, mid, core = self._cols
        breath = 0.5 + 0.5 * math.sin(t * 2 * math.pi / 3.2)
        edge_a = int(140 + 60 * breath) if state == "idle" else 210
        d.rounded_rectangle(box, radius=radius, fill=_PILL_FILL,
                            outline=mid + (edge_a,), width=SS)
        # glassy top highlight
        d.arc((box[0] + ph * 0.35, box[1] + SS, box[2] - ph * 0.35,
               box[1] + ph * 0.8), 200, 340, fill=(255, 255, 255, 26),
              width=SS)

        if texty and live_text:
            indic = any(ord(ch) >= 0x0900 for ch in live_text)
            font = _font(indic)
            maxw = pw - 44 * SS
            lines = _wrap_tail(live_text, font, maxw)
            ty = box[1] + 12 * SS
            for line in lines:
                d.text((box[0] + 22 * SS, ty), line, font=font,
                       fill=_TEXT_COL + (255,))
                ty += 21 * SS
            if state == "recording" and self._rec_since is not None:
                secs = int(time.perf_counter() - self._rec_since)
                d.text((box[2] - 46 * SS, box[1] + 10 * SS),
                       f"{secs // 60}:{secs % 60:02d}", font=_font(False),
                       fill=_DIM_COL + (255,))
            elif state == "processing":
                dots = "." * (1 + int(t * 2.5) % 3)
                d.text((box[0] + 22 * SS, box[3] - ph * 0.16 - 8 * SS),
                       f"transcribing{dots}", font=_font(False),
                       fill=_DIM_COL + (230,), anchor="lm")

        bloom = min(1.0, max(0.0, (self._h - IDLE_H) / (FULL_H - IDLE_H)))
        if bloom > 0.25 and amp > 0.3:
            a = (amp * bloom) * (0.45 if texty else 1.0)
            for layer in range(3):
                pts = self._ribbon_points(layer, a, speed, t, ry)
                d.line(pts, fill=glow + (55,), width=8 * SS, joint="curve")
                d.line(pts, fill=mid + (165,), width=3 * SS, joint="curve")
                d.line(pts, fill=core + (255,), width=int(1.4 * SS),
                       joint="curve")

            if state == "done" and self._done_since is not None:
                # luminous dot sweeps the ribbon as it collapses
                p = (t - self._done_since) / DONE_SECONDS
                u = p
                span = (self._w - 36) * SS
                sx = (W * SS - span) / 2 + u * span
                sy = ry + SS * math.sin(u * math.pi) * self._wave(u, t, 0, speed) * a
                for r, alpha in ((9, 40), (5, 110), (2.5, 255)):
                    d.ellipse((sx - r * SS, sy - r * SS, sx + r * SS, sy + r * SS),
                              fill=(220, 245, 200, alpha))

        frame = Image.new("RGB", (W, H), _KEY_RGB)
        small = img.resize((W, H), Image.LANCZOS)
        frame.paste(small, (0, 0), small)
        self._photo = ImageTk.PhotoImage(frame)
        self.canvas.itemconfig(self._img_item, image=self._photo)

    # --- state loop ----------------------------------------------------------

    def _tick(self):
        now = time.perf_counter()
        dt = min(0.05, now - self._last)
        self._last = now
        t = now - self._t0
        state = self.state
        amp = speed = 0.0

        if state == "recording" and self._prev_state != "recording":
            self._rec_since = now
        self._prev_state = state

        live = ""
        if state in ("recording", "processing") and self.text_source:
            try:
                live = self.text_source() or ""
            except Exception:
                live = ""
        # word-by-word reveal: segments arrive as sentence chunks, but the
        # card types them out one word at a time - gently when nearly caught
        # up, faster the further behind it is (so flush bursts don't lag)
        words = live.split()
        if len(words) < self._reveal:
            self._reveal = 0.0            # new utterance started
        if self._reveal < len(words):
            behind = len(words) - self._reveal
            rate = min(28.0, 5.0 + 2.2 * behind)   # words per second
            self._reveal = min(float(len(words)), self._reveal + rate * dt)
        live = " ".join(words[:int(self._reveal)])

        if state == "recording":
            self._done_since = None
            target = min(1.0, math.sqrt(self._level_source() * LEVEL_GAIN))
            if target > self._drive + 0.22:      # speech transient -> ripple
                self._ripples.append((t, min(1.0, target)))
            self._drive = self._drive * 0.6 + target * 0.4
            amp, speed = 3 + 20 * self._drive, 1.0
        elif state == "processing":
            self._done_since = None
            amp, speed = 7 + 2.5 * math.sin(t * 3), 2.2
        elif state in ("done", "error"):
            if self._done_since is None:
                self._done_since = t
            # the error flash lingers a beat longer so it registers
            hold = DONE_SECONDS if state == "done" else DONE_SECONDS * 1.8
            p = (t - self._done_since) / hold
            if p >= 1.0:
                self.state = state = "idle"
            else:
                amp, speed = max(0.5, 12 * (1 - p)), 1.0
        if state == "idle":
            self._done_since = None
            self._drive = 0.0
            self._reveal = 0.0

        self._ripples = [r for r in self._ripples if t - r[0] < 1.2]

        if state == "idle":
            tw, th = IDLE_W, IDLE_H
        elif live and state in ("recording", "processing"):
            tw, th = TEXT_W, TEXT_H
        else:
            tw, th = FULL_W, FULL_H
        self._w, self._wv = self._spring(self._w, self._wv, tw, dt)
        self._h, self._hv = self._spring(self._h, self._hv, th, dt)

        for i, tgt in enumerate(_COLORS[state]):
            self._cols[i] = _lerp(self._cols[i], tgt, 0.14)

        self._render(state, amp, speed, t, live)
        settled = state == "idle" and abs(self._w - IDLE_W) < 1.0
        self.root.after(IDLE_MS if settled else ACTIVE_MS, self._tick)

    def _click(self, _event):
        if self.state == "recording" and self.on_cancel:
            self.on_cancel()

    def run(self):
        self.root.mainloop()

    def stop(self):
        self.root.after(0, self.root.destroy)


if __name__ == "__main__":
    # standalone demo: cycles the states with a fake voice full of transients
    demo_t0 = time.perf_counter()

    def fake_level():
        t = time.perf_counter() - demo_t0
        env = 0.3 + 0.7 * abs(math.sin(t * 2.1 + math.sin(t * 0.7) * 2.5))
        burst = 1.0 if (t * 1.9) % 1 < 0.12 else 0.35
        return 0.05 * env * burst

    hud = Hud(level_source=fake_level)

    _WORDS = ("This is a product overview of BolFlow — it transcribes "
              "while you speak, live, right here in the card. Mera naam "
              "Krishna hai aur ye Hinglish mein bhi kaam karta hai.").split()

    def fake_text():
        t = (time.perf_counter() - demo_t0) % 9.5
        if t < 2.0:
            return ""
        return " ".join(_WORDS[:int((t - 2.0) * 3.5)])

    hud.text_source = fake_text

    def cycle():
        t = (time.perf_counter() - demo_t0) % 9.5
        if t < 1.5:
            pass                              # idle pill, breathing
        elif t < 5.5:
            hud.state = "recording"
        elif t < 7.5:
            hud.state = "processing"
        elif hud.state == "processing":
            hud.state = "done"                # hud returns itself to idle
        hud.root.after(50, cycle)

    cycle()
    print("HUD demo running - watch the pill at the bottom of the screen. "
          "Ctrl+C to quit.")
    hud.run()
