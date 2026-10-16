"""Фоновый бит + SFX под тайминги ролика -> music.wav (синтез, без сторонних семплов).

До реплики «Решение есть» — напряжённый пэд и тиканье часов,
затем райзер, удар и бит 120 BPM до конца.
"""
import json
import wave
from pathlib import Path

import numpy as np

HERE = Path(__file__).parent
SR = 44100
timings = json.loads((HERE / "timings.json").read_text())
LINES = timings["lines"]
TOTAL = timings["total"]
N = int(TOTAL * SR)
DROP = LINES[2]["start"]  # момент появления Deckcard
rng = np.random.default_rng(7)
out = np.zeros(N)


def place(sig, t, gain=1.0):
    i = int(t * SR)
    if i >= N:
        return
    j = min(N, i + len(sig))
    out[i:j] += sig[: j - i] * gain


def env(n, attack=0.005, decay=0.2):
    t = np.arange(n) / SR
    return np.minimum(1, t / attack) * np.exp(-t / decay)


def lowpass(x, k):
    y = np.empty_like(x)
    acc = 0.0
    for i, v in enumerate(x):
        acc += k * (v - acc)
        y[i] = acc
    return y


def kick():
    n = int(0.35 * SR)
    t = np.arange(n) / SR
    f = 45 + 110 * np.exp(-t * 30)
    return np.sin(2 * np.pi * np.cumsum(f) / SR) * env(n, 0.002, 0.12)


def hat():
    n = int(0.06 * SR)
    x = rng.standard_normal(n)
    x = x - lowpass(x, 0.3)
    return x * env(n, 0.001, 0.015)


def tick(high):
    n = int(0.05 * SR)
    t = np.arange(n) / SR
    return np.sin(2 * np.pi * (2400 if high else 1800) * t) * env(n, 0.0005, 0.008)


def tone(freq, dur, harmonics=(1, 0.5, 0.25), decay=None):
    n = int(dur * SR)
    t = np.arange(n) / SR
    s = sum(a * np.sin(2 * np.pi * freq * (k + 1) * t) for k, a in enumerate(harmonics))
    e = np.minimum(1, t / 0.08) * np.minimum(1, (dur - t) / 0.15)
    if decay:
        e = e * np.exp(-t / decay)
    return s * e


def note(midi):
    return 440 * 2 ** ((midi - 69) / 12)


# --- пэд: Am – F – C – G, по 2 секунды
chords = [(57, 60, 64), (53, 57, 60), (48, 55, 64), (55, 59, 62)]
t = 0.0
k = 0
while t < TOTAL:
    for m in chords[k % 4]:
        place(tone(note(m), 2.1, (1, 0.35, 0.12)), t, 0.06 if t < DROP else 0.08)
    k += 1
    t += 2.0

# --- до дропа: тиканье часов
t = 0.3
i = 0
while t < DROP - 0.6:
    place(tick(i % 2 == 0), t, 0.35)
    t += 0.5
    i += 1

# --- райзер перед дропом
rn = int(1.2 * SR)
rt = np.arange(rn) / SR
riser = rng.standard_normal(rn)
riser = riser - lowpass(riser, 0.6)
riser *= (rt / rt[-1]) ** 2.5
place(riser, DROP - 1.2, 0.18)

# --- дроп: удар + бит 120 BPM
boom = kick() * 1.4
place(boom, DROP, 0.9)
bass = [45, 41, 36, 43]
t = DROP
beat = 0
while t < TOTAL - 0.3:
    place(kick(), t, 0.55)
    place(hat(), t + 0.25, 0.25)
    if beat % 2 == 0:
        bar = int((t - DROP) // 2) % 4
        place(tone(note(bass[bar]), 0.45, (1, 0.3), decay=0.3), t, 0.22)
    t += 0.5
    beat += 1

# --- свуши на сменах сцен
for ln in LINES[1:]:
    wn = int(0.4 * SR)
    w = rng.standard_normal(wn)
    w = lowpass(w, 0.15)
    w *= np.sin(np.pi * np.arange(wn) / wn) ** 2
    place(w, ln["start"] - 0.2, 0.5)

out *= np.minimum(1, (TOTAL - np.arange(N) / SR) / 0.5)  # затухание в конце
out = out / np.max(np.abs(out)) * 0.8
with wave.open(str(HERE / "music.wav"), "w") as f:
    f.setnchannels(1)
    f.setsampwidth(2)
    f.setframerate(SR)
    f.writeframes((out * 32767).astype(np.int16).tobytes())
print("music.wav", TOTAL)
