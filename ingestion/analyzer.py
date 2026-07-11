"""Fast rich-content pre-scan for uploaded PDFs — no OCR involved.

Runs at upload time (~5-20 ms/page) using only PyMuPDF signals, and again in the
worker to route each page to the right engine. Thresholds and rationale live in
ocrplan.md §3.

Page classes:
  digital — born-digital text; the text layer is perfect, OCR would be waste
  scanned — an image of a page with no usable text layer; needs vision OCR
  rich    — has tables / large images / probable charts worth a vision pass
"""
import logging
from typing import Dict, List, Optional

import fitz  # PyMuPDF

logger = logging.getLogger(__name__)

# ---- classification thresholds (ocrplan.md §3.2) ----
TEXT_MIN_CHARS = 40      # below this the "text" is a page number / watermark
SCAN_IMG_AREA = 0.50     # raster covering half the page + no text = a scan
RICH_IMG_AREA = 0.15     # an embedded image this big is a photo/diagram, not an icon
CHART_MIN_PATHS = 40     # a rendered chart is dozens of small vector strokes


def _image_area_ratio(page: "fitz.Page") -> float:
    """Fraction of the page covered by embedded raster images, clamped to 1."""
    page_area = abs(page.rect)
    if not page_area:
        return 0.0
    covered = 0.0
    try:
        for img in page.get_images(full=True):
            for rect in page.get_image_rects(img):
                covered += abs(rect)
    except Exception:
        return 0.0
    return min(covered / page_area, 1.0)


def _vector_path_count(page: "fitz.Page") -> int:
    """Number of vector drawing paths — many small paths ≈ a rendered chart."""
    try:
        # get_cdrawings is the fast C-level variant where available.
        if hasattr(page, "get_cdrawings"):
            return len(page.get_cdrawings())
        return len(page.get_drawings())
    except Exception:
        return 0


def _table_count(page: "fitz.Page") -> int:
    """Digital table detection via PyMuPDF (>= 1.23). 0 if unsupported."""
    if not hasattr(page, "find_tables"):
        return 0
    try:
        return len(page.find_tables().tables)
    except Exception:
        return 0


def classify_page(page: "fitz.Page") -> Dict:
    """Compute the raw signals for one page and classify it."""
    text_len = len((page.get_text() or "").strip())
    img_area = _image_area_ratio(page)
    n_images = len(page.get_images(full=True))
    n_tables = _table_count(page)
    n_paths = _vector_path_count(page)

    if text_len < TEXT_MIN_CHARS and img_area > SCAN_IMG_AREA:
        page_class = "scanned"
    elif n_tables >= 1 or img_area > RICH_IMG_AREA or n_paths >= CHART_MIN_PATHS:
        page_class = "rich"
    else:
        page_class = "digital"

    return {
        "page": page.number + 1,
        "class": page_class,
        "text_len": text_len,
        "img_area": round(img_area, 3),
        "images": n_images,
        "tables": n_tables,
        "chart_likely": n_paths >= CHART_MIN_PATHS,
    }


def analyze_pdf(pdf_path: str) -> Dict:
    """Pre-scan a whole PDF. Returns a summary safe to store in documents.rich_content.

    Never raises on a readable file; per-page failures degrade that page to 'digital'.
    """
    doc = fitz.open(pdf_path)
    pages: List[Dict] = []
    for i in range(len(doc)):
        try:
            pages.append(classify_page(doc[i]))
        except Exception as e:
            logger.warning(f"Pre-scan failed on page {i + 1} of {pdf_path}: {e}")
            pages.append({"page": i + 1, "class": "digital", "text_len": 0,
                          "img_area": 0.0, "images": 0, "tables": 0, "chart_likely": False})
    doc.close()

    scanned = [p for p in pages if p["class"] == "scanned"]
    rich = [p for p in pages if p["class"] == "rich"]
    summary = {
        "page_count": len(pages),
        "tables": sum(p["tables"] for p in pages),
        "images": sum(p["images"] for p in pages if p["class"] != "scanned"),
        "charts": sum(1 for p in pages if p["chart_likely"]),
        "scanned_pages": len(scanned),
        "is_rich": bool(scanned or rich),
        # Only the interesting pages — keeps the JSON small for big documents.
        "rich_pages": [
            {"page": p["page"], "class": p["class"], "tables": p["tables"],
             "images": p["images"], "chart_likely": p["chart_likely"]}
            for p in (scanned + rich)
        ][:200],
    }
    return summary


def analyze_file(path: str) -> Optional[Dict]:
    """Upload-time entry point. Only PDFs are pre-scanned; other types return None
    and flow through ingestion exactly as before."""
    if not str(path).lower().endswith(".pdf"):
        return None
    try:
        return analyze_pdf(path)
    except Exception as e:
        logger.warning(f"Pre-scan could not open {path}: {e}")
        return None
