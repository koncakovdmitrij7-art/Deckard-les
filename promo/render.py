"""Рендер 15-секундного промо-ролика Deckcard для TikTok (1080x1920, 60 fps).

Верх кадра — анимированные сцены, низ — живой персонаж-маскот
(перекладная анимация из puppet.py): ходит, жестикулирует, прыгает,
моргает и кивает в такт озвучке. Субтитров нет.
Кадры рисуются Pillow и уходят в ffmpeg через pipe; звук — voice.wav
(tts.py) + music.wav (music.py) с ducking-ом музыки под голос.
Важное держим вне зон интерфейса TikTok (верх ~180px, правая колонка
кнопок, подпись снизу).
"""
import json
import multiprocessing as mp
import math
import random
import subprocess
import sys
import wave
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

from puppet import Puppet

HERE = Path(__file__).parent
W, H, FPS = 1080, 1920, 60
FONT_DIR = "/usr/share/fonts/opentype/inter/"


def font(weight, size):
    return ImageFont.truetype(f"{FONT_DIR}Inter-{weight}.otf", size)


F_SMALL = font("SemiBold", 40)
F_MID = font("ExtraBold", 66)
F_BUBBLE = font("ExtraBold", 50)

BG = (9, 10, 22)
ACCENT = (124, 92, 255)
ACCENT2 = (0, 222, 186)
GOLD = (255, 196, 92)
RED = (255, 64, 92)
WHITE = (247, 247, 255)
MUTED = (150, 154, 190)
INK = (18, 18, 30)

timings = json.loads((HERE / "timings.json").read_text())
LINES = timings["lines"]
TOTAL = timings["total"]
B = [ln["start"] for ln in LINES] + [TOTAL]
B[0] = 0.0

# --- огибающая голоса: по ней маскот «говорит»
with wave.open(str(HERE / "voice.wav")) as wf:
    sr = wf.getframerate()
    ch = wf.getnchannels()
    pcm = np.frombuffer(wf.readframes(wf.getnframes()), dtype=np.int16).astype(float)
pcm = pcm.reshape(-1, ch).mean(axis=1)
hop = sr // FPS
rms = np.array([np.sqrt(np.mean(pcm[i:i + hop] ** 2) + 1e-9) for i in range(0, len(pcm), hop)])
rms = rms / np.percentile(rms, 95)
VOICE_ENV = np.clip(np.convolve(rms, np.ones(4) / 4, mode="same"), 0, 1)


def voice_env(t):
    i = int(t * FPS)
    return float(VOICE_ENV[i]) if i < len(VOICE_ENV) else 0.0


# --- маскот (перекладная анимация, см. puppet.py)
MASCOT_H = 880
PUPPET = Puppet(HERE / "assets" / "mascot.png", MASCOT_H)
GROUND = 1895  # y ступней на экране
BLINKS = (1.1, 3.0, 5.5, 7.9, 10.3, 12.4, 14.1)

# --- частицы фона
random.seed(3)
PARTICLES = [(random.random() * W, random.random() * H, random.uniform(8, 40),
              random.uniform(2, 6), random.random() * 6.28) for _ in range(70)]


def ease(t):
    t = max(0.0, min(1.0, t))
    return 1 - (1 - t) ** 3


def ease_back(t):
    t = max(0.0, min(1.0, t))
    c = 1.9
    return 1 + (c + 1) * (t - 1) ** 3 + c * (t - 1) ** 2


def lerp(a, b, t):
    return a + (b - a) * t


def mix(c1, c2, t):
    return tuple(int(lerp(a, b, t)) for a, b in zip(c1, c2))


def rgba(c, a):
    return (*c, int(255 * max(0.0, min(1.0, a))))


def text_c(d, x, y, s, f, fill):
    d.text((x, y), s, font=f, fill=fill, anchor="mm")


TINTS = (RED, (150, 30, 70), ACCENT, ACCENT2, ACCENT)


def scene_idx(t):
    return max(i for i in range(len(B) - 1) if B[i] <= t)


def background(t):
    # мягкие цветные пятна, плавно перетекающие между сценами (считаем в 1/4 разрешения)
    i = scene_idx(t)
    k = ease((t - B[i]) / 0.5)
    tint = mix(TINTS[max(0, i - 1)], TINTS[i], k if i else 1)
    sw, sh = W // 4, H // 4
    small = Image.new("RGB", (sw, sh), BG)
    g = ImageDraw.Draw(small)
    blobs = ((0.5 + 0.18 * math.sin(t * 0.8), 0.28 + 0.05 * math.cos(t * 0.6), 190, tint, 0.55),
             (0.15 + 0.1 * math.cos(t * 0.5), 0.75, 150, ACCENT, 0.35),
             (0.9, 0.55 + 0.08 * math.sin(t * 0.7), 120, mix(tint, ACCENT2, 0.5), 0.25))
    for bx, by, r, c, a in blobs:
        cx, cy = bx * sw, by * sh
        g.ellipse((cx - r, cy - r, cx + r, cy + r), fill=mix(BG, c, a))
    small = small.filter(ImageFilter.GaussianBlur(48))
    img = small.resize((W, H), Image.BILINEAR)
    d = ImageDraw.Draw(img)
    # еле заметная сетка
    off = (t * 30) % 90
    for x in range(0, W + 90, 90):
        d.line((x - off, 0, x - off, H), fill=mix(BG, WHITE, 0.035))
    for y in range(0, H + 90, 90):
        d.line((0, y + off, W, y + off), fill=mix(BG, WHITE, 0.035))
    # частицы
    for px, py, sp, r, ph in PARTICLES:
        y = (py - t * sp * 6) % H
        x = px + math.sin(t + ph) * 20
        a = 0.25 + 0.25 * math.sin(t * 2 + ph)
        d.ellipse((x - r, y - r, x + r, y + r), fill=mix(img.getpixel((int(x) % W, int(y) % H)), WHITE, a))
    return img


# ---------------- сцены (рисуют на прозрачном слое, зона y≈190..900)

def scene_clock(d, t, lt, dur):
    remaining = 5 * 3600 - int(lt * 1400)
    hh, mm, ss = remaining // 3600, remaining % 3600 // 60, remaining % 60
    a = ease(lt / 0.35)
    pulse = 0.5 + 0.5 * math.sin(t * 10)
    text_c(d, W / 2, 300, "ДО СДАЧИ КУРСОВОЙ", F_SMALL, rgba(MUTED, a))
    s = lerp(1.25, 1.0, ease(lt / 0.5))
    text_c(d, W / 2, 470, f"{hh:02d}:{mm:02d}:{ss:02d}", font("Black", int(176 * s)),
           rgba(mix(WHITE, RED, 0.55 + 0.45 * pulse), a))
    x0, x1, y = 150, W - 150, 610
    d.rounded_rectangle((x0, y, x1, y + 18), 9, fill=rgba((40, 40, 64), a))
    d.rounded_rectangle((x0, y, x0 + (x1 - x0) * remaining / 18000, y + 18), 9, fill=rgba(RED, a))
    for i, word in enumerate(("ДЕДЛАЙН", "БЛИЗКО")):
        b = ease((lt - 0.5 - i * 0.25) / 0.3)
        d.text((W / 2 + (i * 2 - 1) * 14, 730 + (1 - b) * 40), word, font=font("Black", 66),
               fill=rgba(RED if i else WHITE, b), anchor="lm" if i else "rm")


def scene_empty(d, t, lt, dur):
    shake = math.sin(t * 70) * 7 * (1 - ease((lt - 0.4) / 0.4))
    a = ease(lt / 0.3)
    x0, y0, x1, y1 = 130 + shake, 220, W - 130 + shake, 520
    d.rounded_rectangle((x0, y0, x1, y1), 26, fill=rgba((26, 28, 48), a), outline=rgba((70, 74, 110), a), width=4)
    d.text((x0 + 50, y0 + 45), "Слайд 1 из 15", font=F_SMALL, fill=rgba(MUTED, a))
    if int(t * 2.5) % 2 == 0:
        d.rectangle((x0 + 50, y0 + 130, x0 + 57, y0 + 210), fill=rgba(WHITE, a))
    for i, (q, c) in enumerate((("Что писать?", WHITE), ("Какой дизайн?", WHITE), ("Не успеваю!", RED))):
        b = ease_back((lt - 0.25 - i * 0.4) / 0.35)
        if b <= 0:
            continue
        f = font("ExtraBold", int(64 * max(0.01, b)))
        text_c(d, W / 2 + (i - 1) * 40, 620 + i * 95, q, f, rgba(c, min(1, b)))


def logo(layer, cx, cy, s, a, spin=0.0):
    """Логотип Deckcard: белая карточка с «dc» + цветные карточки-слайды позади."""
    d = ImageDraw.Draw(layer)
    w, h = 300 * s, 190 * s
    for i, c in enumerate((ACCENT2, ACCENT)):
        off = (2 - i) * 34 * s * ease(a)
        d.rounded_rectangle((cx - w / 2 + off, cy - h / 2 - off, cx + w / 2 + off, cy + h / 2 - off),
                            int(28 * s), fill=rgba(c, a))
    d.rounded_rectangle((cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2), int(28 * s), fill=rgba(WHITE, a))
    d.rounded_rectangle((cx - w / 2 + 22 * s, cy - h / 2 + 22 * s, cx + w / 2 - 22 * s, cy + h / 2 - 22 * s),
                        int(10 * s), outline=rgba(INK, a), width=max(2, int(5 * s)))
    text_c(d, cx, cy - 6 * s, "dc", font("Black", int(110 * s)), rgba(INK, a))


def scene_reveal(d, t, lt, dur, layer):
    a = ease(lt / 0.25)
    s = ease_back(lt / 0.55)
    # вспышка-лучи
    rays = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    rd = ImageDraw.Draw(rays)
    for k in range(12):
        ang = k * math.pi / 6 + t * 0.6
        rd.polygon([(W / 2, 400), (W / 2 + 900 * math.cos(ang - 0.08), 400 + 900 * math.sin(ang - 0.08)),
                    (W / 2 + 900 * math.cos(ang + 0.08), 400 + 900 * math.sin(ang + 0.08))],
                   fill=rgba(WHITE, 0.07 * a))
    layer.alpha_composite(rays.filter(ImageFilter.GaussianBlur(6)))
    logo(layer, W / 2, 400, 1.15 * max(0.01, s), a)
    name_s = lerp(1.4, 1.0, ease(lt / 0.4))
    text_c(d, W / 2, 660, "DECKCARD", font("Black", int(150 * name_s)), rgba(WHITE, ease((lt - 0.1) / 0.3)))
    b = ease((lt - 0.35) / 0.4)
    text_c(d, W / 2, 770, "решение есть", font("Bold", 52), rgba(ACCENT2, b))


def scene_build(d, t, lt, dur):
    p = ease(lt / (dur * 0.9))
    titles = ("Введение", "Цели и задачи", "Методология", "Результаты", "Выводы")
    colors = (ACCENT, ACCENT2, GOLD, (255, 92, 160), ACCENT)
    for i, title in enumerate(titles):
        ap = ease_back((lt - i * 0.3) / 0.4)
        if ap <= 0:
            continue
        a = min(1, ap)
        w, h = 390, 160
        col, row = i % 2, i // 2
        x = 115 + col * 460
        y = 190 + row * 190
        if i == 4:
            x = (W - w) / 2
        y += (1 - ap) * 120
        d.rounded_rectangle((x, y, x + w, y + h), 22, fill=rgba((30, 33, 58), a))
        d.rounded_rectangle((x, y, x + w, y + 46), 22, fill=rgba(colors[i], a))
        d.rectangle((x, y + 24, x + w, y + 46), fill=rgba(colors[i], a))
        d.text((x + 26, y + 62), title, font=font("Bold", 38), fill=rgba(WHITE, a))
        for k in range(2):
            d.rounded_rectangle((x + 26, y + 118 + k * 22, x + 26 + (290 - k * 90), y + 128 + k * 22),
                                5, fill=rgba(MUTED, a * 0.55))
        if ap >= 1 and lt - i * 0.3 < 0.9:  # галочка «готово»
            d.ellipse((x + w - 50, y + 60, x + w - 14, y + 96), fill=rgba(ACCENT2, a))
            d.line((x + w - 41, y + 78, x + w - 34, y + 86, x + w - 22, y + 70), fill=rgba(INK, a), width=5)
    x0, x1, y = 150, W - 150, 790
    d.rounded_rectangle((x0, y, x1, y + 18), 9, fill=rgba((40, 40, 64), 1))
    d.rounded_rectangle((x0, y, x0 + (x1 - x0) * p, y + 18), 9, fill=rgba(ACCENT2, 1))
    text_c(d, W / 2, y + 60, f"Готово {int(p * 100)}%  ·  {lt:0.1f} c", F_SMALL, rgba(WHITE, 1))


def scene_cta(d, t, lt, dur, layer):
    a = ease(lt / 0.35)
    logo(layer, W / 2, 330, 0.95 * max(0.01, ease_back(lt / 0.5)), a)
    text_c(d, W / 2, 540, "DECKCARD", font("Black", 140), rgba(WHITE, a))
    text_c(d, W / 2, 640, "Презентации", F_MID, rgba(WHITE, ease((lt - 0.2) / 0.35)))
    text_c(d, W / 2, 720, "за минуты", F_MID, rgba(ACCENT2, ease((lt - 0.35) / 0.35)))
    b = ease_back((lt - 0.6) / 0.4)
    if b > 0:
        pulse = 1 + 0.03 * math.sin(t * 8)
        bw, bh = 520 * b * pulse, 104 * b * pulse
        cy = 830
        d.rounded_rectangle((W / 2 - bw / 2, cy - bh / 2, W / 2 + bw / 2, cy + bh / 2), int(bh / 2),
                            fill=rgba(ACCENT, min(1, b)))
        text_c(d, W / 2, cy, "Попробуй сейчас →", font("Bold", max(1, int(44 * b))), rgba(WHITE, min(1, b)))


SCENES = (scene_clock, scene_empty, scene_reveal, scene_build, scene_cta)


def scene_layer(i, t):
    layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    lt, dur = t - B[i], B[i + 1] - B[i]
    if SCENES[i] in (scene_reveal, scene_cta):
        SCENES[i](d, t, lt, dur, layer)
    else:
        SCENES[i](d, t, lt, dur)
    return layer


def transform(layer, scale, alpha, dy=0):
    if scale != 1:
        sw, sh = int(W * scale), int(H * scale)
        sc = layer.resize((sw, sh), Image.BILINEAR)
        layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        layer.alpha_composite(sc, ((W - sw) // 2, int((H - sh) * 0.28) + dy) if sw <= W else (0, 0),
                              ((sw - W) // 2, int((sh - H) * 0.28)) if sw > W else (0, 0))
    if alpha < 1:
        layer.putalpha(layer.getchannel("A").point(lambda v: int(v * alpha)))
    return layer


# ---------------- маскот: хореография по сценам

def smooth(t):
    t = max(0.0, min(1.0, t))
    return t * t * (3 - 2 * t)


def walk(ph, amp):
    s = math.sin(ph)
    return dict(legL=9 * s * amp, legR=9 * s * amp, liftL=max(0, s) * 45 * amp, liftR=max(0, -s) * 45 * amp,
                body=4 * s * amp, y=-abs(s) * 16 * amp, armL=12 * s * amp, armR=-8 * s * amp)


def add(*ds):
    out = {}
    for d in ds:
        for k, v in d.items():
            out[k] = out.get(k, 0.0) + v
    return out


def seg_intro(t):
    """Выходит слева, останавливается и показывает на таймер."""
    u = t / 1.6
    x = lerp(-330, 430, smooth(u))
    amp = 1 - smooth((t - 1.45) / 0.3)
    k = smooth((t - 1.5) / 0.4)
    return add(walk(x / 38, amp), dict(x=x, armL=k * (38 + 10 * math.sin(t * 5)), head=k * (-7 + 3 * math.sin(t * 2)),
                                       armR=k * 8))


def seg_panic(t):
    """Паника: машет руками, трясёт головой, подпрыгивает."""
    lt = t - B[1]
    return dict(x=430 + 22 * math.sin(lt * 6.5), armL=45 + 38 * math.sin(lt * 13), armR=8 + 22 * math.sin(lt * 13 + 3.1),
                head=10 * math.sin(lt * 8), y=-abs(math.sin(lt * 6.5)) * 50, body=4 * math.sin(lt * 13),
                squash=0.04 * math.cos(lt * 13))


def seg_reveal(t):
    """Прыжок от радости с поднятыми руками."""
    lt = t - B[2]
    u = lt / 0.75
    y = -math.sin(math.pi * min(1, max(0, u))) * 210 if u < 1 else 0
    sq = -0.06 * math.sin(math.pi * min(1, u)) if u < 1 else 0.1 * math.sin(math.pi * min(1, (u - 1) / 0.35))
    tuck = math.sin(math.pi * min(1, max(0, u))) if u < 1 else 0
    return dict(x=430, y=y, squash=sq, armL=88 + 10 * math.sin(lt * 12), armR=35 + 6 * math.sin(lt * 12),
                head=6 * math.sin(lt * 5), legL=-10 * tuck, legR=10 * tuck)


def seg_build(t):
    """Идёт к центру и показывает на собирающиеся слайды."""
    lt = t - B[3]
    x = lerp(430, 575, smooth(lt / 1.1))
    amp = 1 - smooth((lt - 1.1) / 0.3)
    k = smooth((lt - 0.9) / 0.5)
    return add(walk(x / 38, amp), dict(x=x, armL=k * (58 + 6 * math.sin(lt * 3)), armR=k * (15 + 8 * math.sin(lt * 2.5)),
                                       head=k * (-5 + 2 * math.sin(lt * 2)), body=k * 2 * math.sin(lt * 2)))


def seg_cta(t):
    """Машет рукой и пританцовывает."""
    lt = t - B[4]
    return dict(x=575, armL=72 + 20 * math.sin(lt * 11), armR=25 + 5 * math.sin(lt * 5.5),
                y=-abs(math.sin(lt * 5.5)) * 32, head=6 * math.sin(lt * 5.5), body=3 * math.sin(lt * 5.5),
                squash=0.03 * math.cos(lt * 11))


SEGS = (seg_intro, seg_panic, seg_reveal, seg_build, seg_cta)


def mascot_pose(t):
    i = scene_idx(t)
    pose = SEGS[i](t)
    if i > 0:
        k = smooth((t - B[i]) / 0.35)
        prev = SEGS[i - 1](t)
        pose = {key: lerp(prev.get(key, 0.0), pose.get(key, 0.0), k) for key in set(prev) | set(pose)}
    e = voice_env(t)
    pose["head"] = pose.get("head", 0.0) + 3.5 * e * math.sin(t * 15)  # кивает в такт речи
    pose["squash"] = pose.get("squash", 0.0) + 0.012 * math.sin(t * 3)  # дыхание
    pose["y"] = pose.get("y", 0.0) - 5 * e
    return pose


def blink(t):
    for tb in BLINKS:
        if tb <= t < tb + 0.16:
            return math.sin(math.pi * (t - tb) / 0.16)
    return 0.0


def draw_mascot(img, t):
    pose = mascot_pose(t)
    x, y = pose.get("x", 430), pose.get("y", 0.0)
    # тень на «полу»: меньше и прозрачнее, когда маскот в воздухе
    h = min(1, -y / 300)
    sh = Image.new("RGBA", (W // 4, H // 4), (0, 0, 0, 0))
    sd = ImageDraw.Draw(sh)
    rw, rh = (340 * (1 - 0.5 * h)) / 4, 34 / 4
    sd.ellipse((x / 4 - rw / 2, GROUND / 4 - rh, x / 4 + rw / 2, GROUND / 4 + rh), fill=(0, 0, 0, int(150 * (1 - 0.6 * h))))
    img.alpha_composite(sh.filter(ImageFilter.GaussianBlur(4)).resize((W, H), Image.BILINEAR))
    # свечение за спиной
    e = voice_env(t)
    glow = Image.new("RGBA", (W // 4, H // 4), (0, 0, 0, 0))
    gd = ImageDraw.Draw(glow)
    gx, gy, r = x / 4, (GROUND + y - 520) / 4, 100 + 18 * e
    gd.ellipse((gx - r, gy - r, gx + r, gy + r), fill=rgba(ACCENT, 0.3 + 0.2 * e))
    img.alpha_composite(glow.filter(ImageFilter.GaussianBlur(30)).resize((W, H), Image.BILINEAR))
    m = PUPPET.render(pose, blink(t))
    fx, fy = PUPPET.feet
    img.alpha_composite(m, (int(x - fx), int(GROUND + y - fy)))
# ---------------- кадр целиком

def frame(t):
    img = background(t).convert("RGBA")
    i = scene_idx(t)
    lt = t - B[i]
    T = 0.3  # длительность перехода
    cur = scene_layer(i, t)
    if i > 0 and lt < T:
        k = ease(lt / T)
        prev = scene_layer(i - 1, B[i] - 0.001)
        img.alpha_composite(transform(prev, 1 + 0.15 * k, 1 - k))
        cur = transform(cur, 0.85 + 0.15 * k, k)
    img.alpha_composite(cur)
    draw_mascot(img, t)
    # белая вспышка на дропе
    if B[2] <= t < B[2] + 0.2:
        f = 1 - (t - B[2]) / 0.2
        img.alpha_composite(Image.new("RGBA", (W, H), rgba(WHITE, 0.55 * f)))
    # затемнение в самом конце
    if t > TOTAL - 0.3:
        img.alpha_composite(Image.new("RGBA", (W, H), rgba(BG, (t - TOTAL + 0.3) / 0.3)))
    return img.convert("RGB")


def render_frame(i):
    return frame(i / FPS).tobytes()


def main():
    if "--stills" in sys.argv:
        for k, ln in enumerate(LINES):
            frame(ln["end"] - 0.1).save(HERE / "build" / f"still_{k}.png")
        if "--only-stills" in sys.argv:
            return
    out = HERE / "deckcard_promo_tiktok.mp4"
    n = int(TOTAL * FPS)
    audio = ("[1:a]aresample=44100,asplit=2[v1][v2];"
             "[2:a]aresample=44100,volume=0.5[m];"
             "[m][v1]sidechaincompress=threshold=0.03:ratio=8:attack=20:release=300[duck];"
             "[duck][v2]amix=inputs=2:normalize=0,loudnorm=I=-14:TP=-1.5[a]")
    cmd = ["ffmpeg", "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24",
           "-s", f"{W}x{H}", "-r", str(FPS), "-i", "-",
           "-i", str(HERE / "voice.wav"), "-i", str(HERE / "music.wav"),
           "-filter_complex", audio, "-map", "0:v", "-map", "[a]",
           "-c:v", "libx264", "-preset", "slow", "-crf", "17", "-profile:v", "high",
           "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k", "-ar", "44100",
           "-shortest", "-movflags", "+faststart", str(out)]
    p = subprocess.Popen(cmd, stdin=subprocess.PIPE)
    with mp.get_context("fork").Pool(mp.cpu_count()) as pool:
        for i, fr in enumerate(pool.imap(render_frame, range(n), chunksize=4)):
            p.stdin.write(fr)
            if i % 120 == 0:
                print(f"{i}/{n}", file=sys.stderr)
    p.stdin.close()
    p.wait()
    print(out)


if __name__ == "__main__":
    main()
