"""Озвучка (голос Piper «Руслан», как в первом ролике) + пословные тайминги субтитров.

-> voice.wav, timings.json: [{scene, start, end, words: [{text, start, hl}]}]
Модель голоса: см. promo/tts.py (лежит в promo/models).
"""
import json
import re
import subprocess
import wave
from pathlib import Path

import numpy as np
import sherpa_onnx

from script import LINES

HERE = Path(__file__).parent
TMP = HERE / "build"
TMP.mkdir(exist_ok=True)
VOICE = HERE.parent / "promo" / "models" / "vits-piper-ru_RU-ruslan-medium"
SR = 44100
SPEED = 1.04
GAP = 0.14  # короткий вдох между репликами — речь идёт без остановок
LEAD, TAIL = 0.3, 0.8
VOWELS = set("аеёиоуыэюяaeiouy")


def parse(line):
    """-> список слов {text, say, hl} и строка для синтеза."""
    words, hl = [], False
    for tok in re.findall(r"\*?\{[^}]*\}\S*|\S+", line):
        start_hl = tok.startswith("*")
        tok = tok.lstrip("*")
        end_hl = tok.endswith("*")
        tok = tok.rstrip("*")
        if start_hl:
            hl = True
        m = re.fullmatch(r"\{([^|]*)\|([^}]*)\}(.*)", tok)
        disp, say = (m.group(1) + m.group(3), m.group(2) + m.group(3)) if m else (tok, tok)
        words.append({"text": disp, "say": say, "hl": hl})
        if end_hl:
            hl = False
    return words, " ".join(w["say"] for w in words)


def weight(say):
    v = sum(ch in VOWELS for ch in say.lower())
    pause = 0.9 if say[-1:] in ".!?:" else 0.5 if say[-1:] in ",—" else 0
    return max(1, v) + pause


TTS = sherpa_onnx.OfflineTts(sherpa_onnx.OfflineTtsConfig(model=sherpa_onnx.OfflineTtsModelConfig(
    vits=sherpa_onnx.OfflineTtsVitsModelConfig(model=str(VOICE / "ru_RU-ruslan-medium.onnx"),
                                               tokens=str(VOICE / "tokens.txt"),
                                               data_dir=str(VOICE / "espeak-ng-data")),
    num_threads=4)))


def synth(text, out):
    audio = TTS.generate(text, sid=0, speed=SPEED)
    raw = out.with_suffix(".raw.wav")
    with wave.open(str(raw), "w") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(audio.sample_rate)
        w.writeframes((np.clip(np.array(audio.samples), -1, 1) * 32767).astype(np.int16).tobytes())
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(raw), "-ar", str(SR), "-ac", "1",
                    "-af", "silenceremove=start_periods=1:start_threshold=-45dB,"
                           "areverse,silenceremove=start_periods=1:start_threshold=-45dB,areverse,"
                           "highpass=f=90,equalizer=f=3200:t=q:w=1:g=3,"
                           "acompressor=threshold=-18dB:ratio=3:attack=5:release=80",
                    str(out)], check=True)
    with wave.open(str(out)) as w:
        return w.getnframes() / w.getframerate()


t, parts, out = LEAD, [], []
for i, (scene, line) in enumerate(LINES):
    words, say = parse(line)
    f = TMP / f"line{i:02d}.wav"
    dur = synth(say, f)
    parts.append((f, t))
    ws = [weight(w["say"]) for w in words]
    total_w, acc = sum(ws), 0.0
    for w, wt in zip(words, ws):
        w["start"] = round(t + dur * acc / total_w, 3)
        acc += wt
        del w["say"]
    out.append({"scene": scene, "start": round(t, 3), "end": round(t + dur, 3), "words": words})
    t += dur + GAP
total = t - GAP + TAIL

inputs, filters = [], []
for i, (f, start) in enumerate(parts):
    inputs += ["-i", str(f)]
    ms = int(start * 1000)
    filters.append(f"[{i}]adelay={ms}|{ms}[a{i}]")
mix = "".join(f"[a{i}]" for i in range(len(parts)))
filters.append(f"{mix}amix=inputs={len(parts)}:normalize=0,apad,atrim=0:{total:.3f},loudnorm=I=-15:TP=-1.5[out]")
subprocess.run(["ffmpeg", "-y", "-loglevel", "error", *inputs, "-filter_complex", ";".join(filters),
                "-map", "[out]", "-ar", str(SR), str(HERE / "voice.wav")], check=True)
(HERE / "timings.json").write_text(json.dumps({"total": round(total, 3), "lines": out}, ensure_ascii=False, indent=1))
print(f"total={total:.2f}s lines={len(out)}")
