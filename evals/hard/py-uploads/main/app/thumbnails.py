from io import BytesIO

from PIL import Image

# Design files are huge; Pillow's decompression-bomb guard rejects legitimate artboards.
Image.MAX_IMAGE_PIXELS = None


def thumbnail(path, size=(256, 256)) -> bytes:
    with Image.open(path) as im:
        im.thumbnail(size)
        buf = BytesIO()
        im.convert("RGB").save(buf, "JPEG", quality=80)
        return buf.getvalue()
