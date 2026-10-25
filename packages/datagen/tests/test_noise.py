import random
from io import BytesIO

from PIL import Image

from pixelshark_datagen.noise import apply_noise


def test_noise_keeps_the_image_size():
    image = Image.new("RGB", (40, 24), (10, 80, 40))
    noisy, params = apply_noise(image, random.Random(1))
    assert noisy.size == (40, 24)
    assert noisy.mode == "RGB"
    assert 0 < params["alpha"] < 0.2
    assert set(params) == {"sigma", "alpha", "brightness", "color"}
    # Grain changes pixels. Pillow's effect_noise is not bit-stable across calls,
    # so this check only requires that the frame is no longer a flat color.
    assert list(noisy.get_flattened_data()) != list(image.get_flattened_data())
    buffer = BytesIO()
    noisy.save(buffer, format="PNG")
    assert buffer.getvalue().startswith(b"\x89PNG")
