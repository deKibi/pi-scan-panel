# pi_scan_panel/pdf_preview.py

# Standard Libraries
import argparse
import math
from pathlib import Path

# Third-party Libraries
import pypdfium2 as pdfium


def render_pdf_preview(
    source: Path, destination: Path, width: int, height: int, quality: int
) -> None:
    with pdfium.PdfDocument(source) as document:
        if not len(document):
            raise ValueError("PDF has no pages")
        page = document[0]
        try:
            page_width, page_height = page.get_size()
            if not all(
                math.isfinite(value) and value > 0
                for value in (page_width, page_height)
            ):
                raise ValueError("Invalid PDF page dimensions")
            scale = min(width / page_width, height / page_height)
            bitmap = page.render(scale=scale, fill_color=(255, 255, 255, 255))
            try:
                with bitmap.to_pil() as image:
                    image.thumbnail((width, height))
                    with image.convert("RGB") as thumbnail:
                        thumbnail.save(
                            destination, format="JPEG",
                            quality=quality, optimize=True,
                        )
            finally:
                bitmap.close()
        finally:
            page.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Render the first PDF page as JPEG."
    )
    parser.add_argument("source", type=Path)
    parser.add_argument("destination", type=Path)
    parser.add_argument("width", type=int)
    parser.add_argument("height", type=int)
    parser.add_argument("quality", type=int)
    args = parser.parse_args()
    if args.width < 1 or args.height < 1 or not 1 <= args.quality <= 95:
        parser.error("Use positive dimensions and JPEG quality from 1 to 95")
    render_pdf_preview(
        args.source, args.destination, args.width, args.height, args.quality
    )
