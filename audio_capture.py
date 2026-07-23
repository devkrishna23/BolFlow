"""Always-open microphone stream with a pre-roll buffer.

The input stream runs permanently so recording starts with zero latency —
opening a stream on key-press takes 100-300 ms and clips the first word.
A small rolling pre-roll buffer captures speech that starts a hair before
the key does.
"""

import collections
import threading

import numpy as np
import sounddevice as sd

import config


class MicStream:
    def __init__(self):
        self._lock = threading.Lock()
        self._recording = False
        self.level = 0.0  # smoothed mic RMS, read by the HUD ribbon
        self.chunk_sink = None  # optional callable(chunk) fed live while
                                # recording (streaming STT); set per-utterance
        self._chunks: list[np.ndarray] = []
        # rolling buffer of the most recent audio, kept while idle
        self._preroll = collections.deque()
        self._preroll_samples = 0
        self._preroll_max = int(config.PRE_ROLL_SECONDS * config.SAMPLE_RATE)
        self._stream = sd.InputStream(
            device=config.MIC_DEVICE,
            samplerate=config.SAMPLE_RATE,
            channels=1,
            dtype="float32",
            callback=self._callback,
        )
        self._stream.start()

    def _callback(self, indata, frames, time_info, status):
        chunk = indata[:, 0].copy()
        rms = float(np.sqrt(np.mean(chunk * chunk)))
        # fast attack, slow release - reads as natural on the ribbon
        self.level = max(rms, self.level * 0.85)
        with self._lock:
            if self._recording:
                self._chunks.append(chunk)
                # sink is called under the lock: chunk order into the
                # streaming session must match _chunks, and start/stop
                # (which also hold the lock) must never interleave with it
                if self.chunk_sink is not None:
                    self.chunk_sink(chunk)
                self._preroll.append(chunk)
                self._preroll_samples += len(chunk)
                while self._preroll_samples > self._preroll_max and len(self._preroll) > 1:
                    dropped = self._preroll.popleft()
                    self._preroll_samples -= len(dropped)

    def start_recording(self, chunk_sink=None):
        if not self._stream.active:
            # device vanished (Bluetooth headset slept, USB mic unplugged):
            # PortAudio kills the stream silently - reopen so the next
            # dictation self-heals instead of recording nothing forever
            try:
                self._stream.close()
            except Exception:
                pass
            try:
                self._stream = sd.InputStream(
                    device=config.MIC_DEVICE,
                    samplerate=config.SAMPLE_RATE, channels=1,
                    dtype="float32", callback=self._callback)
                self._stream.start()
                print("(mic stream reopened)")
            except Exception as e:
                print(f"  [mic unavailable: {e}]")
        with self._lock:
            if self._recording:
                return
            self._chunks = list(self._preroll)  # seed with pre-roll audio
            if chunk_sink is not None:
                for chunk in self._chunks:      # pre-roll to the stream first,
                    chunk_sink(chunk)           # still under the lock, so live
            self.chunk_sink = chunk_sink        # chunks can't jump the queue
            self._recording = True

    def stop_recording(self) -> np.ndarray:
        """Return the recorded utterance as float32 mono at SAMPLE_RATE."""
        with self._lock:
            self._recording = False
            self.chunk_sink = None
            chunks, self._chunks = self._chunks, []
            self._preroll.clear()
            self._preroll_samples = 0
        if not chunks:
            return np.zeros(0, dtype=np.float32)
        return np.concatenate(chunks)

    def close(self):
        self._stream.stop()
        self._stream.close()
