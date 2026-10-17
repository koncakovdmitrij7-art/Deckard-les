"""Лёгкий лоу-фай бит под весь ролик + «поп» на смене сцен -> music.wav (чистый синтез)."""
import json
import wave
from pathlib import Path

import numpy as np

HERE = Path(__file__).parent
SR = 44100
tm = json.loads((HERE / "timings.json").read_text())
TOTAL = tm["total"]
N = int(TOTAL * SR)
rng = np.random.default_rng(11)
out = np.zeros(N)
BPM = 96
BEAT = 60 / BPM


def place(sig, t, gain=1.0):
    i = int(t * SR)
    if 0 <= i < N:
        j = min(N, i + len(sig))
        out[i:j] += sig[: j - i] * gain


def env(n, a, d):
    t = np.arange(n) / SR
    return np.minimum(1, t / a) * np.exp(-t / d)


def note(m):
    return 440 * 2 ** ((m - 69) / 12)


def keys(freq, dur):
    """мягкое электропиано: синус + немного обертонов, медленное затухание."""
    n = int(dur * SR)
    t = np.arange(n) / SR
    s = np.sin(2 * np.pi * freq * t) + 0.3 * np.sin(4 * np.pi * freq * t) + 0.08 * np.sin(6 * np.pi * freq * t)
    trem = 1 + 0.08 * np.sin(2 * np.pi * 4.5 * t)
    return s * trem * env(n, 0.01, 1.4)


def kick():
    n = int(0.3 * SR)
    t = np.arange(n) / SR
    f = 50 + 70 * np.exp(-t * 35)
    return np.sin(2 * np.pi * np.cumsum(f) / SR) * env(n, 0.002, 0.11)


def hat():
    n = int(0.05 * SR)
    x = rng.standard_normal(n)
    x = np.diff(x, prepend=0)
    return x * env(n, 0.001, 0.012)


def snap():
    n = int(0.12 * SR)
    x = rng.standard_normal(n)
    x = np.convolve(x, np.ones(6) / 6, mode="same")
    return x * env(n, 0.001, 0.035)


def pop():
    n = int(0.09 * SR)
    t = np.arange(n) / SR
    f = 500 + 900 * np.exp(-t * 60)
    return np.sin(2 * np.pi * np.cumsum(f) / SR) * env(n, 0.001, 0.03)


chords = [(65, 69, 72, 76), (64, 67, 71, 74), (62, 65, 69, 72), (60, 64, 67, 71)]  # Fmaj7 Em7 Dm7 Cmaj7
bass = [41, 40, 38, 36]
bar = 4 * BEAT
t, k = 0.0, 0
while t < TOTAL:
    for j, m in enumerate(chords[k % 4]):
        place(keys(note(m), bar + 0.5), t + j * 0.012, 0.05)
    place(keys(note(bass[k % 4]), bar), t, 0.10)
    for b in range(4):
        tb = t + b * BEAT
        place(kick(), tb, 0.45 if b in (0, 2) else 0.0)
        place(snap(), tb, 0.22 if b in (1, 3) else 0.0)
        place(hat(), tb + BEAT / 2, 0.12)
    t += bar
    k += 1

prev = None
for ln in tm["lines"]:
    if ln["scene"] != prev:
        place(pop(), ln["start"] - 0.05, 0.35)
    prev = ln["scene"]

out *= np.minimum(1, np.arange(N) / SR / 0.6) * np.minimum(1, (TOTAL - np.arange(N) / SR) / 1.0)
out = out / np.max(np.abs(out)) * 0.8
with wave.open(str(HERE / "music.wav"), "w") as f:
    f.setnchannels(1)
    f.setsampwidth(2)
    f.setframerate(SR)
    f.writeframes((out * 32767).astype(np.int16).tobytes())
print("music.wav", TOTAL)
