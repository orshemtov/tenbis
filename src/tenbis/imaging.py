"""Barcode image composition."""

from io import BytesIO

from PIL import Image


def create_voucher_image(barcode_bytes: bytes, barcode_number: str) -> bytes:
    """Compose a clean white PNG: barcode image centred with padding.

    The source barcode from 10bis already includes the number below the bars,
    so we only add padding — no duplicate text.
    """
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

    # Scale up to at least 1200px wide so WhatsApp renders it as a full-size photo
    MIN_WIDTH = 1200
    if barcode_img.width < MIN_WIDTH:
        scale = MIN_WIDTH / barcode_img.width
        new_size = (int(barcode_img.width * scale), int(barcode_img.height * scale))
        barcode_img = barcode_img.resize(new_size, Image.LANCZOS)

    padding = 80
    canvas = Image.new(
        "RGB",
        (barcode_img.width + padding * 2, barcode_img.height + padding * 2),
        color="white",
    )
    canvas.paste(barcode_img, (padding, padding))

    output = BytesIO()
    canvas.save(output, format="PNG")
    return output.getvalue()
