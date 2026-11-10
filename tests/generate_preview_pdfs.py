# tests/generate_preview_pdfs.py

# Standard Libraries
import argparse
import random
from pathlib import Path

# Third-party Libraries
from PIL import Image, ImageDraw, ImageFont


def make_page(size: tuple[int, int], title: str, color: str) -> Image.Image:
    image = Image.new("RGB", size, "white")
    draw = ImageDraw.Draw(image)
    font = ImageFont.load_default(size=24)
    draw.rectangle(
        (20, 20, size[0] - 21, size[1] - 21), outline="black", width=3
    )
    draw.text((40, 45), title, fill="black", font=font)
    draw.text((40, 85), "SYNTHETIC PREVIEW TEST", fill="black", font=font)
    draw.rectangle((40, 140, size[0] - 41, size[1] - 100), fill=color)
    draw.text((50, 155), "First-page content", fill="black", font=font)
    draw.text((40, size[1] - 70), "No personal data", fill="black", font=font)
    return image


def generate_samples(directory: Path, large: bool = False) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    with make_page((595, 842), "Portrait A4", "#f5cdcd") as page:
        page.save(directory / "preview-portrait.pdf", resolution=72)
    with make_page((842, 595), "Landscape A4", "#f5dfb0") as page:
        page.save(directory / "preview-landscape.pdf", resolution=72)
    with (
        make_page((595, 842), "Page 1 of 2 - RED", "#f5cdcd") as first,
        make_page((595, 842), "Page 2 of 2 - BLUE", "#cddcf5") as second,
    ):
        first.save(
            directory / "preview-multipage.pdf",
            save_all=True,
            append_images=[second],
            resolution=72,
        )
    if large:
        # Random pixels exercise decoding instead of merely padding the file.
        size = (2480, 3508)
        pixels = random.Random(0).randbytes(size[0] * size[1] * 3)
        with Image.frombytes("RGB", size, pixels) as page:
            draw = ImageDraw.Draw(page)
            draw.rectangle((0, 0, size[0], 250), fill="white")
            draw.text(
                (60, 60), "SYNTHETIC 300 DPI SCAN - NO PERSONAL DATA",
                fill="black", font=ImageFont.load_default(size=60),
            )
            page.save(
                directory / "preview-large-scan.pdf",
                resolution=300, quality=100,
            )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Generate local PDF preview samples."
    )
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--large", action="store_true", help="Also create a ~16 MB scan."
    )
    args = parser.parse_args()
    generate_samples(args.output, args.large)
