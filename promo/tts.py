"""Озвучка промо-ролика Deckcard через RHVoice (офлайн) -> voice.wav + timings.json.

Субтитры показывают text, а голос читает say (там правки ударений/темпа).
"""
import json
import subprocess
import wave
from pathlib import Path

HERE = Path(__file__).parent
TMP = HERE / "build"
TMP.mkdir(exist_ok=True)
VOICE = "aleksandr-hq"
RATE = 22050
TARGET = 15.0
LEAD, TAIL = 0.35, 0.6

LINES = [
    {"text": "Через пять часов сдавать курсовую?", "say": "Через пять часов сдавать курсовую?", "gap": 0.25},
    {"text": "А презентации нет, и ты не успеваешь?", "say": "А презентации нет? И ты не успеваешь?", "gap": 0.35},
    {"text": "Решение есть — Deckcard!", "say": "Решение есть! Деккард!", "gap": 0.3},
    {"text": "Он сделает презентацию за считанные минуты.", "say": "Он сделает презентацию за считанные минуты.", "gap": 0.35},
    {"text": "Deckcard. Презентации за минуты.", "say": "Деккард. Презентации за минуты.", "gap": 0.0},
]


def synth(text, out, rate):
    raw = out.with_suffix(".raw.wav")
    subprocess.run(["RHVoice-test", "-p", VOICE, "-r", str(rate), "-o", str(raw)],
                   input=text.encode(), check=True)
    # единый формат + обрезка тишины по краям
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(raw), "-ar", str(RATE), "-ac", "1",
                    "-af", "silenceremove=start_periods=1:start_threshold=-45dB,"
                           "areverse,silenceremove=start_periods=1:start_threshold=-45dB,areverse",
                    str(out)], check=True)
    with wave.open(str(out)) as w:
        return w.getnframes() / w.getframerate()


def build(rate):
    t, parts = LEAD, []
    for i, ln in enumerate(LINES):
        f = TMP / f"line{i}.wav"
        dur = synth(ln["say"], f, rate)
        parts.append((f, t))
        ln["start"], ln["end"] = round(t, 3), round(t + dur, 3)
        t += dur + ln["gap"]
    return t + TAIL, parts


rate = 100
total, parts = build(rate)
# подгоняем темп речи, чтобы ролик уложился примерно в 15 секунд
for _ in range(4):
    if abs(total - TARGET) < 0.4:
        break
    rate = max(60, min(200, int(rate * total / TARGET)))
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
