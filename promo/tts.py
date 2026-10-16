"""Озвучка промо-ролика Deckcard нейросетевым голосом Piper (офлайн) -> voice.wav + timings.json.

text — реплика (для таймингов сцен), say — то, что читает голос (правки ударений/пауз).
Модель голоса (не хранится в репозитории):
  curl -L https://github.com/k2-fsa/sherpa-onnx/releases/download/tts-models/vits-piper-ru_RU-dmitri-medium.tar.bz2 \
    | tar xj -C promo/models
  pip install sherpa-onnx
"""
import json
import numpy as np
import sherpa_onnx
import subprocess
import wave
from pathlib import Path

HERE = Path(__file__).parent
TMP = HERE / "build"
TMP.mkdir(exist_ok=True)
VOICE = HERE / "models" / "vits-piper-ru_RU-dmitri-medium"
RATE = 44100
TARGET = 15.0
LEAD, TAIL = 0.35, 0.6

LINES = [
    {"text": "Через пять часов сдавать курсовую?", "say": "Через пять часов сдавать курсовую?", "gap": 0.25},
    {"text": "А презентации нет, и ты не успеваешь?", "say": "А презентации нет? И ты не успеваешь?", "gap": 0.35},
    {"text": "Решение есть — Deckcard!", "say": "Решение есть! Деккард!", "gap": 0.3},
    {"text": "Он сделает презентацию за считанные минуты.", "say": "Он сделает презентацию за считанные минуты.", "gap": 0.35},
    {"text": "Deckcard. Презентации за минуты.", "say": "Деккард. Презентации за минуты.", "gap": 0.0},
]


TTS = sherpa_onnx.OfflineTts(sherpa_onnx.OfflineTtsConfig(model=sherpa_onnx.OfflineTtsModelConfig(
    vits=sherpa_onnx.OfflineTtsVitsModelConfig(model=str(VOICE / "ru_RU-dmitri-medium.onnx"),
                                               tokens=str(VOICE / "tokens.txt"),
                                               data_dir=str(VOICE / "espeak-ng-data")),
    num_threads=4)))


def synth(text, out, rate):
    """rate — темп в процентах (100 = обычный)."""
    audio = TTS.generate(text, sid=0, speed=rate / 100)
    raw = out.with_suffix(".raw.wav")
    with wave.open(str(raw), "w") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(audio.sample_rate)
        w.writeframes((np.clip(np.array(audio.samples), -1, 1) * 32767).astype(np.int16).tobytes())
    # единый формат, обрезка тишины по краям, «дикторская» обработка: срез низа, присутствие, компрессия
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(raw), "-ar", str(RATE), "-ac", "1",
                    "-af", "silenceremove=start_periods=1:start_threshold=-45dB,"
                           "areverse,silenceremove=start_periods=1:start_threshold=-45dB,areverse,"
                           "highpass=f=90,equalizer=f=3200:t=q:w=1:g=3,"
                           "acompressor=threshold=-18dB:ratio=3:attack=5:release=80",
                    str(out)], check=True)
    with wave.open(str(out)) as w:
        return w.getnframes() / w.getframerate()


def build(rate):
    global TAIL
    t, parts = LEAD, []
    for i, ln in enumerate(LINES):
        f = TMP / f"line{i}.wav"
        dur = synth(ln["say"], f, rate)
        parts.append((f, t))
        ln["start"], ln["end"] = round(t, 3), round(t + dur, 3)
        t += dur + ln["gap"]
    return t + TAIL, parts


rate = 95  # естественный темп
total, parts = build(rate)
# добиваем до ~15 с паузами между репликами, а не замедлением речи
extra = TARGET - total
if extra > 0:
    gaps = [ln for ln in LINES[:-1]]
    for ln in gaps:
        ln["gap"] += extra * 0.8 / len(gaps)
    TAIL += extra * 0.2
    total, parts = build(rate)

inputs, filters = [], []
for i, (f, start) in enumerate(parts):
    inputs += ["-i", str(f)]
    ms = int(start * 1000)
    filters.append(f"[{i}]adelay={ms}|{ms}[a{i}]")
mixin = "".join(f"[a{i}]" for i in range(len(parts)))
filters.append(f"{mixin}amix=inputs={len(parts)}:normalize=0,apad,atrim=0:{total:.3f},"
               f"loudnorm=I=-14:TP=-1.5[out]")
subprocess.run(["ffmpeg", "-y", "-loglevel", "error", *inputs, "-filter_complex", ";".join(filters),
                "-map", "[out]", "-ar", "44100", str(HERE / "voice.wav")], check=True)

(HERE / "timings.json").write_text(json.dumps(
    {"total": round(total, 3), "rate": rate,
     "lines": [{k: ln[k] for k in ("text", "start", "end")} for ln in LINES]},
    ensure_ascii=False, indent=2))
print(f"rate={rate} total={total:.2f}s")
