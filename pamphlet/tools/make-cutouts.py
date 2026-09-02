"""Chroma-key a flat studio background out of a generated image.

Only background-coloured pixels that are connected to the image border are
removed, so same-coloured pixels inside the subject (e.g. golden vada on a
mustard backdrop) are preserved.
"""
import sys

import numpy as np
from PIL import Image, ImageFilter
from scipy import ndimage


def cutout(src, dst, key_rgb, tol=42, erode=1, feather=1.1):
    img = Image.open(src).convert("RGBA")
    arr = np.asarray(img).astype(np.int32)
    rgb = arr[:, :, :3]

    dist = np.sqrt(((rgb - np.array(key_rgb, dtype=np.int32)) ** 2).sum(axis=2))
    is_key = dist < tol

    labels, n = ndimage.label(is_key)
    border = set(labels[0, :]) | set(labels[-1, :]) | set(labels[:, 0]) | set(labels[:, -1])
    border.discard(0)
    background = np.isin(labels, list(border))

    subject = ~background
    if erode:
        # Pull the matte in slightly to shave off the coloured fringe.
        subject = ndimage.binary_erosion(subject, iterations=erode)
    subject = ndimage.binary_fill_holes(subject)

    alpha = Image.fromarray((subject * 255).astype(np.uint8), "L")
    if feather:
        alpha = alpha.filter(ImageFilter.GaussianBlur(feather))

    out = img.copy()
    out.putalpha(alpha)
    out = out.crop(out.getbbox())
    out.save(dst)
    print(f"{dst}: {out.size[0]}x{out.size[1]}, "
          f"{100 * subject.mean():.1f}% subject, {n} keyed regions")


if __name__ == "__main__":
    cutout("/opt/cursor/artifacts/assets/hero-platter.png",
           "/workspace/pamphlet/assets/platter.png", (245, 184, 32), tol=58)
    cutout("/opt/cursor/artifacts/assets/velan-logo.png",
           "/workspace/pamphlet/assets/logo.png", (12, 59, 44), tol=40, erode=1)
