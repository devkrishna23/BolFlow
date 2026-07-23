"""BolFlow settings window (pywebview / Edge WebView2).

Runs as its own process (launched from the tray) so its GUI loop never
fights the main app's Tk HUD. Writes settings.json; the running app picks
changes up within ~2 s. Run directly for development: python settings.py
"""

import json
import os
import threading

import webview

import config

VERSION = "1.0"


class Api:
    def get_settings(self):
        hotkey = config.HOTKEY if isinstance(config.HOTKEY, (tuple, list)) \
            else (config.HOTKEY,)
        return {
            "hotkey": list(hotkey),
            "sarvam_mode": config.SARVAM_MODE,
            "mic_device": config.MIC_DEVICE,
            "show_live_transcript": config.SHOW_LIVE_TRANSCRIPT,
            "api_key_ok": bool(config.SARVAM_API_KEY),
            "version": VERSION,
        }

    def save_settings(self, data):
        keep = {}
        try:
            with open(config.SETTINGS_PATH, encoding="utf-8") as f:
                keep = json.load(f)
        except (OSError, ValueError):
            pass
        for key in ("HOTKEY", "SARVAM_MODE", "MIC_DEVICE",
                    "SHOW_LIVE_TRANSCRIPT"):
            if key.lower() in data:
                keep[key] = data[key.lower()]
        with open(config.SETTINGS_PATH, "w", encoding="utf-8") as f:
            json.dump(keep, f, indent=2)
        return True

    def list_mics(self):
        import sounddevice as sd
        names, seen = [], set()
        for dev in sd.query_devices():
            if dev["max_input_channels"] > 0 and dev["name"] not in seen:
                seen.add(dev["name"])
                names.append(dev["name"])
        return names

    def capture_hotkey(self):
        """Block until the user presses a key/combo (max 2 keys); returns
        pynput key names, or None on Esc / 10 s timeout."""
        from pynput import keyboard
        combo, held = [], set()
        done = threading.Event()

        def name_of(key):
            if isinstance(key, keyboard.Key):
                return key.name
            return getattr(key, "char", None)

        def on_press(key):
            n = name_of(key)
            if n:
                held.add(n)
                if n not in combo and len(combo) < 2:
                    combo.append(n)

        def on_release(key):
            held.discard(name_of(key))
            if combo and not held:
                done.set()
                return False

        with keyboard.Listener(on_press=on_press, on_release=on_release):
            done.wait(timeout=10)
        if not combo or combo == ["esc"]:
            return None
        return combo


HTML = """<!DOCTYPE html><html><head><meta charset="utf-8"><style>
* { margin:0; padding:0; box-sizing:border-box; user-select:none; }
body { font-family:'Segoe UI',sans-serif; background:#101014; color:#e4e6ee;
       height:100vh; display:flex; overflow:hidden; }
.side { width:172px; background:#101014; padding:16px 10px; display:flex;
        flex-direction:column; gap:4px; border-right:1px solid #1e1e24; }
.logo { display:flex; align-items:center; gap:9px; padding:4px 8px 18px; }
.logo .dot { width:27px; height:27px; border-radius:50%; background:#1c1c22;
             display:flex; align-items:center; justify-content:center; }
.logo b { color:#FAC775; font-size:16px; font-weight:600; }
.nav { color:#9a9ca6; padding:9px 11px; font-size:13px; border-radius:8px;
       cursor:pointer; }
.nav:hover { background:#17171d; }
.nav.on { background:#2a2318; color:#FAC775; }
.foot { margin-top:auto; padding:8px 10px; font-size:11.5px; color:#5f6068;
        display:flex; gap:7px; align-items:center; }
.foot .st { width:8px; height:8px; border-radius:50%; }
.main { flex:1; background:#16161b; padding:18px 22px; overflow-y:auto; }
.ribbon { height:36px; border-radius:18px; background:#101014;
          border:1px solid #26262e; display:flex; align-items:center;
          justify-content:center; margin-bottom:14px; }
h4 { font-size:11px; color:#7a7c86; letter-spacing:0.08em; font-weight:600;
     margin:14px 2px 8px; }
.row { background:#1c1c22; border-radius:10px; padding:12px 15px;
       display:flex; align-items:center; justify-content:space-between;
       margin-bottom:8px; }
.row .l { font-size:13.5px; }
.row .hint { color:#7a7c86; font-size:11.5px; margin-top:2px; }
.chip { border:1px solid #3a3a44; border-radius:7px; padding:5px 12px;
        font-size:12.5px; font-family:Consolas,monospace; cursor:pointer; }
.chip:hover { border-color:#EF9F27; }
.chip.listen { color:#FAC775; border-color:#EF9F27; }
.seg { display:flex; gap:6px; }
.seg span { color:#9a9ca6; border:1px solid #3a3a44; border-radius:7px;
            padding:5px 11px; font-size:12px; cursor:pointer; }
.seg span:hover { border-color:#6a6a76; }
.seg span.on { background:#2a2318; color:#FAC775; border-color:#2a2318; }
.sw { width:36px; height:20px; border-radius:11px; background:#3a3a44;
      position:relative; cursor:pointer; transition:background .15s; }
.sw::after { content:''; position:absolute; left:2px; top:2px; width:16px;
             height:16px; border-radius:50%; background:#fff;
             transition:left .15s; }
.sw.on { background:#639922; }
.sw.on::after { left:18px; }
select { background:#16161b; color:#b9bbc5; border:1px solid #3a3a44;
         border-radius:7px; padding:5px 10px; font-size:12.5px;
         max-width:250px; outline:none; }
.about p { font-size:13px; color:#b9bbc5; line-height:1.7; margin:0 0 12px; }
.about b { color:#e4e6ee; }
.saved { position:fixed; bottom:14px; right:18px; background:#1c2a14;
         color:#97C459; font-size:12px; padding:6px 12px; border-radius:7px;
         opacity:0; transition:opacity .2s; }
</style></head><body>
<div class="side">
  <div class="logo"><span class="dot"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="#EF9F27" stroke-width="2.4"><rect x="9" y="2" width="6" height="12" rx="3"/><path d="M5 10v1a7 7 0 0 0 14 0v-1M12 18v4"/></svg></span><b>BolFlow</b></div>
  <div class="nav on" id="nav-gen">General</div>
  <div class="nav" id="nav-about">About</div>
  <div class="foot"><span class="st" id="keydot" style="background:#5f6068"></span><span id="keytxt">checking key…</span></div>
</div>
<div class="main">
  <div class="ribbon"><svg width="190" height="14" viewBox="0 0 190 14"><path d="M2 7 Q 22 1 42 7 T 82 7 T 122 7 T 162 7 T 188 7" fill="none" stroke="#E24B4A" stroke-width="1.6"/><path d="M2 7 Q 26 13 50 7 T 98 7 T 146 7 T 188 7" fill="none" stroke="#EF9F27" stroke-width="1.1" opacity="0.65"/></svg></div>
  <div id="pane-gen">
    <h4>DICTATION</h4>
    <div class="row"><div><div class="l">Push-to-talk keys</div>
      <div class="hint">Click, then press your key or two-key combo</div></div>
      <span class="chip" id="hotkey">…</span></div>
    <div class="row"><div><div class="l">Live transcript card</div>
      <div class="hint">Words appear on screen while you speak</div></div>
      <span class="sw" id="live"></span></div>
    <div class="row"><div><div class="l">Microphone</div>
      <div class="hint">Applies from the next app start</div></div>
      <select id="mic"><option>Default</option></select></div>
    <h4>OUTPUT</h4>
    <div class="row"><div><div class="l">Style</div>
      <div class="hint">How Hindi and mixed speech is written</div></div>
      <span class="seg" id="modes"></span></div>
  </div>
  <div id="pane-about" class="about" style="display:none">
    <h4>ABOUT</h4>
    <div class="row" style="display:block">
      <p><b>BolFlow</b> is voice dictation for Bharat. Hold a key, speak in
      any of 22 Indian languages (or Hinglish), and clean text appears at
      your cursor.</p>
      <p>Speech-to-text runs on <b>Sarvam AI's Saaras v3</b>; audio is sent
      to Sarvam's API using your key. Filler-word cleanup runs locally.
      MIT licensed.</p>
      <p id="ver" style="color:#7a7c86"></p>
    </div>
  </div>
</div>
<div class="saved" id="saved">Saved</div>
<script>
const MODES = [["translit","Hinglish"],["codemix","Mixed"],
               ["transcribe","देवनागरी"],["translate","English"]];
let S = {};
function savedFlash(){ const el = document.getElementById('saved');
  el.style.opacity = 1; setTimeout(()=>el.style.opacity=0, 1200); }
async function save(){ await pywebview.api.save_settings({
    hotkey:S.hotkey, sarvam_mode:S.sarvam_mode, mic_device:S.mic_device,
    show_live_transcript:S.show_live_transcript }); savedFlash(); }
function keyLabel(k){ const m={ctrl_l:'Ctrl',ctrl_r:'RCtrl',alt_l:'Alt',
  alt_gr:'AltGr',cmd:'Win',shift_l:'Shift',shift_r:'RShift',space:'Space'};
  return m[k] || k.charAt(0).toUpperCase()+k.slice(1); }
function render(){
  document.getElementById('hotkey').textContent =
    S.hotkey.map(keyLabel).join(' + ');
  document.getElementById('live').classList.toggle('on', S.show_live_transcript);
  const seg = document.getElementById('modes'); seg.innerHTML = '';
  for (const [val, label] of MODES){
    const el = document.createElement('span'); el.textContent = label;
    if (S.sarvam_mode === val) el.classList.add('on');
    el.onclick = ()=>{ S.sarvam_mode = val; render(); save(); };
    seg.appendChild(el); }
}
window.addEventListener('pywebviewready', async ()=>{
  S = await pywebview.api.get_settings();
  document.getElementById('ver').textContent = 'Version ' + S.version;
  const dot = document.getElementById('keydot'),
        txt = document.getElementById('keytxt');
  dot.style.background = S.api_key_ok ? '#97C459' : '#E24B4A';
  txt.textContent = S.api_key_ok ? 'API key connected' : 'API key missing';
  const mic = document.getElementById('mic'); mic.innerHTML = '';
  const opt = document.createElement('option');
  opt.value = ''; opt.textContent = 'Default'; mic.appendChild(opt);
  for (const name of await pywebview.api.list_mics()){
    const o = document.createElement('option');
    o.value = name; o.textContent = name; mic.appendChild(o); }
  mic.value = S.mic_device || '';
  mic.onchange = ()=>{ S.mic_device = mic.value || null; save(); };
  render();
  document.getElementById('live').onclick = function(){
    S.show_live_transcript = !S.show_live_transcript; render(); save(); };
  document.getElementById('hotkey').onclick = async function(){
    this.classList.add('listen'); this.textContent = 'press keys…';
    const combo = await pywebview.api.capture_hotkey();
    this.classList.remove('listen');
    if (combo){ S.hotkey = combo; save(); }
    render(); };
  document.getElementById('nav-gen').onclick = ()=>{ swap('gen'); };
  document.getElementById('nav-about').onclick = ()=>{ swap('about'); };
  function swap(which){
    document.getElementById('pane-gen').style.display =
      which==='gen' ? '' : 'none';
    document.getElementById('pane-about').style.display =
      which==='about' ? '' : 'none';
    document.getElementById('nav-gen').classList.toggle('on', which==='gen');
    document.getElementById('nav-about').classList.toggle('on', which==='about');
  }
});
</script></body></html>"""


def _windows_chrome():
    """Dark title bar + BolFlow icon (instead of pythonw's) once the
    window exists. Pure win32; silently a no-op if anything is missing."""
    import ctypes
    import time
    hwnd = 0
    for _ in range(60):
        hwnd = ctypes.windll.user32.FindWindowW(None, "BolFlow settings")
        if hwnd:
            break
        time.sleep(0.1)
    if not hwnd:
        return
    dark = ctypes.c_int(1)   # DWMWA_USE_IMMERSIVE_DARK_MODE
    ctypes.windll.dwmapi.DwmSetWindowAttribute(
        hwnd, 20, ctypes.byref(dark), 4)
    ctypes.windll.user32.SetWindowPos(hwnd, 0, 0, 0, 0, 0, 0x27)  # repaint
    ico = os.path.join(config.RESOURCE_DIR, "app.ico")
    if os.path.exists(ico):
        for size, which in ((16, 0), (32, 1)):   # small + big icon
            h = ctypes.windll.user32.LoadImageW(None, ico, 1, size, size,
                                                0x10)  # LR_LOADFROMFILE
            if h:
                ctypes.windll.user32.SendMessageW(hwnd, 0x80, which, h)


if __name__ == "__main__":
    webview.create_window(
        "BolFlow settings", html=HTML, js_api=Api(),
        width=730, height=560, background_color="#101014")
    webview.start(func=_windows_chrome)
