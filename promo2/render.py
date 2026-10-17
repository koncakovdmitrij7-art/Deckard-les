"""Рендер ролика «Как я защитил курсовую» про Deckcard (1080x1920, 30 fps, ~66 c).

Стилистика как у референса: пастельные градиенты, пиксельные персонажи с подписями-«таблетками»,
карточки интерфейса, стикеры, LED-заголовки, пословные субтитры с оранжевой плашкой на ключевых
словах, тонкая полоса прогресса сверху. Сцены — по репликам из timings.json (tts.py).
"""
import json
import math
import multiprocessing as mp
import random
import subprocess
import sys
from functools import lru_cache
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

HERE = Path(__file__).parent
W, H, FPS = 1080, 1920, 30
INTER = "/usr/share/fonts/opentype/inter/Inter-{}.otf"
MONO = "/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf"

ORANGE = (240, 108, 78)
ORANGE_D = (205, 82, 56)
INK = (28, 28, 40)
GREY = (160, 163, 182)
WHITE = (255, 255, 255)
VIOLET = (124, 92, 255)
GREEN = (52, 180, 110)
YELLOW = (251, 227, 142)
LAV = (201, 194, 245)

TM = json.loads((HERE / "timings.json").read_text())
LINES = TM["lines"]
TOTAL = TM["total"]


@lru_cache(None)
def font(weight, size):
    return ImageFont.truetype(INTER.format(weight), size)


def ease(t):
    t = max(0.0, min(1.0, t))
    return 1 - (1 - t) ** 3


def ease_io(t):
    t = max(0.0, min(1.0, t))
    return t * t * (3 - 2 * t)


def ease_back(t):
    t = max(0.0, min(1.0, t))
    c = 1.7
    return 1 + (c + 1) * (t - 1) ** 3 + c * (t - 1) ** 2


def pop(lt, delay=0.0, dur=0.35):
    """(масштаб, прозрачность) для появления «с пружинкой»."""
    u = (lt - delay) / dur
    return max(0.0, ease_back(u)), min(1.0, max(0.0, u * 2.5))


def lerp(a, b, k):
    return a + (b - a) * k


def mix(c1, c2, k):
    return tuple(int(lerp(a, b, k)) for a, b in zip(c1, c2))


# ---------------------------------------------------------------- компоновка слоёв

def comp(img, layer, cx, cy, s=1.0, a=1.0, rot=0.0):
    """Кладёт RGBA-слой центром в (cx, cy) с масштабом, прозрачностью и поворотом."""
    if layer is None or s <= 0.02 or a <= 0.01:
        return
    if abs(s - 1) > 0.01:
        layer = layer.resize((max(1, int(layer.width * s)), max(1, int(layer.height * s))), Image.BILINEAR)
    if abs(rot) > 0.1:
        layer = layer.rotate(rot, resample=Image.BICUBIC, expand=True)
    if a < 0.999:
        layer = layer.copy()
        layer.putalpha(layer.getchannel("A").point(lambda v: int(v * a)))
    x, y = int(cx - layer.width / 2), int(cy - layer.height / 2)
    sx, sy = max(0, -x), max(0, -y)
    ex, ey = min(layer.width, W - x), min(layer.height, H - y)
    if ex <= sx or ey <= sy:
        return
    img.alpha_composite(layer.crop((sx, sy, ex, ey)), (x + sx, y + sy))


def shadowed(w, h, r, fill, pad=40, shadow=40):
    """Слой: скруглённый прямоугольник с мягкой тенью. Возвращает (layer, ox, oy) — смещение рамки."""
    L = Image.new("RGBA", (w + 2 * pad, h + 2 * pad), (0, 0, 0, 0))
    sh = Image.new("RGBA", L.size, (0, 0, 0, 0))
    ImageDraw.Draw(sh).rounded_rectangle((pad, pad + 14, pad + w, pad + h + 14), r, fill=(40, 30, 60, shadow))
    L.alpha_composite(sh.filter(ImageFilter.GaussianBlur(18)))
    ImageDraw.Draw(L).rounded_rectangle((pad, pad, pad + w, pad + h), r, fill=fill)
    return L, pad, pad


@lru_cache(None)
def L_pill(text, size=34, bg=WHITE, fg=INK, weight="SemiBold", padx=None, pady=None, shadow=True):
    f = font(weight, size)
    tw = int(ImageDraw.Draw(Image.new("L", (1, 1))).textlength(text, font=f))
    padx = padx if padx is not None else int(size * 0.7)
    pady = pady if pady is not None else int(size * 0.42)
    w, h = tw + 2 * padx, size + 2 * pady
    if shadow:
        L, ox, oy = shadowed(w, h, h // 2, bg, pad=30, shadow=34)
    else:
        L = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        ox = oy = 0
        ImageDraw.Draw(L).rounded_rectangle((0, 0, w, h), h // 2, fill=bg)
    ImageDraw.Draw(L).text((ox + w / 2, oy + h / 2 + 1), text, font=f, fill=fg, anchor="mm")
    return L


@lru_cache(None)
def L_sticker(text, bg, fg=INK, size=46):
    f = font("Bold", size)
    tw = int(ImageDraw.Draw(Image.new("L", (1, 1))).textlength(text, font=f))
    w, h = tw + 64, size + 44
    L, ox, oy = shadowed(w, h, 18, bg, pad=30, shadow=40)
    ImageDraw.Draw(L).text((ox + w / 2, oy + h / 2), text, font=f, fill=fg, anchor="mm")
    return L


@lru_cache(None)
def L_stamp(text, color=(225, 45, 55), size=96):
    f = font("Black", size)
    tw = int(ImageDraw.Draw(Image.new("L", (1, 1))).textlength(text, font=f))
    w, h = tw + 80, size + 60
    L = Image.new("RGBA", (w + 20, h + 20), (0, 0, 0, 0))
    d = ImageDraw.Draw(L)
    d.rounded_rectangle((10, 10, 10 + w, 10 + h), 22, fill=(255, 255, 255, 235), outline=color, width=9)
    d.rounded_rectangle((26, 26, w - 6, h - 6), 14, outline=color, width=3)
    d.text((10 + w / 2, 10 + h / 2), text, font=f, fill=color, anchor="mm")
    return L


@lru_cache(None)
def L_led(text, cell=22, color=ORANGE, size=20):
    """Пиксельный LED-заголовок, как «CLAUDE CODE» в референсе."""
    f = ImageFont.truetype(MONO, size)
    tw = int(ImageDraw.Draw(Image.new("L", (1, 1))).textlength(text, font=f)) + 2
    small = Image.new("L", (tw, size + 4), 0)
    ImageDraw.Draw(small).text((1, 0), text, font=f, fill=255)
    bbox = small.getbbox()
    small = small.crop(bbox)
    gw, gh = small.size
    cell = min(cell, int(880 / gw))  # влезает по ширине кадра
    pad = cell * 2
    L = Image.new("RGBA", (gw * cell + 2 * pad, gh * cell + 2 * pad), (0, 0, 0, 0))
    d = ImageDraw.Draw(L)
    px = small.load()
    for y in range(gh):
        for x in range(gw):
            on = px[x, y] > 110
            x0, y0 = pad + x * cell, pad + y * cell
            c = (*color, 255) if on else (*color, 22)
            d.rounded_rectangle((x0 + 2, y0 + 2, x0 + cell - 3, y0 + cell - 3), cell // 4, fill=c)
    glow = L.filter(ImageFilter.GaussianBlur(cell * 0.9))
    out = Image.new("RGBA", L.size, (0, 0, 0, 0))
    out.alpha_composite(glow)
    out.alpha_composite(glow)
    out.alpha_composite(L)
    return out


# ---------------------------------------------------------------- пиксельный персонаж

SPRITE = [
    "....OOOOOOOO....",
    "...OOOOOOOOOO...",
    "..OOOOOOOOOOOO..",
    "..OOOEOOOOEOOO..",
    "..OOOEOOOOEOOO..",
    "OOOOOOOOOOOOOOOO",
    "OOOOOOOOOOOOOOOO",
    "..OOWWWWWWWWOO..",
    "..OOWAAAAAWWOO..",
    "..OOWWWWWWWWOO..",
    "..DDDDDDDDDDDD..",
]
LEGS = ["...D.D....D.D...", "..D.D......D.D.."]
PAL = {"O": ORANGE, "D": ORANGE_D, "E": (40, 30, 42), "W": (255, 250, 246), "A": VIOLET}


@lru_cache(None)
def L_sprite(px=10, legs=0, blink=False, happy=False):
    rows = SPRITE + [LEGS[legs], LEGS[legs]]
    w, h = len(rows[0]) * px, len(rows) * px
    L = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(L)
    for y, row in enumerate(rows):
        for x, ch in enumerate(row):
            if ch == ".":
                continue
            if ch == "E" and (blink or (happy and y == 4)):
                ch = "O"
            d.rectangle((x * px, y * px, x * px + px - 1, y * px + px - 1), fill=(*PAL[ch], 255))
    if happy:  # глаза-дуги
        for ex in (5, 10):
            d.rectangle((ex * px - px // 2, 3 * px, ex * px + px + px // 2 - 1, 3 * px + px // 2), fill=(40, 30, 42, 255))
    return L


def sprite(img, cx, bottom, px=10, t=0.0, walk=False, hop=0.0, rot=0.0, happy=False, a=1.0, s=1.0, seed=0):
    blink = ((t + seed * 0.7) % 3.1) < 0.12
    legs = int(t * 8) % 2 if walk else 0
    L = L_sprite(px, legs, blink, happy)
    comp(img, L, cx, bottom - L.height * s / 2 - hop, s=s, a=a, rot=rot)
    return bottom - L.height * s - hop  # верх головы


# ---------------------------------------------------------------- иконки (над персонажами)

@lru_cache(None)
def L_icon(name, size=90):
    L = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(L)
    s = size
    k = (40, 30, 42, 255)
    if name == "mail":
        d.rounded_rectangle((s * .1, s * .25, s * .9, s * .78), 6, fill=WHITE, outline=k, width=4)
        d.line((s * .12, s * .28, s * .5, s * .55, s * .88, s * .28), fill=k, width=4)
    elif name == "cap":
        d.polygon([(s * .5, s * .2), (s * .95, s * .4), (s * .5, s * .6), (s * .05, s * .4)], fill=k)
        d.rectangle((s * .28, s * .45, s * .72, s * .7), fill=k)
        d.line((s * .85, s * .42, s * .85, s * .72), fill=(250, 200, 60, 255), width=4)
    elif name == "rocket":
        d.ellipse((s * .35, s * .08, s * .65, s * .78), fill=(235, 238, 248, 255), outline=k, width=4)
        d.ellipse((s * .43, s * .28, s * .57, s * .42), fill=(110, 170, 255, 255))
        d.polygon([(s * .35, s * .55), (s * .2, s * .8), (s * .38, s * .72)], fill=ORANGE)
        d.polygon([(s * .65, s * .55), (s * .8, s * .8), (s * .62, s * .72)], fill=ORANGE)
        d.polygon([(s * .42, s * .78), (s * .5, s * .97), (s * .58, s * .78)], fill=(255, 190, 60, 255))
    elif name == "clip":
        d.rounded_rectangle((s * .2, s * .12, s * .8, s * .92), 8, fill=WHITE, outline=k, width=4)
        d.rectangle((s * .38, s * .06, s * .62, s * .2), fill=k)
        d.line((s * .32, s * .55, s * .45, s * .68, s * .7, s * .4), fill=GREEN, width=7)
    elif name == "book":
        d.polygon([(s * .5, s * .3), (s * .08, s * .2), (s * .08, s * .8), (s * .5, s * .9)], fill=WHITE, outline=k)
        d.polygon([(s * .5, s * .3), (s * .92, s * .2), (s * .92, s * .8), (s * .5, s * .9)], fill=(245, 240, 255, 255), outline=k)
        d.line((s * .5, s * .3, s * .5, s * .9), fill=k, width=4)
    elif name == "brain":
        for cx, cy, r in ((.35, .4, .22), (.62, .38, .24), (.42, .62, .22), (.66, .6, .2)):
            d.ellipse((s * (cx - r), s * (cy - r), s * (cx + r), s * (cy + r)), fill=(255, 150, 185, 255))
        d.arc((s * .25, s * .3, s * .55, s * .6), 200, 340, fill=(200, 70, 120, 255), width=4)
        d.arc((s * .48, s * .4, s * .8, s * .75), 180, 330, fill=(200, 70, 120, 255), width=4)
    elif name == "mag":
        d.ellipse((s * .1, s * .1, s * .62, s * .62), outline=k, width=8)
        d.line((s * .55, s * .55, s * .88, s * .88), fill=k, width=12)
    elif name == "doc":
        d.rounded_rectangle((s * .18, s * .08, s * .82, s * .92), 8, fill=WHITE, outline=k, width=4)
        d.text((s * .5, s * .32), "##", font=font("Black", int(s * .26)), fill=VIOLET, anchor="mm")
        for i in range(3):
            d.line((s * .3, s * (.55 + i * .12), s * .7, s * (.55 + i * .12)), fill=(170, 170, 190, 255), width=4)
    elif name == "list":
        d.rounded_rectangle((s * .18, s * .08, s * .82, s * .92), 8, fill=WHITE, outline=k, width=4)
        for i in range(4):
            y = s * (.25 + i * .17)
            d.ellipse((s * .28, y - 5, s * .28 + 10, y + 5), fill=ORANGE)
            d.line((s * .4, y, s * .72, y), fill=(150, 150, 175, 255), width=5)
    elif name == "table":
        d.rounded_rectangle((s * .08, s * .18, s * .92, s * .82), 6, fill=WHITE, outline=k, width=4)
        d.rectangle((s * .08 + 2, s * .18 + 2, s * .92 - 2, s * .34), fill=(255, 215, 200, 255))
        for i in (1, 2):
            d.line((s * (.08 + .28 * i), s * .18, s * (.08 + .28 * i), s * .82), fill=k, width=3)
        for j in (.34, .5, .66):
            d.line((s * .08, s * j, s * .92, s * j), fill=k, width=3)
    elif name == "photo":
        d.rounded_rectangle((s * .08, s * .18, s * .92, s * .82), 8, fill=(205, 230, 250, 255), outline=k, width=4)
        d.polygon([(s * .12, s * .78), (s * .4, s * .45), (s * .6, s * .65), (s * .72, s * .55), (s * .88, s * .78)],
                  fill=(90, 175, 120, 255))
        d.ellipse((s * .66, s * .26, s * .8, s * .4), fill=(255, 200, 60, 255))
    elif name == "laptop":
        d.rounded_rectangle((s * .18, s * .2, s * .82, s * .65), 6, fill=(60, 64, 90, 255))
        d.rectangle((s * .24, s * .26, s * .76, s * .59), fill=(150, 140, 255, 255))
        d.polygon([(s * .08, s * .7), (s * .92, s * .7), (s * .86, s * .78), (s * .14, s * .78)], fill=k)
    elif name == "wrench":
        d.line((s * .25, s * .78, s * .65, s * .38), fill=k, width=14)
        d.ellipse((s * .52, s * .12, s * .88, s * .48), outline=k, width=12)
    return L


# ---------------------------------------------------------------- фоны

THEMES = {
    "peach": ((250, 244, 240), [((255, 205, 185), .25, .35, 520), ((222, 214, 252), .75, .7, 600), ((252, 236, 205), .8, .2, 420)], False),
    "blue": ((236, 242, 250), [((200, 222, 248), .3, .3, 560), ((230, 214, 246), .7, .72, 600), ((255, 222, 205), .15, .8, 380)], False),
    "lav": ((243, 240, 250), [((220, 212, 252), .7, .3, 560), ((255, 218, 204), .2, .25, 460), ((206, 228, 250), .4, .8, 560)], False),
    "yellow": ((252, 244, 218), [((255, 224, 160), .3, .3, 560), ((255, 206, 186), .75, .75, 520), ((250, 240, 200), .8, .2, 400)], False),
    "dark": ((20, 20, 30), [((70, 40, 40), .5, .3, 520), ((40, 40, 80), .4, .8, 560)], True),
    "navy": ((34, 56, 168), [((70, 110, 230), .5, .4, 700), ((30, 40, 140), .2, .9, 500)], True),
}


@lru_cache(None)
def theme_bg(name):
    base, blobs, grid = THEMES[name]
    m = 160
    sw, sh = (W + 2 * m) // 4, (H + 2 * m) // 4
    small = Image.new("RGB", (sw, sh), base)
    d = ImageDraw.Draw(small)
    for c, x, y, r in blobs:
        r /= 4
        d.ellipse((x * sw - r, y * sh - r, x * sw + r, y * sh + r), fill=c)
    img = small.filter(ImageFilter.GaussianBlur(70)).resize((W + 2 * m, H + 2 * m), Image.BICUBIC)
    if grid:
        d = ImageDraw.Draw(img)
        gc = mix(base, WHITE, 0.07)
        for x in range(0, W + 2 * m, 72):
            d.line((x, 0, x, H + 2 * m), fill=gc)
        for y in range(0, H + 2 * m, 72):
            d.line((0, y, W + 2 * m, y), fill=gc)
    return img.convert("RGBA")


def background(name, t):
    m = 160
    ox = m + math.sin(t * 0.35) * 60
    oy = m + math.cos(t * 0.27) * 80
    return theme_bg(name).crop((int(ox), int(oy), int(ox) + W, int(oy) + H))


DARK_THEMES = {"dark", "navy"}


# ---------------------------------------------------------------- окна интерфейса

@lru_cache(None)
def L_window(w, h, title=""):
    L, ox, oy = shadowed(w, h, 30, WHITE, pad=40, shadow=46)
    d = ImageDraw.Draw(L)
    for i, c in enumerate(((255, 95, 87), (254, 188, 46), (40, 200, 64))):
        d.ellipse((ox + 28 + i * 30, oy + 26, ox + 46 + i * 30, oy + 44), fill=c)
    if title:
        d.text((ox + w / 2, oy + 35), title, font=font("SemiBold", 26), fill=(150, 152, 170), anchor="mm")
    return L


def window(img, cx, cy, w, h, title, s=1.0, a=1.0, rot=0.0):
    comp(img, L_window(w, h, title), cx, cy, s, a, rot)


def label(img, cx, cy, text, s=1.0, a=1.0, size=30, dark=False):
    comp(img, L_pill(text, size, (36, 36, 50) if dark else WHITE, WHITE if dark else INK), cx, cy, s, a)


def caps(img, cx, cy, text, color=(150, 152, 170), a=1.0):
    L = Image.new("RGBA", (900, 60), (0, 0, 0, 0))
    ImageDraw.Draw(L).text((450, 30), text, font=font("SemiBold", 28), fill=color, anchor="mm")
    comp(img, L, cx, cy, 1, a)


# ---------------------------------------------------------------- сцены

class Ctx:
    def __init__(self, img, t, lt, dur, lines):
        self.img, self.t, self.lt, self.dur, self.lines = img, t, lt, dur, lines
        self.d = ImageDraw.Draw(img)

    def word_t(self, li, wi):
        """Время слова wi реплики li (относительно начала сцены)."""
        ln = self.lines[min(li, len(self.lines) - 1)]
        return ln["words"][min(wi, len(ln["words"]) - 1)]["start"] - self.lines[0]["start"]


def sc_night(c):
    lt, img = c.lt, c.img
    s, a = pop(lt, 0.0, 0.45)
    colon = ":" if int(c.t * 2) % 2 == 0 else " "
    comp(img, L_led(f"01{colon}00", cell=30), W / 2, 470, s, a)
    awake = lt > c.word_t(0, 4)
    hop = max(0, math.sin((lt - c.word_t(0, 4)) * 9)) * 40 if awake and lt < c.word_t(0, 4) + 0.7 else 0
    top = sprite(img, W / 2, 960, 12, c.t, hop=hop, happy=False)
    if not awake:
        for i in range(3):
            ph = (lt * 0.8 + i * 0.33) % 1
            L = Image.new("RGBA", (60, 60), (0, 0, 0, 0))
            ImageDraw.Draw(L).text((30, 30), "z", font=font("Bold", 30 + i * 6), fill=(200, 200, 230), anchor="mm")
            comp(img, L, W / 2 + 90 + ph * 50, top - 10 - ph * 120, 1, 1 - ph)
    else:
        sp, ap = pop(lt, c.word_t(0, 4))
        comp(img, L_pill("!", 54, ORANGE, WHITE, "Black"), W / 2 + 120, top - 40, sp, ap)
    sp, ap = pop(lt, c.word_t(0, 5))
    comp(img, L_pill("завтра защита", 40, ORANGE, WHITE, "Bold"), W / 2, 680, sp, ap)


def sc_docs(c):
    lt, img = c.lt, c.img
    s, a = pop(lt, 0.0)
    window(img, 330, 560, 440, 420, "курсовая.docx", s, a, rot=-3)
    if a > 0.5:
        L = Image.new("RGBA", (380, 300), (0, 0, 0, 0))
        d = ImageDraw.Draw(L)
        for i in range(8):
            d.rounded_rectangle((10, 20 + i * 34, 10 + (340 if i % 3 else 220), 34 + i * 34), 6, fill=(200, 202, 218, 255))
        comp(img, L, 330, 600, s, a, rot=-3)
        comp(img, L_pill("✓ 40 страниц", 30, (226, 246, 234), GREEN, "Bold"), 330, 830, s, a)
    s2, a2 = pop(lt, 0.5)
    window(img, 760, 640, 420, 340, "презентация.pptx", s2, a2, rot=3)
    if a2 > 0.5:
        L = Image.new("RGBA", (330, 190), (0, 0, 0, 0))
        ImageDraw.Draw(L).rounded_rectangle((4, 4, 326, 186), 12, outline=(205, 205, 222, 255), width=4)
        comp(img, L, 760, 670, s2, a2, rot=3)
    s3, a3 = pop(lt, c.word_t(0, 5))
    comp(img, L_pill("0 слайдов", 38, (225, 50, 60), WHITE, "Bold"), 770, 860, s3, a3, rot=3)
    sprite(img, 250, 960, 8, c.t, hop=abs(math.sin(c.t * 3)) * 6)


def sc_ppt(c):
    lt, img = c.lt, c.img
    s, a = pop(lt, 0.0)
    window(img, W / 2, 600, 900, 600, "PowerPoint", s, a)
    if a > 0.6:
        L = Image.new("RGBA", (800, 450), (0, 0, 0, 0))
        d = ImageDraw.Draw(L)
        d.rounded_rectangle((0, 0, 799, 449), 10, fill=(247, 247, 252, 255), outline=(225, 225, 236, 255), width=3)
        jit = math.sin(lt * 7) * 70 + math.sin(lt * 17) * 18
        jy = math.sin(lt * 5.3) * 14
        bx = 400 + jit
        d.rounded_rectangle((bx - 230, 120 + jy, bx + 230, 200 + jy), 6, outline=ORANGE, width=4)
        d.text((bx, 160 + jy), "Заголовок", font=font("Bold", 44), fill=INK, anchor="mm")
        for i in range(3):
            d.rounded_rectangle((90, 260 + i * 46, 560 - i * 80, 278 + i * 46), 6, fill=(205, 207, 222, 255))
        comp(img, L, W / 2, 630, s, a)
    mins = int(min(40, lt / max(0.1, c.word_t(0, 3) + 0.6) * 40))
    sp, ap = pop(lt, 0.3)
    comp(img, L_pill(f"⏱ 00:{mins:02d}:00", 38, ORANGE, WHITE, "Bold"), W / 2, 230, sp, ap)
    sprite(img, 860, 1000, 9, c.t, walk=True, hop=abs(math.sin(c.t * 8)) * 8)


def sc_prompt(c):
    lt, img = c.lt, c.img
    caps(img, W / 2, 220, "НЕЙРОСЕТЬ", a=pop(lt, 0)[1])
    stickers = [("Сделай красиво.", WHITE, INK, -4), ("Добавь стиль.", YELLOW, INK, 3),
                ("Нет, не так.", ORANGE, WHITE, -2), ("Ещё раз.", LAV, INK, 4), ("Ну пожалуйста...", WHITE, INK, -3)]
    times = [c.word_t(1, 0), c.word_t(1, 2), c.word_t(1, 4), c.word_t(1, 6), c.word_t(1, 6) + 0.25]
    for i, ((txt, bg, fg, r), tt) in enumerate(zip(stickers, times)):
        s, a = pop(lt, tt)
        comp(img, L_sticker(txt, bg, fg), W / 2 + (i % 2 * 2 - 1) * 40, 380 + i * 105, s, a, rot=r)
    sprite(img, W / 2, 1010, 9, c.t, hop=abs(math.sin(c.t * 5)) * 6)
    comp(img, L_icon("laptop", 110), W / 2 + 120, 960)
    sp, ap = pop(lt, c.word_t(0, 5), 0.3)
    fade = 1 - ease((lt - c.word_t(1, 0)) / 0.3)
    comp(img, L_pill("промпт-ад", 40, (225, 45, 55), WHITE, "Bold"), W / 2, 300, sp, ap * fade)
    s2, a2 = pop(lt, min(c.word_t(1, 6) + 0.45, c.dur - 0.5), 0.25)
    comp(img, L_stamp("ПРОМПТ-АД"), W / 2, 640, s2, a2, rot=-8)


def sc_link(c):
    lt, img = c.lt, c.img
    u = ease(lt / 0.5)
    L, ox, oy = shadowed(820, 150, 34, WHITE, pad=30, shadow=40)
    d = ImageDraw.Draw(L)
    d.rounded_rectangle((ox + 26, oy + 30, ox + 116, oy + 120), 22, fill=ORANGE)
    d.text((ox + 71, oy + 75), "dc", font=font("Black", 44), fill=WHITE, anchor="mm")
    d.text((ox + 140, oy + 50), "Друг · сейчас", font=font("SemiBold", 28), fill=(140, 142, 160), anchor="lm")
    d.text((ox + 140, oy + 98), "смотри, это спасёт → deckcard", font=font("Bold", 36), fill=INK, anchor="lm")
    comp(img, L, W / 2, lerp(-150, 300, u), 1, min(1, lt * 3))
    s, a = pop(lt, c.word_t(0, 4), 0.5)
    glow = Image.new("RGBA", (700, 700), (0, 0, 0, 0))
    ImageDraw.Draw(glow).ellipse((150, 150, 550, 550), fill=(255, 255, 255, 120))
    comp(img, glow.filter(ImageFilter.GaussianBlur(60)), W / 2, 680, s, a)
    comp(img, L_led("DECKCARD", cell=22), W / 2, 680, s, a)
    sprite(img, W / 2, 1000, 9, c.t, hop=max(0, math.sin((lt - c.word_t(0, 4)) * 8)) * 50 if a > 0 else 0, happy=a > 0)


def sc_input(c):
    lt, img = c.lt, c.img
    s, a = pop(lt, 0)
    window(img, W / 2, 600, 900, 640, "Новая презентация", s, a)
    if a < 0.6:
        return
    L = Image.new("RGBA", (820, 560), (0, 0, 0, 0))
    d = ImageDraw.Draw(L)
    d.text((10, 30), "Тема или текст", font=font("SemiBold", 28), fill=(150, 152, 170), anchor="lm")
    d.rounded_rectangle((0, 60, 819, 400), 22, fill=(246, 245, 251, 255), outline=(225, 224, 238, 255), width=2)
    text = ("Курсовая: влияние соцсетей на подростков. Введение, цели, методология, "
            "результаты опроса 120 школьников, выводы и рекомендации…")
    n = int(len(text) * min(1, lt / (c.dur * 0.75)))
    words, rows, cur = text[:n].split(" "), [], ""
    f = font("Medium", 34)
    for wd in words:
        if d.textlength(cur + " " + wd, font=f) > 760 and cur:
            rows.append(cur)
            cur = wd
        else:
            cur = (cur + " " + wd).strip()
    rows.append(cur)
    for i, r in enumerate(rows[:6]):
        d.text((28, 100 + i * 48), r, font=f, fill=INK, anchor="lm")
    if int(c.t * 3) % 2 == 0:
        x = 28 + d.textlength(rows[min(len(rows), 6) - 1], font=f) + 4
        d.rectangle((x, 100 + (min(len(rows), 6) - 1) * 48 - 20, x + 4, 100 + (min(len(rows), 6) - 1) * 48 + 20), fill=ORANGE)
    cnt = int(48213 * ease(lt / (c.dur * 0.8)))
    d.text((810, 430), f"{cnt:,}".replace(",", " ") + " / 50 000", font=font("SemiBold", 28), fill=(150, 152, 170), anchor="rm")
    d.rounded_rectangle((0, 470, 819, 550), 26, fill=ORANGE)
    d.text((410, 510), "Создать презентацию", font=font("Bold", 36), fill=WHITE, anchor="mm")
    comp(img, L, W / 2, 640, s, a)


def sc_formats(c):
    lt, img = c.lt, c.img
    items = [("doc", "план по слайдам", 0), ("list", "списки", 3), ("table", "таблицы", 6)]
    for i, (ic, lab, wi) in enumerate(items):
        tt = c.word_t(0, wi)
        s, a = pop(lt, tt)
        x = 220 + i * 320
        hop = max(0, math.sin((lt - tt) * 7)) * 40 if 0 < lt - tt < 0.45 else 0
        top = sprite(img, x, 820, 10, c.t + i, hop=hop, s=s, a=a, seed=i)
        comp(img, L_icon(ic, 120), x, top - 75, s, a)
        label(img, x, 870, lab, s, a)


def sc_count(c):
    lt, img = c.lt, c.img
    s, a = pop(lt, 0)
    manual = lt > c.word_t(0, 6)
    L = Image.new("RGBA", (640, 100), (0, 0, 0, 0))
    d = ImageDraw.Draw(L)
    d.rounded_rectangle((0, 0, 639, 99), 50, fill=(226, 226, 238, 255))
    kx = 320 if manual else 0
    d.rounded_rectangle((kx + 8, 8, kx + 312, 91), 44, fill=WHITE)
    d.text((160, 50), "Авто", font=font("Bold", 38), fill=INK if not manual else (130, 132, 150), anchor="mm")
    d.text((480, 50), "Вручную", font=font("Bold", 38), fill=INK if manual else (130, 132, 150), anchor="mm")
    comp(img, L, W / 2, 330, s, a)
    k = ease_io((lt - c.word_t(0, 7)) / max(0.3, c.dur - c.word_t(0, 7) - 0.3))
    val = 1 + round(15 * k)
    x0, x1, y = 170, 910, 560
    c.d.rounded_rectangle((x0, y - 8, x1, y + 8), 8, fill=(220, 220, 234))
    kx = lerp(x0, x1, (val - 1) / 15)
    c.d.rounded_rectangle((x0, y - 8, kx, y + 8), 8, fill=ORANGE)
    c.d.ellipse((kx - 26, y - 26, kx + 26, y + 26), fill=WHITE, outline=ORANGE, width=6)
    comp(img, L_pill(str(val), 48, INK, WHITE, "Black"), kx, y - 90, a=a)
    for i in range(val):
        col, row = i % 8, i // 8
        sx, sa = pop(lt, c.word_t(0, 7) + (i / 15) * 1.0, 0.25)
        cx, cy = 210 + col * 94, 720 + row * 80
        L2 = Image.new("RGBA", (84, 54), (0, 0, 0, 0))
        ImageDraw.Draw(L2).rounded_rectangle((0, 0, 83, 53), 8, fill=WHITE, outline=(215, 215, 230), width=2)
        ImageDraw.Draw(L2).rectangle((10, 12, 50, 18), fill=ORANGE)
        comp(img, L2, cx, cy, max(sx, 1 if lt > c.word_t(0, 7) + 1.2 else sx), max(sa, 1 if lt > c.word_t(0, 7) + 1.2 else sa))


def sc_photos(c):
    lt, img = c.lt, c.img
    slots = [(780, 320, "слайд 2"), (780, 560, "слайд 5"), (780, 800, "слайд 7")]
    for i, (x, y, lab) in enumerate(slots):
        s, a = pop(lt, 0.1 * i)
        L = Image.new("RGBA", (330, 186), (0, 0, 0, 0))
        ImageDraw.Draw(L).rounded_rectangle((2, 2, 327, 183), 14, fill=(255, 255, 255, 200), outline=(200, 200, 220, 255), width=4)
        comp(img, L, x, y, s, a)
        label(img, x, y + 125, lab, s, a, size=26)
    for i, (x, y, _) in enumerate(slots):
        t0 = 0.4 + i * 0.55
        u = ease_io((lt - t0) / 0.6)
        px = lerp(250, x, u)
        py = lerp(y + 40, y, u) - math.sin(u * math.pi) * 80
        sz = lerp(1.0, 1.75, u)
        s, a = pop(lt, 0.15 * i)
        comp(img, L_icon("photo", 170), px, py, s * sz, a, rot=lerp(-8, 0, u))
    sprite(img, 230, 1010, 9, c.t, walk=True)


def sc_brain(c):
    lt, img = c.lt, c.img
    s, a = pop(lt, 0)
    top = sprite(img, W / 2, 900, 16, c.t, s=s, a=a, hop=abs(math.sin(c.t * 3)) * 10)
    pulse = 1 + 0.06 * math.sin(c.t * 6)
    sb, ab = pop(lt, c.word_t(0, 5))
    comp(img, L_icon("brain", 220), W / 2, top - 110, sb * pulse, ab)
    for i, (lab, x, y) in enumerate((("смысл", 230, 380), ("структура", 540, 250), ("дизайн", 850, 380))):
        sp, ap = pop(lt, c.word_t(0, 6 + i))
        comp(img, L_pill(lab, 40, ORANGE if i == 1 else WHITE, WHITE if i == 1 else INK, "Bold"), x, y, sp, ap)


def sc_grid(c):
    lt, img = c.lt, c.img
    s, a = pop(lt, 0)
    window(img, W / 2, 560, 900, 600, "слайд 4", s, a)
    snap = ease_io((lt - c.word_t(0, 5)) / 0.7)
    gl = min(1, max(0, (lt - c.word_t(0, 5) + 0.3) / 0.3)) * (1 - ease((lt - c.word_t(0, 9)) / 0.6))
    L = Image.new("RGBA", (820, 480), (0, 0, 0, 0))
    d = ImageDraw.Draw(L)
    if gl > 0:
        for x in range(40, 820, 120):
            for y in range(0, 480, 24):
                d.line((x, y, x, y + 12), fill=(*ORANGE, int(160 * gl)), width=2)
    messy = [(70, 60, -6, 30), (300, 100, 5, -20), (560, 40, -3, 40)]
    for i, (mx, my, mr, mdy) in enumerate(messy):
        tx = 40 + i * 260
        x = lerp(mx, tx, snap)
        y = lerp(my + 80, 120, snap)
        card = Image.new("RGBA", (220, 280), (0, 0, 0, 0))
        cd = ImageDraw.Draw(card)
        cd.rounded_rectangle((0, 0, 219, 279), 18, fill=(247, 246, 252, 255), outline=(222, 222, 236, 255), width=3)
        cd.rectangle((24, 30, 120, 44), fill=(ORANGE, VIOLET, GREEN)[i])
        for j in range(4):
            cd.rounded_rectangle((24, 80 + j * 40, 190 - j * 25, 94 + j * 40), 6, fill=(205, 207, 222, 255))
        card = card.rotate(lerp(mr, 0, snap), resample=Image.BICUBIC, expand=True)
        L.alpha_composite(card, (int(x), int(y)))
    comp(img, L, W / 2, 600, s, a)
    sp, ap = pop(lt, c.word_t(0, 9))
    comp(img, L_pill("✓ ровно", 40, (226, 246, 234), GREEN, "Bold"), W / 2, 940, sp, ap)
    sw, aw = pop(lt, c.word_t(0, 3))
    top = sprite(img, 150, 1010, 8, c.t, s=sw, a=aw)
    comp(img, L_icon("wrench", 80), 150, top - 50, sw, aw)


LAYOUTS = ["Титул", "Сплит", "Пункты", "Тезис", "Команда", "2 колонки", "Галерея",
           "Призыв", "Карточки", "Выводы", "Процесс", "Метрики", "Важно"]


@lru_cache(None)
def L_tile(i):
    L = Image.new("RGBA", (200, 150), (0, 0, 0, 0))
    d = ImageDraw.Draw(L)
    d.rounded_rectangle((0, 0, 199, 112), 14, fill=WHITE, outline=(222, 222, 236), width=3)
    g = (205, 207, 222, 255)
    acc = (ORANGE, VIOLET, GREEN)[i % 3]
    v = i % 6
    if v == 0:
        d.rectangle((40, 40, 160, 54), fill=acc)
        d.rectangle((60, 66, 140, 74), fill=g)
    elif v == 1:
        d.rectangle((14, 14, 96, 98), fill=(205, 230, 250))
        for j in range(3):
            d.rectangle((108, 24 + j * 22, 184, 32 + j * 22), fill=g)
    elif v == 2:
        for j in range(4):
            d.ellipse((20, 22 + j * 20, 28, 30 + j * 20), fill=acc)
            d.rectangle((36, 23 + j * 20, 170 - j * 18, 29 + j * 20), fill=g)
    elif v == 3:
        for j in range(3):
            d.rounded_rectangle((14 + j * 60, 20, 66 + j * 60, 92), 8, fill=(246, 244, 252), outline=acc, width=2)
    elif v == 4:
        for j, hh in enumerate((40, 62, 30, 76)):
            d.rectangle((30 + j * 38, 96 - hh, 54 + j * 38, 96), fill=acc)
    else:
        for j in range(3):
            d.ellipse((22 + j * 58, 34, 58 + j * 58, 70), outline=acc, width=4)
            if j < 2:
                d.line((58 + j * 58, 52, 80 + j * 58, 52), fill=g, width=4)
    d.text((100, 134), LAYOUTS[i], font=font("SemiBold", 24), fill=(110, 112, 130), anchor="mm")
    return L


def sc_layouts(c):
    lt, img = c.lt, c.img
    s, a = pop(lt, 0)
    comp(img, L_pill("13 типов слайдов", 44, ORANGE, WHITE, "Bold"), W / 2, 230, s, a)
    for i in range(13):
        col, row = i % 4, i // 4
        x = 165 + col * 250 if row < 3 else W / 2
        y = 380 + row * 180
        sp, ap = pop(lt, 0.25 + i * 0.16)
        comp(img, L_tile(i), x, y, sp, ap)


def sc_genres(c):
    lt, img = c.lt, c.img
    items = [("cap", "учёба", 300, 470, 2), ("rocket", "питч", 780, 470, 3),
             ("clip", "аудит", 300, 860, 4), ("book", "история", 780, 860, 6)]
    for i, (ic, lab, x, y, wi) in enumerate(items):
        tt = c.word_t(0, wi) - 0.1
        s, a = pop(lt, tt)
        hop = abs(math.sin((c.t + i) * 4)) * 10
        top = sprite(img, x, y, 10, c.t + i, s=s, a=a, hop=hop, seed=i)
        comp(img, L_icon(ic, 110), x + (20 if ic == "cap" else 0), top - (20 if ic == "cap" else 70), s, a)
        label(img, x, y + 50, lab, s, a)


def sc_images(c):
    lt, img = c.lt, c.img
    x = lerp(160, 540, ease_io(lt / 1.5))
    top = sprite(img, x, 1000, 10, c.t, walk=lt < 1.5)
    comp(img, L_icon("mag", 110), x + 110, top + 30, 1, 1, rot=math.sin(c.t * 4) * 10)
    pics = [(260, 360, -5, "фотобанк"), (560, 300, 4, "фотобанк"), (840, 380, -3, "Википедия")]
    for i, (px, py, r, src) in enumerate(pics):
        s, a = pop(lt, c.word_t(0, 5) + i * 0.35)
        comp(img, L_icon("photo", 230), px, py, s, a, rot=r)
        label(img, px, py + 140, src, s, a, size=26)
    sp, ap = pop(lt, c.word_t(0, 8))
    comp(img, L_pill("✓ картинка найдена", 38, (226, 246, 234), GREEN, "Bold"), W / 2, 640, sp, ap)


def sc_export(c):
    lt, img = c.lt, c.img
    s, a = pop(lt, 0)
    L, ox, oy = shadowed(800, 450, 26, WHITE, pad=40, shadow=50)
    d = ImageDraw.Draw(L)
    d.rectangle((ox + 60, oy + 70, ox + 380, oy + 96), fill=ORANGE)
    for j in range(3):
        d.rounded_rectangle((ox + 60, oy + 150 + j * 50, ox + 400 - j * 60, oy + 170 + j * 50), 8, fill=(205, 207, 222))
    d.rounded_rectangle((ox + 470, oy + 70, ox + 740, oy + 380), 18, fill=(205, 230, 250))
    for j, hh in enumerate((90, 150, 120, 200)):
        d.rectangle((ox + 500 + j * 60, oy + 360 - hh, ox + 540 + j * 60, oy + 360), fill=(VIOLET, ORANGE)[j % 2])
    comp(img, L, W / 2, 480, s, a)
    comp(img, L_pill("16:9", 34, INK, WHITE, "Bold"), W / 2 + 330, 270, *pop(lt, c.word_t(0, 4)))
    prog = ease_io(lt / 1.6)
    fl = Image.new("RGBA", (700, 120), (0, 0, 0, 0))
    fd = ImageDraw.Draw(fl)
    fd.rounded_rectangle((0, 0, 699, 119), 30, fill=WHITE)
    fd.rounded_rectangle((20, 20, 100, 100), 18, fill=ORANGE)
    fd.text((60, 60), "P", font=font("Black", 48), fill=WHITE, anchor="mm")
    fd.text((125, 42), "kursovaya.pptx", font=font("Bold", 34), fill=INK, anchor="lm")
    fd.rounded_rectangle((125, 76, 640, 88), 6, fill=(230, 230, 240))
    fd.rounded_rectangle((125, 76, 125 + 515 * prog, 88), 6, fill=GREEN if prog >= 1 else ORANGE)
    if prog >= 1:
        fd.ellipse((630, 24, 680, 74), fill=GREEN)
        fd.line((642, 50, 652, 60, 670, 38), fill=WHITE, width=6)
    comp(img, fl, W / 2, 820, *pop(lt, 0.2))
    if len(c.lines) > 1:
        t2 = c.lines[1]["start"] - c.lines[0]["start"]
        u = ease_io((lt - t2) / 1.2)
        sprite(img, lerp(120, 980, u), 1010, 9, c.t, walk=0 < u < 1, hop=abs(math.sin(c.t * 9)) * 10 if 0 < u < 1 else 0)
        sp, ap = pop(lt, t2 + c.word_t(1, 4) - t2)
        comp(img, L_pill("на защиту →", 40, ORANGE, WHITE, "Bold"), W / 2, 950, sp, ap)
    else:
        sprite(img, 120, 1010, 9, c.t)


def sc_grade(c):
    lt, img = c.lt, c.img
    rnd = random.Random(5)
    for i in range(36):
        x = rnd.random() * W
        sp = rnd.uniform(200, 420)
        y = (rnd.random() * 400 - 300 + lt * sp) % 1100
        col = (ORANGE, VIOLET, GREEN, (255, 196, 60))[i % 4]
        c.d.rectangle((x, y, x + 16, y + 16), fill=col)
    hop = abs(math.sin(c.t * 5)) * 70
    top = sprite(img, W / 2, 960, 14, c.t, hop=hop, happy=True)
    comp(img, L_icon("cap", 150), W / 2 + 20, top - 10)
    s, a = pop(lt, c.word_t(0, 2), 0.3)
    comp(img, L_stamp("ЗАЩИЩЕНО", (40, 160, 90), 92), W / 2, 420, s, a, rot=-7)
    sp, ap = pop(lt, c.word_t(0, 4))
    comp(img, L_pill("выравнивал: 0 минут", 36, WHITE, INK, "Bold"), W / 2, 600, sp, ap)


def sc_outro(c):
    lt, img = c.lt, c.img
    s, a = pop(lt, 0, 0.5)
    glow = Image.new("RGBA", (800, 800), (0, 0, 0, 0))
    ImageDraw.Draw(glow).ellipse((200, 200, 600, 600), fill=(255, 140, 100, 70))
    comp(img, glow.filter(ImageFilter.GaussianBlur(80)), W / 2, 420, s, a)
    comp(img, L_led("DECKCARD", cell=22), W / 2, 400, s, a)
    for i, (txt, wi) in enumerate((("скажи тему обычным языком", 2), ("получи ровную презентацию", 6))):
        sp, ap = pop(lt, c.word_t(0, wi))
        comp(img, L_pill(txt, 40, (40, 40, 58), WHITE, "SemiBold", shadow=False), W / 2, 620 + i * 110, sp, ap)
    sp, ap = pop(lt, c.word_t(0, 10))
    comp(img, L_pill("без промпт-ада", 48, ORANGE, WHITE, "Bold"), W / 2, 870, sp, ap, rot=-3)
    sprite(img, 170, 1010, 8, c.t, hop=abs(math.sin(c.t * 4)) * 10)
    sprite(img, 910, 1010, 8, c.t + 1, hop=abs(math.sin(c.t * 4 + 1)) * 10, seed=2)


SWARM = [(random.Random(i).uniform(120, 960), random.Random(i + 50).uniform(330, 1000),
          random.Random(i + 99).uniform(0, 6.28), random.Random(i + 7).choice(["mail", "doc", "photo", "table", "cap", "rocket"]))
         for i in range(14)]


def sc_subscribe(c):
    lt, img = c.lt, c.img
    for i, (x, y, ph, ic) in enumerate(SWARM):
        s, a = pop(lt, i * 0.06)
        xx = x + math.sin(c.t * 0.9 + ph) * 60
        yy = y + math.cos(c.t * 1.1 + ph) * 40
        top = sprite(img, xx, yy, 5, c.t + i, walk=True, s=s, a=a, rot=math.sin(c.t * 2 + ph) * 12, seed=i)
        comp(img, L_icon(ic, 46), xx, top - 20, s, a)
    s, a = pop(lt, 0.4)
    comp(img, L_pill("✓ Вы подписаны", 44, GREEN, WHITE, "Bold"), W / 2, 520, s, a)
    sh, ah = pop(lt, 1.0)
    L = Image.new("RGBA", (130, 130), (0, 0, 0, 0))
    d = ImageDraw.Draw(L)
    d.ellipse((0, 0, 129, 129), fill=WHITE)
    d.ellipse((30, 38, 66, 74), fill=(235, 60, 80))
    d.ellipse((62, 38, 98, 74), fill=(235, 60, 80))
    d.polygon([(32, 62), (96, 62), (64, 100)], fill=(235, 60, 80))
    comp(img, L, W / 2, 680, sh * (1 + 0.08 * math.sin(c.t * 8)), ah)


SCENES = {
    "night": ("dark", sc_night), "docs": ("peach", sc_docs), "ppt": ("blue", sc_ppt),
    "prompt": ("lav", sc_prompt), "link": ("navy", sc_link), "input": ("peach", sc_input),
    "formats": ("blue", sc_formats), "count": ("lav", sc_count), "photos": ("yellow", sc_photos),
    "brain": ("lav", sc_brain), "grid": ("blue", sc_grid), "layouts": ("peach", sc_layouts),
    "genres": ("lav", sc_genres), "images": ("blue", sc_images), "export": ("peach", sc_export),
    "grade": ("yellow", sc_grade), "outro": ("dark", sc_outro), "subscribe": ("peach", sc_subscribe),
}

# группы реплик -> сцены
GROUPS = []
for i, ln in enumerate(LINES):
    if GROUPS and GROUPS[-1]["scene"] == ln["scene"]:
        GROUPS[-1]["lines"].append(ln)
    else:
        GROUPS.append({"scene": ln["scene"], "lines": [ln], "start": 0.0 if i == 0 else ln["start"] - 0.07})
for i, g in enumerate(GROUPS):
    g["end"] = GROUPS[i + 1]["start"] if i + 1 < len(GROUPS) else TOTAL


# ---------------------------------------------------------------- субтитры

SUB_F = font("ExtraBold", 54)
SUB_Y = 1190
SUB_MAXW = 860
SUB_LH = 74
HL_PAD = 10


@lru_cache(None)
def sub_layout(li):
    """Слова реплики -> страницы (по 2 строки) с позициями слов."""
    ln = LINES[li]
    dd = ImageDraw.Draw(Image.new("L", (1, 1)))
    sp = dd.textlength(" ", font=SUB_F)
    rows, cur, cw = [], [], 0
    for wi, w in enumerate(ln["words"]):
        ww = dd.textlength(w["text"], font=SUB_F) + (2 * HL_PAD if w["hl"] else 0)
        if cur and cw + sp + ww > SUB_MAXW:
            rows.append((cur, cw))
            cur, cw = [], 0
        cur.append((wi, ww))
        cw += (sp if len(cur) > 1 else 0) + ww
    rows.append((cur, cw))
    pages = [rows[i:i + 2] for i in range(0, len(rows), 2)]
    out = []
    for page in pages:
        items = []
        y0 = SUB_Y - (len(page) - 1) * SUB_LH / 2
        for r, (row, rw) in enumerate(page):
            x = W / 2 - rw / 2
            for wi, ww in row:
                items.append((wi, x, y0 + r * SUB_LH, ww))
                x += ww + sp
        out.append(items)
    return out


def subtitles(img, t, dark):
    li = None
    for i, ln in enumerate(LINES):
        if ln["start"] - 0.05 <= t:
            li = i
    if li is None:
        return
    ln = LINES[li]
    words = ln["words"]
    cur = max([i for i, w in enumerate(words) if w["start"] <= t] or [0])
    pages = sub_layout(li)
    page = next(p for p in pages if any(wi == cur for wi, *_ in p)) if any(
        any(wi == cur for wi, *_ in p) for p in pages) else pages[0]
    d = ImageDraw.Draw(img)
    for wi, x, y, ww in page:
        w = words[wi]
        said = w["start"] <= t
        tx = x + (HL_PAD if w["hl"] else 0)
        if said and w["hl"]:
            k = ease((t - w["start"]) / 0.12)
            d.rounded_rectangle((x, y - 38 - 2 * (1 - k), x + ww, y + 36 + 2 * (1 - k)), 12, fill=ORANGE)
            col = WHITE
        elif said:
            col = WHITE if dark else INK
        else:
            col = (255, 255, 255, 110) if dark else (*GREY, 255)
        d.text((tx, y), w["text"], font=SUB_F, fill=col, anchor="lm")


# ---------------------------------------------------------------- кадр

def frame(t):
    g = next(g for g in GROUPS if g["start"] <= t < g["end"]) if t < TOTAL else GROUPS[-1]
    theme, fn = SCENES[g["scene"]]
    img = background(theme, t)
    lt = t - g["start"]
    # «камера»: лёгкий наезд в течение сцены
    fn(Ctx(img, t, lt, g["end"] - g["start"], g["lines"]))
    subtitles(img, t, theme in DARK_THEMES)
    d = ImageDraw.Draw(img)
    d.rectangle((0, 0, W * min(1, t / TOTAL), 7), fill=ORANGE)  # полоса прогресса как в референсе
    if t > TOTAL - 0.4:
        img.alpha_composite(Image.new("RGBA", (W, H), (255, 255, 255, int(255 * (t - TOTAL + 0.4) / 0.4))))
    return img.convert("RGB")


def render_frame(i):
    return frame(i / FPS).tobytes()


def main():
    if "--stills" in sys.argv:
        out = HERE / "build"
        out.mkdir(exist_ok=True)
        for k, g in enumerate(GROUPS):
            tt = (g["start"] + g["end"]) / 2 + 0.6
            frame(min(tt, g["end"] - 0.05)).save(out / f"still_{k:02d}_{g['scene']}.png")
        return
    out = HERE / "deckcard_promo_story.mp4"
    n = int(TOTAL * FPS)
    audio = ("[1:a]aresample=48000,asplit=2[v1][v2];"
             "[2:a]aresample=48000,volume=0.35[m];"
             "[m][v1]sidechaincompress=threshold=0.03:ratio=6:attack=20:release=350[duck];"
             "[duck][v2]amix=inputs=2:normalize=0,loudnorm=I=-14:TP=-1.5[a]")
    cmd = ["ffmpeg", "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24",
           "-s", f"{W}x{H}", "-r", str(FPS), "-i", "-",
           "-i", str(HERE / "voice.wav"), "-i", str(HERE / "music.wav"),
           "-filter_complex", audio, "-map", "0:v", "-map", "[a]",
           "-c:v", "libx264", "-preset", "slow", "-crf", "18", "-pix_fmt", "yuv420p",
           "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-ac", "2",
           "-shortest", "-movflags", "+faststart", str(out)]
    p = subprocess.Popen(cmd, stdin=subprocess.PIPE)
    with mp.get_context("fork").Pool(mp.cpu_count()) as pool:
        for i, fr in enumerate(pool.imap(render_frame, range(n), chunksize=8)):
            p.stdin.write(fr)
            if i % 300 == 0:
                print(f"{i}/{n}", file=sys.stderr)
    p.stdin.close()
    p.wait()
    print(out)


if __name__ == "__main__":
    main()
