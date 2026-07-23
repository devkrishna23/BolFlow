# BolFlow: voice dictation for Bharat

Hold a hotkey, speak in Hindi, English, Hinglish, or any of 22 Indian
languages, release, and clean, punctuated text appears at the cursor in
whatever app is focused. Wispr Flow, but built for how India actually
speaks: speech-to-text runs on [Sarvam AI's](https://www.sarvam.ai) Saaras
v3 model, which handles code-mixed speech natively. The default `translit`
mode romanizes everything, so Hindi comes out as Hinglish and English stays
English. (Prefer Devanagari? Switch to native script from the tray menu.)

**Website:** [devkrishna23.github.io/BolFlow](https://devkrishna23.github.io/BolFlow)

**Bring your own key:** transcription uses Sarvam's cloud API, so you need a
free API key from [dashboard.sarvam.ai](https://dashboard.sarvam.ai) and
dictation spends your Sarvam credits. Audio leaves your machine (to Sarvam);
filler-word cleanup runs locally as a lightweight text pass.

## Install (users)

Grab **BolFlow-Setup** from the
[latest release](https://github.com/devkrishna23/BolFlow/releases/latest)
and run it. No Python, no dependencies. First launch opens an onboarding
window that verifies your key with a live call, checks your mic, and ends
with a real dictation test.

Windows may show a SmartScreen prompt because the installer is new and
unsigned: click "More info", then "Run anyway". Every line of the source is
in this repo if you'd rather read it or build it yourself.

## Run from source (developers)

1. **Python venv** (3.13):
   ```
   python -m venv .venv
   .venv\Scripts\pip install -r requirements.txt
   ```
2. Start it:
   ```
   .venv\Scripts\pythonw.exe app.py
   ```
   Console-less; output goes to `bolflow.log`. Onboarding will ask for your
   Sarvam key on first run (or set a `SARVAM_API_KEY` environment variable).
   For debugging, run with a console instead: `.venv\Scripts\python app.py`.

Build the installer yourself:
```
.venv\Scripts\pip install pyinstaller
.venv\Scripts\pyinstaller bolflow.spec --noconfirm
ISCC.exe installer.iss
```

## Using it

Hold **Left Ctrl + Left Alt** together, speak, release (either key) to
paste. Audio streams to Sarvam **while you speak** (WebSocket), so most of
the transcription is already done when you release, with automatic fallback
to a one-shot REST call if the stream fails. A fluid-ribbon pill at the
bottom of the screen springs open into a card that shows **your words
appearing live as you speak**, with a timer; it swells amber
("transcribing…") while finishing, and flashes green when the text lands
(red if the network or a stage failed and nothing was pasted). Tap **Esc**
or click the card while recording to cancel without pasting.

The tray menu can pause dictation, open **Settings** (rebind the hotkey by
pressing keys, switch output style, pick a microphone, toggle the live
card; changes apply within ~2 s, no restart), switch the output style
directly, and open the log. Power-user knobs beyond the Settings window
live in `config.py`.

Notes:
- Latency is network-bound: measured ~1.3-2.3 s stop-speaking to
  text-pasted on a real connection (streaming hides most of the STT inside
  the speaking time; the text cleanup is instant). Re-measure on your
  connection with `bench.py <wav-file>` (16 kHz mono WAV; uses the REST
  path).
- To dictate into elevated (admin) apps, run the app as admin too.
- The previous clipboard **text** is restored after each paste; images and
  files on the clipboard are not (v1 limitation).

## Files

- `app.py`: entrypoint: hotkey chord, worker pipeline, single-instance guard
- `audio_capture.py`: always-open mic stream with pre-roll buffer
- `transcriber.py`: Sarvam Saaras v3: streaming WebSocket client + REST fallback
- `cleaner.py`: script-safe text cleanup: filler sounds, punctuation spacing
- `injector.py`: clipboard-paste injection, focus tracking, clipboard restore
- `hud.py`: live-transcript card / fluid ribbon HUD (run standalone for a demo)
- `tray.py`: tray icon: pause, settings, output style, open log, quit
- `settings.py`: settings window (pywebview/WebView2, writes settings.json)
- `onboarding.py`: first-run window: key verification, mic check, live test
- `bench.py`: offline latency benchmark over WAV files (no mic needed)
