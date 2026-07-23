"""Sarvam speech-to-text clients: streaming WebSocket (primary) + REST
(fallback and bench).

Streaming: audio chunks are sent over the WebSocket *while the user speaks*,
so the server has transcribed all but the final VAD segment by the time the
hotkey is released - the post-release wait is one segment's inference
(~0.5-1.3 s) instead of the whole utterance's upload + inference. The server
returns one `data` message per speech segment, each with its own
language_code; the final transcript is their concatenation.

REST: one-shot POST of the whole utterance. Used by bench.py and as the
automatic fallback whenever a streaming session fails.
"""

import asyncio
import base64
import concurrent.futures
import io
import threading
import wave

import httpx
import numpy as np

import config

_ENDPOINT = "https://api.sarvam.ai/speech-to-text"


def _to_wav_bytes(audio: np.ndarray) -> bytes:
    pcm = (np.clip(audio, -1.0, 1.0) * 32767).astype(np.int16)
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(config.SAMPLE_RATE)
        w.writeframes(pcm.tobytes())
    return buf.getvalue()


class Transcriber:
    def __init__(self):
        self.last_language = ""   # detected language_code of the last call
        if not config.SARVAM_API_KEY:
            raise RuntimeError(
                "No Sarvam API key. Set the SARVAM_API_KEY environment "
                "variable (get a key at https://dashboard.sarvam.ai), "
                "then restart the app.")
        self.client = httpx.Client(
            headers={"api-subscription-key": config.SARVAM_API_KEY},
            timeout=config.SARVAM_TIMEOUT,
        )

    def warm(self):
        """Fire-and-forget: open (or refresh) the pooled TLS connection to the
        API so the transcribe call doesn't pay the handshake. Call on hotkey
        press - it runs concurrently with the user speaking."""
        def _ping():
            try:
                self.client.get("https://api.sarvam.ai/", timeout=5.0)
            except httpx.HTTPError:
                pass  # offline etc.; transcribe() will surface the real error
        threading.Thread(target=_ping, daemon=True).start()

    def transcribe(self, audio: np.ndarray) -> str:
        duration = len(audio) / config.SAMPLE_RATE
        if duration < config.MIN_UTTERANCE_SECONDS:
            return ""
        r = self.client.post(
            _ENDPOINT,
            files={"file": ("utterance.wav", _to_wav_bytes(audio), "audio/wav")},
            data={
                "model": config.SARVAM_MODEL,
                "mode": config.SARVAM_MODE,
                "language_code": config.SARVAM_LANGUAGE,
            },
        )
        r.raise_for_status()
        data = r.json()
        self.last_language = data.get("language_code") or ""
        return data.get("transcript", "").strip()


class StreamingTranscriber:
    """Owns a background asyncio loop; hands out one StreamingSession per
    utterance. Import of sarvamai is deferred so the REST path (bench.py)
    doesn't require it."""

    def __init__(self):
        from sarvamai import AsyncSarvamAI
        self.loop = asyncio.new_event_loop()
        threading.Thread(target=self.loop.run_forever, daemon=True).start()
        self.client = AsyncSarvamAI(
            api_subscription_key=config.SARVAM_API_KEY)

    def start_session(self):
        return StreamingSession(self.loop, self.client)


class StreamingSession:
    """One dictation utterance over the streaming WebSocket.

    feed() is called from the audio callback thread with raw float32 chunks;
    finish() blocks the worker thread until the tail segment arrives (or
    raises, in which case the caller falls back to REST)."""

    _CANCEL = object()
    _EOS = object()

    def __init__(self, loop, client):
        self.loop = loop
        self.client = client
        self.queue = asyncio.Queue()
        self.result = concurrent.futures.Future()
        self.segments = []      # (transcript, language_code)
        self._pcm_buf = []
        self._pcm_samples = 0
        self._last_data = 0.0   # loop-clock time of the last data message
        asyncio.run_coroutine_threadsafe(self._run(), loop)

    def live_text(self) -> str:
        """Transcript so far - read by the HUD while the user is speaking."""
        return " ".join(s[0] for s in self.segments if s[0]).strip()

    # --- called from the audio callback thread -----------------------------
    def feed(self, chunk: np.ndarray):
        self._pcm_buf.append(chunk)
        self._pcm_samples += len(chunk)
        if self._pcm_samples >= int(0.25 * config.SAMPLE_RATE):
            self._flush_buf()

    def _flush_buf(self):
        if not self._pcm_buf:
            return
        audio = np.concatenate(self._pcm_buf)
        self._pcm_buf, self._pcm_samples = [], 0
        b64 = base64.b64encode(_to_wav_bytes(audio)).decode()
        self.loop.call_soon_threadsafe(self.queue.put_nowait, b64)

    # --- called from the app/worker threads --------------------------------
    def finish(self) -> tuple[str, set]:
        """Returns (transcript, {language_codes}). Raises on session failure."""
        self._flush_buf()
        self.loop.call_soon_threadsafe(self.queue.put_nowait, self._EOS)
        return self.result.result(timeout=config.SARVAM_TIMEOUT)

    def cancel(self):
        self.loop.call_soon_threadsafe(self.queue.put_nowait, self._CANCEL)

    # --- runs on the asyncio loop ------------------------------------------
    async def _run(self):
        segments = self.segments
        try:
            async with self.client.speech_to_text_streaming.connect(
                model=config.SARVAM_MODEL,
                mode=config.SARVAM_MODE,
                language_code=config.SARVAM_LANGUAGE,
                # NOTE: high_vad_sensitivity=True makes the live transcript
                # update ~2x sooner but chops segments mid-phrase and
                # measurably degrades accuracy - keep the server default.
            ) as ws:
                recv = asyncio.create_task(self._receiver(ws, segments))
                try:
                    while True:
                        item = await self.queue.get()
                        if item is self._CANCEL:
                            self.result.set_result(("", set()))
                            return
                        if item is self._EOS:
                            break
                        await ws.transcribe(audio=item, encoding="audio/wav",
                                            sample_rate=config.SAMPLE_RATE)
                    t_flush = self.loop.time()
                    self._last_data = 0.0
                    await ws.flush()
                    # The server has no end-of-results signal. Post-flush it
                    # finalizes whatever audio is still buffered (typically 1
                    # tail segment, ~0.5-1.3 s). Done when results have gone
                    # quiet, or when nothing at all shows up (tail was
                    # silence), with a hard deadline as the backstop.
                    while True:
                        now = self.loop.time()
                        if self._last_data > t_flush and \
                                now - self._last_data > 0.3:
                            break                      # tail arrived + quiet
                        if self._last_data <= t_flush and now - t_flush > 2.0:
                            break                      # nothing was pending
                        if now - t_flush > 4.0:
                            break                      # backstop
                        await asyncio.sleep(0.05)
                finally:
                    recv.cancel()
            text = " ".join(s[0] for s in segments if s[0]).strip()
            langs = {s[1] for s in segments if s[0] and s[1]}
            self.result.set_result((text, langs))
        except Exception as e:
            if not self.result.done():
                self.result.set_exception(e)

    async def _receiver(self, ws, segments):
        async for msg in ws:
            if getattr(msg, "type", "") == "data" and msg.data:
                d = msg.data
                segments.append(((d.transcript or "").strip(),
                                 d.language_code or ""))
                self._last_data = self.loop.time()
