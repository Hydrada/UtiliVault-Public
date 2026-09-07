"""Create a website-safe copy of a generated two-page tie-card PDF."""

from __future__ import annotations

import argparse
from pathlib import Path

import fitz
from PIL import Image, ImageDraw, ImageFont


def _font(size: int, bold: bool = False) -> ImageFont.ImageFont:
    try:
        return ImageFont.truetype("arialbd.ttf" if bold else "arial.ttf", size)
    except OSError:
        return ImageFont.load_default()


def _box(image: Image.Image, fractions: tuple[float, float, float, float]) -> tuple[int, int, int, int]:
    width, height = image.size
    return (
        int(width * fractions[0]),
        int(height * fractions[1]),
        int(width * fractions[2]),
        int(height * fractions[3]),
    )


def _cover(draw: ImageDraw.ImageDraw, image: Image.Image, fractions, fill) -> None:
    draw.rectangle(_box(image, fractions), fill=fill)


def sanitize_pages(pdf_path: Path, address: str, registry: str) -> list[Image.Image]:
    document = fitz.open(pdf_path)
    pages = [
        Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
        for page in document
        for pix in [page.get_pixmap(matrix=fitz.Matrix(3, 3), alpha=False)]
    ]
    if len(pages) != 2:
        raise ValueError("Expected a two-page printable tie-card PDF")

    front, back = pages
    blue = "#00008B"
    front_fill = "#FFFF99"
    back_fill = "#FFFDE0"
    value_font = _font(max(20, front.width // 75))
    back_font = _font(max(18, back.width // 82), bold=True)

    front_draw = ImageDraw.Draw(front)
    _cover(front_draw, front, (0.024, 0.095, 0.495, 0.126), front_fill)
    _cover(front_draw, front, (0.505, 0.095, 0.825, 0.126), front_fill)
    front_draw.text((int(front.width * 0.027), int(front.height * 0.096)), address,
                    font=value_font, fill=blue)
    front_draw.text((int(front.width * 0.510), int(front.height * 0.096)), registry,
                    font=value_font, fill=blue)

    back_draw = ImageDraw.Draw(back)
    _cover(back_draw, back, (0.795, 0.018, 0.985, 0.063), back_fill)
    _cover(back_draw, back, (0.078, 0.222, 0.650, 0.269), back_fill)
    _cover(back_draw, back, (0.345, 0.285, 0.655, 0.350), back_fill)
    back_draw.text((int(back.width * 0.805), int(back.height * 0.025)),
                   f"Reg. No: {registry}", font=_font(max(11, back.width // 115), bold=True), fill="#000")
    back_draw.text((int(back.width * 0.090), int(back.height * 0.232)), address,
                   font=_font(max(13, back.width // 100)), fill=blue)
    label_bbox = back_draw.textbbox((0, 0), address, font=back_font)
    label_width = label_bbox[2] - label_bbox[0]
    back_draw.text(((back.width - label_width) // 2, int(back.height * 0.302)),
                   address, font=back_font, fill="#000")

    notice = "FICTIONAL WEBSITE DEMONSTRATION - ADDRESS AND REGISTRY SANITIZED"
    for image, fill in ((front, front_fill), (back, back_fill)):
        draw = ImageDraw.Draw(image)
        notice_font = _font(max(11, image.width // 115), bold=True)
        notice_box = _box(image, (0.06, 0.915, 0.94, 0.966))
        draw.rounded_rectangle(notice_box, radius=max(4, image.width // 250),
                               fill=fill, outline="#B66A20", width=max(2, image.width // 600))
        text_bbox = draw.textbbox((0, 0), notice, font=notice_font)
        draw.text(
            ((image.width - (text_bbox[2] - text_bbox[0])) // 2,
             notice_box[1] + (notice_box[3] - notice_box[1] - (text_bbox[3] - text_bbox[1])) // 2),
            notice,
            font=notice_font,
            fill="#7A4317",
        )
    return pages


def main() -> None:
    Image.init()
    parser = argparse.ArgumentParser()
    parser.add_argument("pdf", type=Path)
    parser.add_argument("--output-pdf", type=Path, required=True)
    parser.add_argument("--web-dir", type=Path, required=True)
    parser.add_argument("--prefix", default="demo-card-a")
    parser.add_argument("--address", default="100 UtiliVault Demo Way")
    parser.add_argument("--registry", default="DEMO-0000")
    args = parser.parse_args()

    front, back = sanitize_pages(args.pdf, args.address, args.registry)
    args.output_pdf.parent.mkdir(parents=True, exist_ok=True)
    front.save(args.output_pdf, save_all=True, append_images=[back], resolution=300.0)
    args.web_dir.mkdir(parents=True, exist_ok=True)
    front.save(args.web_dir / f"{args.prefix}-front.webp", "WEBP", quality=95, method=6)
    back.save(args.web_dir / f"{args.prefix}-back.webp", "WEBP", quality=95, method=6)


if __name__ == "__main__":
    main()
