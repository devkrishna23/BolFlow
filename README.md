# BolFlow — voice dictation for Bharat

Hold a hotkey, speak — in Hindi, English, Hinglish, or any of 22 Indian
languages — release, and clean, punctuated text appears at the cursor in
whatever app is focused. Wispr Flow, but built for how India actually
speaks: speech-to-text runs on [Sarvam AI's](https://www.sarvam.ai) Saaras
v3 model, which handles code-mixed speech natively. The default `translit`
mode romanizes everything — Hindi comes out as Hinglish, English stays
English. (Prefer Devanagari? Switch to native script from the tray menu.)

**Bring your own key:** transcription uses Sarvam's cloud API, so you need a
free API key from [dashboard.sarvam.ai](https://dashboard.sarvam.ai) and
dictation spends your Sarvam credits. Audio leaves your machine (to Sarvam);
filler-word cleanup runs locally as a lightweight text pass. **First
launch opens an onboarding window** that verifies your key with a live
call, checks your mic, and ends with a real dictation test — no manual
environment variables needed.

## Setup

1. **Python venv** (3.13):
   ```
   python -m venv .venv
   .venv\Scripts\pip install -r requirements.txt
   ```
2. **Sarvam API key**: get one at [dashboard.sarvam.ai](https://dashboard.sarvam.ai),
   then set it as a user environment variable (System Settings → search
   "environment variables", or in PowerShell):
   ```
   [Environment]::SetEnvironmentVariable("SARVAM_API_KEY", "your-key", "User")
   ```
3. That's it — filler sounds (um/uh) are stripped by a built-in text pass,
   no extra models to download.

## Run

```
.venv\Scripts\pythonw.exe app.py
```

(console-less; output goes to `bolflow.log`). A saffron mic icon appears in
the system tray. For debugging, run with a console instead:
`.venv\Scripts\python app.py`. Optional desktop shortcut:

```powershell
$s = (New-Object -ComObject WScript.Shell).CreateShortcut("$env:USERPROFILE\Desktop\BolFlow Dictation.lnk")
$s.TargetPath = "$pwd\.venv\Scripts\pythonw.exe"; $s.Arguments = "`"$pwd\app.py`""
$s.WorkingDirectory = "$pwd"; $s.IconLocation = "$pwd\app.ico"; $s.Save()
```

Hold **Left Ctrl + Left Alt** together, speak, release (either key) to
paste. Audio streams to Sarvam **while you speak** (WebSocket), so most of
the transcription is already done when you release — with automatic
fallback to the one-shot REST call if the stream fails. A fluid-ribbon pill
at the bottom of the screen springs open into a card that shows **your
words appearing live as you speak**, with a timer; it swells amber
("transcribing…") while finishing, and flashes green when the text lands
(red if the network or a stage failed — nothing was pasted). Tap **Esc** or
click the card while recording to cancel without pasting. The tray menu can pause dictation,
open **Settings** (a windowed UI: rebind the hotkey by pressing keys,
switch output style, pick a microphone, toggle the live card and AI
cleanup — changes apply within ~2 s, no restart), switch the output style
directly, and open the log. Power-user knobs beyond the Settings window
live in `config.py`; change the hotkey,
output mode (`codemix` / `translit` / native script / translate-to-English),
and all other knobs in `config.py`.

To start it with Windows: press Win+R, run `shell:startup`, and copy the
Desktop shortcut in there (delete it to undo).

Notes:
- Latency is network-bound: measured ~1.3–2.3 s stop-speaking → text pasted
  on a real connection (streaming hides most of the STT inside the speaking
  time; the text cleanup is instant). Re-measure on your connection with
  `bench.py <wav-file>` (16 kHz mono WAV; uses the REST path).
- To dictate into elevated (admin) apps, run the app as admin too.
- The previous clipboard **text** is restored after each paste; images/files
  on the clipboard are not (v1 limitation).

## Files

- `app.py` — entrypoint: hotkey chord, worker pipeline, single-instance guard
- `audio_capture.py` — always-open mic stream with pre-roll buffer
- `transcriber.py` — Sarvam Saaras v3: streaming WebSocket client + REST fallback
- `cleaner.py` — script-safe text cleanup: filler sounds, punctuation spacing
- `injector.py` — clipboard-paste injection, focus tracking, clipboard restore
- `hud.py` — live-transcript card / fluid ribbon HUD (run standalone for a demo)
- `tray.py` — tray icon: pause, settings, output style, open log, quit
- `settings.py` — settings window (pywebview/WebView2, writes settings.json)
- `bench.py` — offline latency benchmark over WAV files (no mic needed)
