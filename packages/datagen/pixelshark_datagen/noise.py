"""Photometric noise. It does not move pixels, so bounding boxes still line up."""

from __future__ import annotations

import random
from typing import Any

from PIL import Image, ImageEnhance


def apply_noise(image: Image.Image, rng: random.Random) -> tuple[Image.Image, dict[str, float]]:
    """Return a slightly noisy RGB image and the parameters that produced it."""

    sigma = rng.uniform(10.0, 28.0)
    alpha = rng.uniform(0.035, 0.08)
    brightness = rng.uniform(0.92, 1.08)
    color = rng.uniform(0.88, 1.12)
    saved = random.getstate()
    random.seed(rng.randrange(1 << 30))
    try:
        grain = Image.effect_noise(image.size, sigma).convert("RGB")
    finally:
        random.setstate(saved)
    mixed = Image.blend(image.convert("RGB"), grain, alpha)
    mixed = ImageEnhance.Brightness(mixed).enhance(brightness)
    mixed = ImageEnhance.Color(mixed).enhance(color)
    params: dict[str, Any] = {
        "sigma": round(sigma, 3),
        "alpha": round(alpha, 3),
        "brightness": round(brightness, 3),
        "color": round(color, 3),
    }
    return mixed, params
