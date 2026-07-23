"""BolFlow first-run onboarding (pywebview / Edge WebView2).

Launched by app.py when no Sarvam API key is configured. Three steps:
verify + save the key, live environment checks, and a real dictation test
(the main app starts in the background as soon as the key lands in
settings.json, so the hotkey is live by step 3). Runs as its own process,
same as settings.py.
"""

import io
import json
import math
import os
import struct
import wave

import httpx
import webview

import config


def _test_wav() -> bytes:
    """One second of a soft 440 Hz tone - enough for a real API round-trip."""
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(16000)
        for i in range(16000):
            w.writeframes(struct.pack(
                "<h", int(6000 * math.sin(2 * math.pi * 440 * i / 16000))))
    return buf.getvalue()


def _save_key(key: str):
    data = {}
    try:
        with open(config.SETTINGS_PATH, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        pass
    data["SARVAM_API_KEY"] = key
    with open(config.SETTINGS_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


class Api:
    def hotkey_labels(self):
        names = config.HOTKEY if isinstance(config.HOTKEY, (tuple, list)) \
            else (config.HOTKEY,)
        pretty = {"ctrl_l": "Ctrl", "alt_l": "Alt", "ctrl_r": "RCtrl",
                  "shift_r": "RShift", "space": "Space"}
        return [pretty.get(n, n.title()) for n in names]

    def verify_key(self, key: str):
        key = (key or "").strip()
        if not key:
            return {"ok": False, "error": "Enter a key first"}
        import time
        last_error = "Couldn't reach Sarvam"
        for attempt in (1, 2):        # slow networks deserve a second try
            try:
                t0 = time.perf_counter()
                r = httpx.post(
                    "https://api.sarvam.ai/speech-to-text",
                    headers={"api-subscription-key": key},
                    files={"file": ("t.wav", _test_wav(), "audio/wav")},
                    data={"model": config.SARVAM_MODEL, "mode": "transcribe",
                          "language_code": "unknown"},
                    timeout=60.0)
                latency = time.perf_counter() - t0
                break
            except httpx.TimeoutException:
                last_error = ("Sarvam is taking too long on this connection. "
                              "Check your internet and try once more")
            except httpx.HTTPError:
                last_error = ("Couldn't reach Sarvam. Check your internet "
                              "(or firewall/proxy) and try again")
        else:
            return {"ok": False, "error": last_error}
        if r.status_code in (401, 403):
            return {"ok": False,
                    "error": "Key rejected. Copy it again from platform.sarvam.ai"}
        if r.status_code >= 500:
            return {"ok": False, "error": "Sarvam is having trouble. Try again"}
        _save_key(key)
        return {"ok": True, "latency": round(latency, 1)}

    def check_env(self):
        out = {"mic": None}
        try:
            import sounddevice as sd
            dev = sd.query_devices(kind="input")
            out["mic"] = dev["name"]
        except Exception:
            pass
        return out

    def finish(self):
        webview.windows[0].destroy()


HTML = """<!DOCTYPE html><html><head><meta charset="utf-8"><style>
* { margin:0; padding:0; box-sizing:border-box; user-select:none; }
body { font-family:'Segoe UI',sans-serif; background:#16161b; color:#e4e6ee;
       height:100vh; display:flex; flex-direction:column; padding:30px 36px; }
.crumb { color:#7a7c86; font-size:12.5px; margin-bottom:18px; }
h1 { font-size:19px; font-weight:600; color:#FAC775; display:flex;
     align-items:center; gap:10px; margin-bottom:6px; }
h1 .dot { width:30px; height:30px; border-radius:8px; background:#0b0b0e;
          display:flex; align-items:center; justify-content:center; }
.sub { color:#9a9ca6; font-size:13px; margin-bottom:20px; }
.lbl { font-size:13.5px; margin-bottom:8px; }
.keyrow { display:flex; gap:8px; }
input[type=text] { flex:1; background:#101014; border:1px solid #3a3a44;
  border-radius:8px; padding:10px 12px; color:#e4e6ee; font-size:12.5px;
  font-family:Consolas,monospace; outline:none; user-select:text; }
input[type=text]:focus { border-color:#EF9F27; }
.btn { background:#2a2318; color:#FAC775; border-radius:8px; padding:10px 18px;
       font-size:13px; cursor:pointer; border:none; }
.btn:hover { background:#3a3020; }
.btn.big { display:block; margin:16px auto 0; padding:10px 26px; }
.status { margin-top:12px; font-size:12.5px; display:flex; gap:7px;
          align-items:center; min-height:18px; }
.ok { color:#97C459; } .bad { color:#E24B4A; } .wait { color:#FAC775; }
.check { background:#1c1c22; border-radius:8px; padding:11px 14px;
         display:flex; justify-content:space-between; align-items:center;
         margin-bottom:8px; font-size:13px; }
.check .r { font-size:12.5px; display:flex; gap:6px; align-items:center; }
.check .fix { background:#2a2318; color:#FAC775; border-radius:6px;
              padding:4px 10px; font-size:12px; cursor:pointer; }
.keys { display:flex; align-items:center; justify-content:center; gap:8px;
        margin:8px 0 14px; }
.key { border:1px solid #3a3a44; border-radius:7px; padding:6px 13px;
       font-family:Consolas,monospace; font-size:13px; }
.plus { color:#7a7c86; }
textarea { width:100%; height:74px; background:#101014; resize:none;
  border:1px solid #26262e; border-radius:10px; padding:12px; color:#e4e6ee;
  font-size:13.5px; font-family:'Segoe UI',sans-serif; outline:none;
  user-select:text; }
textarea:focus { border-color:#EF9F27; }
.hintline { color:#7a7c86; font-size:12px; margin-top:12px;
            text-align:center; }
.nav { margin-top:auto; display:flex; justify-content:flex-end; gap:8px;
       padding-top:16px; }
.ghost { background:none; border:1px solid #3a3a44; color:#9a9ca6;
         border-radius:8px; padding:9px 16px; font-size:13px; cursor:pointer; }
</style></head><body>
<div class="crumb" id="crumb">Step 1 of 3</div>

<div id="s1">
  <h1><span class="dot"><svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="#EF9F27" stroke-width="2.4"><rect x="9" y="2" width="6" height="12" rx="3"/><path d="M5 10v1a7 7 0 0 0 14 0v-1M12 18v4"/></svg></span>Namaste, welcome to BolFlow</h1>
  <div class="sub">Speak in 22 Indian languages, get clean text in any app.
    BolFlow needs a free Sarvam AI key to hear you.</div>
  <div class="lbl">Paste your Sarvam API key</div>
  <div class="keyrow">
    <input type="text" id="key" placeholder="sk_..." spellcheck="false">
    <button class="btn" id="verify">Verify</button>
  </div>
  <div class="status" id="s1status">Get a free key at platform.sarvam.ai</div>
</div>

<div id="s2" style="display:none">
  <h1>Checking your setup</h1>
  <div class="sub">Everything BolFlow needs, checked live.</div>
  <div class="check"><span>Microphone</span><span class="r wait" id="c-mic">checking…</span></div>
  <div class="check"><span>Sarvam connection</span><span class="r ok" id="c-sarvam">verified</span></div>
</div>

<div id="s3" style="display:none">
  <h1>Try it right here</h1>
  <div class="sub">BolFlow is already running in your tray.</div>
  <div class="keys" id="chord"></div>
  <textarea id="try" placeholder="Click here, hold the keys, speak, release…"></textarea>
  <div class="hintline">Esc while recording cancels. Settings live in the
    tray's mic icon.</div>
  <button class="btn big" id="done">Start dictating</button>
</div>

<div class="nav">
  <button class="ghost" id="back" style="display:none">Back</button>
  <button class="btn" id="next" style="display:none">Next</button>
</div>

<script>
let step = 1, envTimer = null;
function show(n){
  step = n;
  document.getElementById('crumb').textContent = 'Step ' + n + ' of 3';
  for (const i of [1,2,3])
    document.getElementById('s'+i).style.display = i===n ? '' : 'none';
  document.getElementById('back').style.display = n>1 ? '' : 'none';
  document.getElementById('next').style.display = n===2 ? '' : 'none';
  if (n===2){ pollEnv(); envTimer = setInterval(pollEnv, 2000); }
  else if (envTimer){ clearInterval(envTimer); envTimer = null; }
}
async function pollEnv(){
  const e = await pywebview.api.check_env();
  const mic = document.getElementById('c-mic');
  if (e.mic){ mic.className='r ok'; mic.textContent = e.mic; }
  else { mic.className='r bad'; mic.textContent = 'no input device found'; }
}
window.addEventListener('pywebviewready', async ()=>{
  const chord = document.getElementById('chord');
  const labels = await pywebview.api.hotkey_labels();
  chord.innerHTML = labels.map(l=>'<span class="key">'+l+'</span>')
    .join('<span class="plus">+</span>') +
    '<span style="color:#9a9ca6;font-size:13px;margin-left:8px">hold, speak, release</span>';
  document.getElementById('verify').onclick = async ()=>{
    const st = document.getElementById('s1status');
    st.className = 'status wait'; st.textContent = 'Checking with Sarvam…';
    const r = await pywebview.api.verify_key(document.getElementById('key').value);
    if (r.ok){ st.className = 'status ok';
      st.textContent = 'Key verified, round-trip ' + r.latency + ' s. Moving on…';
      setTimeout(()=>show(2), 900);
    } else { st.className = 'status bad'; st.textContent = r.error; }
  };
  document.getElementById('back').onclick = ()=> show(step-1);
  document.getElementById('next').onclick = ()=> show(3);
  document.getElementById('done').onclick = ()=> pywebview.api.finish();
});
</script></body></html>"""


def _windows_chrome():
    import ctypes
    import time
    hwnd = 0
    for _ in range(60):
        hwnd = ctypes.windll.user32.FindWindowW(None, "Welcome to BolFlow")
        if hwnd:
            break
        time.sleep(0.1)
    if not hwnd:
        return
    dark = ctypes.c_int(1)
    ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, 20, ctypes.byref(dark), 4)
    ctypes.windll.user32.SetWindowPos(hwnd, 0, 0, 0, 0, 0, 0x27)
    ico = os.path.join(config.RESOURCE_DIR, "app.ico")
    if os.path.exists(ico):
        for size, which in ((16, 0), (32, 1)):
            h = ctypes.windll.user32.LoadImageW(None, ico, 1, size, size, 0x10)
            if h:
                ctypes.windll.user32.SendMessageW(hwnd, 0x80, which, h)


if __name__ == "__main__":
    webview.create_window(
        "Welcome to BolFlow", html=HTML, js_api=Api(),
        width=560, height=470, background_color="#16161b")
    webview.start(func=_windows_chrome)
