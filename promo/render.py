"""Рендер 15-секундного промо-ролика Deckard (1080x1920, 30 fps).

Кадры рисуются Pillow и передаются в ffmpeg через pipe, затем
накладывается озвучка (voice.wav) и вшиваются субтитры.
Тайминги сцен берутся из timings.json (их пишет tts.py).
"""
import json
import math
import subprocess
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

HERE = Path(__file__).parent
W, H, FPS = 1080, 1920, 30
FONT_DIR = "/usr/share/fonts/opentype/inter/"


def font(weight, size):
    return ImageFont.truetype(f"{FONT_DIR}Inter-{weight}.otf", size)


F_HUGE = font("Black", 230)
F_BIG = font("ExtraBold", 120)
F_MID = font("Bold", 72)
F_SUB = font("Bold", 58)
F_SMALL = font("Medium", 44)

BG = (11, 13, 24)
ACCENT = (108, 92, 255)
ACCENT2 = (0, 214, 180)
RED = (255, 72, 88)
WHITE = (245, 246, 255)
MUTED = (140, 146, 180)

timings = json.loads((HERE / "timings.json").read_text())
LINES = timings["lines"]  # [{text, start, end}]
TOTAL = timings["total"]


def ease(t):
    t = max(0.0, min(1.0, t))
    return 1 - (1 - t) ** 3


def lerp(a, b, t):
    return a + (b - a) * t


def mix(c1, c2, t):
    return tuple(int(lerp(a, b, t)) for a, b in zip(c1, c2))


def center_text(d, y, text, f, fill, anchor="mm"):
    d.text((W // 2, y), text, font=f, fill=fill, anchor=anchor)


def background(t, tint):
    img = Image.new("RGB", (W, H), BG)
    glow = Image.new("RGB", (W, H), BG)
    g = ImageDraw.Draw(glow)
    cx = W / 2 + math.sin(t * 0.9) * 180
    cy = H * 0.42 + math.cos(t * 0.7) * 160
    for r, a in ((700, 0.18), (480, 0.28), (300, 0.38)):
        g.ellipse((cx - r, cy - r, cx + r, cy + r), fill=mix(BG, tint, a))
    glow = glow.filter(ImageFilter.GaussianBlur(160))
    return Image.blend(img, glow, 1.0)


def scene_bounds():
    # Сцены привязаны к репликам озвучки.
    s = [ln["start"] for ln in LINES]
    return s + [TOTAL]


B = scene_bounds()


def scene_clock(d, t, lt):
    """Сцена 1: до курсовой 5 часов — тикающий таймер."""
    remaining = 5 * 3600 - int(lt * 1400)
    hh, mm, ss = remaining // 3600, remaining % 3600 // 60, remaining % 60
    pulse = 0.5 + 0.5 * math.sin(t * 9)
    a = ease(lt / 0.4)
    center_text(d, 560, "ДО СДАЧИ КУРСОВОЙ", F_SMALL, mix(BG, MUTED, a))
    center_text(d, 800, f"{hh:02d}:{mm:02d}:{ss:02d}", F_BIG.font_variant(size=190),
                mix(WHITE, RED, pulse * a))
    # полоска оставшегося времени
    x0, x1, y = 160, W - 160, 990
    d.rounded_rectangle((x0, y, x1, y + 22), 11, fill=(36, 38, 58))
    d.rounded_rectangle((x0, y, x0 + (x1 - x0) * (remaining / 18000), y + 22), 11, fill=RED)


def scene_empty(d, t, lt):
    """Сцена 2: пустой слайд, мигающий курсор, паника."""
    shake = math.sin(t * 60) * 6 * ease(lt / 0.3)
    x0, y0 = 120 + shake, 470
    x1, y1 = W - 120 + shake, 470 + 500
    d.rounded_rectangle((x0, y0, x1, y1), 28, fill=(24, 27, 44), outline=(52, 56, 84), width=4)
    d.text((x0 + 60, y0 + 70), "Слайд 1", font=F_SMALL, fill=MUTED)
    if int(t * 2.5) % 2 == 0:
        d.rectangle((x0 + 60, y0 + 170, x0 + 68, y0 + 260), fill=WHITE)
    for i, q in enumerate(("Что писать?", "Какой дизайн?", "Не успеваю!")):
        appear = ease((lt - 0.25 - i * 0.35) / 0.3)
        if appear <= 0:
            continue
        yy = 1100 + i * 110
        col = RED if i == 2 else WHITE
        center_text(d, yy + (1 - appear) * 40, q, F_MID, mix(BG, col, appear))


def logo(d, cx, cy, s, a):
    """Знак Deckard: стопка из трёх карточек-слайдов."""
    for i, c in enumerate((ACCENT2, ACCENT, WHITE)):
        off = (2 - i) * 26 * s
        w, h = 170 * s, 120 * s
        d.rounded_rectangle((cx - w / 2 + off, cy - h / 2 - off, cx + w / 2 + off, cy + h / 2 - off),
                            int(18 * s), fill=mix(BG, c, a))
    d.rounded_rectangle((cx - 50 * s, cy - 18 * s, cx + 50 * s, cy - 6 * s), 4, fill=mix(BG, ACCENT, a))
    d.rounded_rectangle((cx - 50 * s, cy + 8 * s, cx + 20 * s, cy + 18 * s), 4, fill=mix(BG, MUTED, a))


def scene_reveal(d, t, lt):
    """Сцена 3: «Решение есть — Deckard!»"""
    a = ease(lt / 0.35)
    s = lerp(0.6, 1.25, ease(lt / 0.5))
    logo(d, W // 2, 700, s * 1.6, a)
    center_text(d, 1030, "DECKARD", F_HUGE.font_variant(size=int(180 * lerp(0.85, 1, a))), mix(BG, WHITE, a))
    center_text(d, 1160, "решение есть", F_SMALL, mix(BG, ACCENT2, ease((lt - 0.2) / 0.4)))


def scene_build(d, t, lt, dur):
    """Сцена 4: слайды собираются сами, прогресс-бар."""
    p = ease(lt / (dur * 0.85))
    titles = ("Введение", "Цели и задачи", "Методология", "Результаты", "Выводы")
    for i, title in enumerate(titles):
        ap = ease((lt - i * 0.28) / 0.35)
        if ap <= 0:
            continue
        col, row = i % 2, i // 2
        w, h = 400, 240
        x = 120 + col * 440 + (1 - ap) * 200
        y = 380 + row * 290
        if i == 4:
            x = (W - w) / 2 + (1 - ap) * 200
        c = (ACCENT, ACCENT2, (255, 170, 60), (255, 92, 160), ACCENT)[i]
        d.rounded_rectangle((x, y, x + w, y + h), 22, fill=mix(BG, (30, 34, 56), ap))
        d.rounded_rectangle((x, y, x + w, y + 54), 22, fill=mix(BG, c, ap))
        d.rectangle((x, y + 30, x + w, y + 54), fill=mix(BG, c, ap))
        d.text((x + 28, y + 80), title, font=font("Bold", 40), fill=mix(BG, WHITE, ap))
        for k in range(3):
            d.rounded_rectangle((x + 28, y + 145 + k * 28, x + 28 + (300 - k * 70), y + 157 + k * 28),
                                6, fill=mix(BG, MUTED, ap * 0.6))
    x0, x1, y = 160, W - 160, 1290
    d.rounded_rectangle((x0, y, x1, y + 22), 11, fill=(36, 38, 58))
    d.rounded_rectangle((x0, y, x0 + (x1 - x0) * p, y + 22), 11, fill=ACCENT2)
    center_text(d, y + 80, f"{int(p * 100)}%  ·  {lt:0.1f} c", F_SMALL, WHITE)


def scene_cta(d, t, lt):
    """Сцена 5: финальный слоган."""
    a = ease(lt / 0.4)
    logo(d, W // 2, 560, 1.3, a)
    center_text(d, 830, "DECKARD", F_HUGE.font_variant(size=170), mix(BG, WHITE, a))
    center_text(d, 980, "Презентации", F_MID, mix(BG, WHITE, ease((lt - 0.2) / 0.4)))
    center_text(d, 1070, "за минуты", F_MID, mix(BG, ACCENT2, ease((lt - 0.35) / 0.4)))
    b = ease((lt - 0.6) / 0.4)
    if b > 0:
        bw, bh = 560, 120
        d.rounded_rectangle(((W - bw) / 2, 1200, (W + bw) / 2, 1200 + bh), 60, fill=mix(BG, ACCENT, b))
        center_text(d, 1260, "Попробуй сейчас", font("Bold", 50), mix(BG, WHITE, b))


TINTS = (RED, (120, 40, 60), ACCENT, ACCENT2, ACCENT)


def wrap(text, f, maxw, d):
    words, lines, cur = text.split(), [], ""
    for w in words:
        test = (cur + " " + w).strip()
        if d.textlength(test, font=f) <= maxw:
            cur = test
        else:
            lines.append(cur)
            cur = w
    lines.append(cur)
    return lines


def subtitle(d, t):
    for ln in LINES:
        if ln["start"] <= t < ln["end"] + 0.15:
            lines = wrap(ln["text"], F_SUB, W - 180, d)
            y = 1640 - (len(lines) - 1) * 40
            for i, s in enumerate(lines):
                yy = y + i * 80
                tw = d.textlength(s, font=F_SUB)
                d.rounded_rectangle(((W - tw) / 2 - 26, yy - 44, (W + tw) / 2 + 26, yy + 40), 16,
                                    fill=(0, 0, 0))
                center_text(d, yy, s, F_SUB, WHITE)
            return


def frame(t):
    idx = max(i for i in range(len(B) - 1) if B[i] <= t or i == 0)
    lt = t - B[idx]
    dur = B[idx + 1] - B[idx]
    img = background(t, TINTS[idx])
    d = ImageDraw.Draw(img)
    (scene_clock, scene_empty, scene_reveal,
     lambda d_, t_, lt_: scene_build(d_, t_, lt_, dur), scene_cta)[idx](d, t, lt)
    # вспышка на смене сцен
    if 0 < lt < 0.12 and idx > 0:
        img = Image.blend(img, Image.new("RGB", (W, H), WHITE), 0.35 * (1 - lt / 0.12))
        d = ImageDraw.Draw(img)
    subtitle(d, t)
    return img


def srt_time(s):
    ms = int(round(s * 1000))
    return f"{ms // 3600000:02d}:{ms // 60000 % 60:02d}:{ms // 1000 % 60:02d},{ms % 1000:03d}"


def main():
    out = HERE / "deckard_promo.mp4"
    with open(HERE / "deckard_promo.srt", "w", encoding="utf-8") as f:
        for i, ln in enumerate(LINES, 1):
            f.write(f"{i}\n{srt_time(ln['start'])} --> {srt_time(ln['end'])}\n{ln['text']}\n\n")
    n = int(TOTAL * FPS)
    cmd = ["ffmpeg", "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24",
           "-s", f"{W}x{H}", "-r", str(FPS), "-i", "-", "-i", str(HERE / "voice.wav"),
           "-c:v", "libx264", "-preset", "medium", "-crf", "20", "-pix_fmt", "yuv420p",
           "-c:a", "aac", "-b:a", "160k", "-shortest", "-movflags", "+faststart", str(out)]
    p = subprocess.Popen(cmd, stdin=subprocess.PIPE)
    for i in range(n):
        p.stdin.write(frame(i / FPS).tobytes())
        if i % 60 == 0:
            print(f"{i}/{n}", file=sys.stderr)
    p.stdin.close()
    p.wait()
    if "--stills" in sys.argv:
        for k, ln in enumerate(LINES):
            frame((ln["start"] + ln["end"]) / 2).save(HERE / f"still_{k}.png")
    print(out)


if __name__ == "__main__":
    main()
