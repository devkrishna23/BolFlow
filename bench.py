"""Offline latency benchmark: runs the real Sarvam STT pipeline on WAV
files (no mic/hotkey needed) and reports per-stage timings.
Latency is now network-bound, so run this on the connection you'll dictate on.

Usage: python bench.py <wav-file> [more wav files...]
WAVs must be 16 kHz mono 16-bit PCM (what make_test_audio.ps1 produces).
"""

import sys
import time
import wave

import numpy as np

import cleaner
import config
from transcriber import Transcriber


def read_wav(path: str) -> np.ndarray:
    with wave.open(path, "rb") as w:
        assert w.getframerate() == config.SAMPLE_RATE, f"{path}: need 16 kHz"
        assert w.getnchannels() == 1, f"{path}: need mono"
        pcm = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16)
    return pcm.astype(np.float32) / 32768.0


def main(paths):
    stt = Transcriber()
    print(f"Sarvam {config.SARVAM_MODEL} mode={config.SARVAM_MODE} "
          f"lang={config.SARVAM_LANGUAGE}\n")

    for path in paths:
        audio = read_wav(path)
        dur = len(audio) / config.SAMPLE_RATE
        t0 = time.perf_counter()
        raw = stt.transcribe(audio)
        t1 = time.perf_counter()
        text = cleaner.light_clean(raw)
        print(f"== {path} ({dur:.1f}s audio)")
        print(f"   stt {t1 - t0:.2f}s")
        print(f"   raw:   {raw}")
        print(f"   clean: {text}")
        print()


if __name__ == "__main__":
    main(sys.argv[1:])
