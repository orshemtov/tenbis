"""Barcode image composition — ported from auto10bis/functions/voucher/tenbis/client.py."""

from io import BytesIO

from PIL import Image, ImageDraw, ImageFont

# Font search order: Linux paths first, macOS fallbacks
_FONT_PATHS = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
    "/usr/share/fonts/TTF/DejaVuSansMono.ttf",
    "/usr/share/fonts/dejavu/DejaVuSansMono.ttf",
    "/System/Library/Fonts/Menlo.ttc",
    "/System/Library/Fonts/Monaco.ttf",
]


def _load_font(size: int = 24) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    for path in _FONT_PATHS:
        try:
            return ImageFont.truetype(path, size)
        except OSError:
            continue
    return ImageFont.load_default()


def create_voucher_image(barcode_bytes: bytes, barcode_number: str) -> bytes:
    """Compose a clean white PNG: barcode image centred with the number printed below."""
    barcode_img = Image.open(BytesIO(barcode_bytes))

    # Normalise to RGB with a white background
    if barcode_img.mode in ("RGBA", "LA") or (
        barcode_img.mode == "P" and "transparency" in barcode_img.info
    ):
        white_bg = Image.new("RGB", barcode_img.size, color="white")
        if barcode_img.mode != "RGBA":
            barcode_img = barcode_img.convert("RGBA")
        white_bg.paste(barcode_img, mask=barcode_img.split()[3])
        barcode_img = white_bg
    elif barcode_img.mode != "RGB":
        barcode_img = barcode_img.convert("RGB")

    padding = 40
    text_height = 50
    width = barcode_img.width + padding * 2
    height = barcode_img.height + padding * 2 + text_height

    canvas = Image.new("RGB", (width, height), color="white")
    canvas.paste(barcode_img, (padding, padding))

    draw = ImageDraw.Draw(canvas)
    font = _load_font(24)

    bbox = draw.textbbox((0, 0), barcode_number, font=font)
    text_width = bbox[2] - bbox[0]
    draw.text(
        ((width - text_width) // 2, padding + barcode_img.height + 15),
        barcode_number,
        fill="black",
        font=font,
    )

    output = BytesIO()
    canvas.save(output, format="PNG")
    return output.getvalue()
