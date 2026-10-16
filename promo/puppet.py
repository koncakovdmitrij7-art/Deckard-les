"""Перекладная (cut-out) анимация маскота из одной картинки.

Картинка режется на слои с мягкими краями: ноги, тело, голова, рука с
ладонью, предплечье с кольцевой лампой. Каждый слой поворачивается вокруг
своего сустава; места на теле, которые закрывали руки и голова,
дорисованы инпейнтингом, поэтому при движении нет дыр.
"""
import math

import cv2
import numpy as np
from PIL import Image

# Разметка в координатах assets/mascot.png (1749x1758)
NECK = (850, 470)
SHOULDER_L = (480, 760)
ELBOW_R = (1530, 820)
HIP_L = (650, 1250)
HIP_R = (1070, 1250)
FEET = (850, 1740)
EYES = ((795, 259), (1005, 262))
EYE_SIZE = (96, 50)

ARM_L_POLY = [(0, 560), (300, 540), (470, 560), (540, 700), (520, 900), (470, 1010), (300, 1020), (0, 1030)]
ARM_L_FILL = [(525, 540), (478, 630), (448, 750), (432, 880), (428, 1000), (440, 1060), (650, 1060), (650, 540)]
ARM_R_POLY = [(1420, 0), (1749, 0), (1749, 900), (1640, 900), (1600, 860), (1450, 820), (1430, 700), (1330, 480), (1330, 0)]


def rot(pivot, deg):
    """Поворот против часовой (визуально, ось y вниз) вокруг pivot, 3x3."""
    a = math.radians(deg)
    c, s = math.cos(a), math.sin(a)
    px, py = pivot
    return np.array([[c, s, px - c * px - s * py],
                     [-s, c, py + s * px - c * py],
                     [0, 0, 1.0]])


def move(dx, dy):
    return np.array([[1, 0, dx], [0, 1, dy], [0, 0, 1.0]])


def scale_at(pivot, sx, sy):
    px, py = pivot
    return np.array([[sx, 0, px - sx * px], [0, sy, py - sy * py], [0, 0, 1.0]])


class Puppet:
    def __init__(self, path, height, pad=(330, 380, 280, 40)):
        src = Image.open(path).convert("RGBA")
        self.k = height / src.height
        w = int(src.width * self.k)
        img = np.array(src.resize((w, height), Image.LANCZOS)).astype(np.float32)
        l, t, r, b = pad
        self.pad = (l, t)
        self.H, self.W = height + t + b, w + l + r
        canvas = np.zeros((self.H, self.W, 4), np.float32)
        canvas[t:t + height, l:l + w] = img
        self.base = canvas  # straight alpha
        self.feet = self.p(FEET)
        self._eye_colors()
        self._build_layers()

    def p(self, pt):
        return (pt[0] * self.k + self.pad[0], pt[1] * self.k + self.pad[1])

    def poly_mask(self, poly, blur=2.5):
        m = np.zeros((self.H, self.W), np.float32)
        cv2.fillPoly(m, [np.array([self.p(q) for q in poly], np.int32)], 1)
        return cv2.GaussianBlur(m, (0, 0), blur) if blur else m

    def ellipse_mask(self, c, r, blur=2.5):
        m = np.zeros((self.H, self.W), np.float32)
        cx, cy = self.p(c)
        cv2.ellipse(m, (int(cx), int(cy)), (int(r[0] * self.k), int(r[1] * self.k)), 0, 0, 360, 1, -1)
        return cv2.GaussianBlur(m, (0, 0), blur) if blur else m

    def _build_layers(self):
        H, W, k = self.H, self.W, self.k
        yy, xx = np.mgrid[0:H, 0:W].astype(np.float32)
        sy = (yy - self.pad[1]) / k
        sx = (xx - self.pad[0]) / k

        def soft(cond, blur=2.5):
            return cv2.GaussianBlur(cond.astype(np.float32), (0, 0), blur)

        head = self.ellipse_mask((840, 240), (420, 300)) * soft(sy < 470)
        head = np.maximum(head, soft((sy < 470) & (sx < 640) & (sx > 380)) * soft(sy < 470))  # наушник/дым
        arm_l = self.poly_mask(ARM_L_POLY)
        arm_r = self.poly_mask(ARM_R_POLY) * (1 - head)
        leg_l = soft((sy > 1180) & (sx < 870))
        leg_r = soft((sy > 1180) & (sx >= 870))
        legs_cut = soft(sy > 1330, 4)

        # тело: всё, кроме конечностей; под руками/головой — дорисовка
        rgb = self.base[..., :3].astype(np.uint8)
        alpha = self.base[..., 3]
        shape = np.maximum(self.poly_mask(ARM_L_FILL, 0), self.ellipse_mask((850, 470), (300, 90), 0))
        fill = (shape > 0).astype(np.uint8)
        # инпейнт только из ткани тела: всё, что не тело, сначала красим в цвет ткани
        cx, cy = self.p((700, 1150))
        fabric = rgb[int(cy) - 15:int(cy) + 15, int(cx) - 15:int(cx) + 15].reshape(-1, 3).mean(0)
        hole = ((fill > 0) | (arm_l > 0.01) | (head > 0.01) | (alpha < 200)).astype(np.uint8)
        pre = np.where(hole[..., None] > 0, fabric, rgb).astype(np.uint8)
        fill_rgb = cv2.inpaint(pre, (((fill > 0) | (arm_l > 0.01) | (head > 0.01)) & (alpha >= 0)).astype(np.uint8) * 255,
                               15, cv2.INPAINT_TELEA)
        body_rgb = np.where(fill[..., None] > 0, fill_rgb, rgb).astype(np.float32)
        body_alpha = np.maximum(alpha * (1 - arm_l) * (1 - head) * (1 - arm_r),
                                cv2.GaussianBlur(fill.astype(np.float32), (0, 0), 3) * 255)
        body_alpha *= 1 - legs_cut
        body = np.dstack([body_rgb, body_alpha])

        def layer(mask, src=None):
            src = self.base if src is None else src
            out = src.copy()
            out[..., 3] = src[..., 3] * mask
            return out

        self.layers = {
            "legL": layer(leg_l), "legR": layer(leg_r), "body": body,
            "head": layer(head), "armR": layer(arm_r), "armL": layer(arm_l),
        }
        for key, im in self.layers.items():  # premultiply
            im[..., :3] *= im[..., 3:4] / 255.0

    def _eye_colors(self):
        self.lids = []
        for ex, ey in EYES:
            cx, cy = self.p((ex, ey - 45))
            patch = self.base[int(cy) - 6:int(cy) + 6, int(cx) - 20:int(cx) + 20, :3]
            self.lids.append(patch.reshape(-1, 3).mean(0))

    def _blink(self, head, closure):
        if closure <= 0.01:
            return head
        img = head.copy()
        for (ex, ey), col in zip(EYES, self.lids):
            cx, cy = self.p((ex, ey))
            rw, rh = EYE_SIZE[0] * self.k / 2, EYE_SIZE[1] * self.k / 2
            y0, y1 = int(cy - rh - 6), int(cy + rh + 6)
            x0, x1 = int(cx - rw - 6), int(cx + rw + 6)
            m = np.zeros((y1 - y0, x1 - x0), np.float32)
            cv2.ellipse(m, (int(cx) - x0, int(cy) - y0), (int(rw + 2), int(rh + 2)), 0, 0, 360, 1, -1)
            bottom = int((rh * 2 + 8) * closure)
            m[bottom:] = 0
            m = cv2.GaussianBlur(m, (0, 0), 1.2)[..., None]
            region = img[y0:y1, x0:x1]
            lid = np.concatenate([np.broadcast_to(col, m.shape[:2] + (3,)), np.full(m.shape, 255.0)], -1)
            region[:] = region * (1 - m) + lid * m
            if closure > 0.3:
                cv2.ellipse(region, (int(cx) - x0, bottom - 2), (int(rw * 0.85), 3), 0, 0, 180,
                            (45, 28, 32, 255), 2)
        return img

    def render(self, pose, blink=0.0):
        """Возвращает PIL RGBA; точка между ступнями = self.feet (в покое)."""
        P, k = self.p, self.k
        sq = pose.get("squash", 0.0)
        root = rot(self.feet, pose.get("body", 0.0)) @ scale_at(self.feet, 1 + sq * 0.6, 1 - sq)
        T = {
            "legL": root @ move(0, -pose.get("liftL", 0.0) * k) @ rot(P(HIP_L), pose.get("legL", 0.0)),
            "legR": root @ move(0, -pose.get("liftR", 0.0) * k) @ rot(P(HIP_R), pose.get("legR", 0.0)),
            "body": root,
            "head": root @ rot(P(NECK), pose.get("head", 0.0)),
            "armR": root @ rot(P(ELBOW_R), pose.get("armR", 0.0)),
            "armL": root @ rot(P(SHOULDER_L), -pose.get("armL", 0.0)),
        }
        out = np.zeros((self.H, self.W, 4), np.float32)
        for name in ("legL", "legR", "body", "head", "armR", "armL"):
            src = self.layers[name]
            if name == "head":
                src = self._blink(src, blink)
            warped = cv2.warpAffine(src, T[name][:2], (self.W, self.H), flags=cv2.INTER_LINEAR,
                                    borderMode=cv2.BORDER_CONSTANT, borderValue=0)
            a = warped[..., 3:4] / 255.0
            out = warped + out * (1 - a)
        a = out[..., 3:4]
        rgb = np.where(a > 0, out[..., :3] * 255 / np.maximum(a, 1e-3), 0)
        res = np.concatenate([np.clip(rgb, 0, 255), np.clip(a, 0, 255)], -1).astype(np.uint8)
        return Image.fromarray(res, "RGBA")
