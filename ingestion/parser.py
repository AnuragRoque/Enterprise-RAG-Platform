"""Document parsing with per-page engine routing (ocrplan.md §3.3).

Every page keeps its free PyMuPDF text layer when it has one. Pages that need
eyes — scans, tables, charts, big images — are routed to the GLM-OCR vision
model on Ollama when it's pulled, with Tesseract as the no-GPU fallback and the
raw text layer as the last resort. Digital tables are recovered structurally by
PyMuPDF's table finder at zero OCR cost.

parse() returns flowing text per page plus *atomic blocks* (tables, figure
descriptions) that the worker stores as unsplittable chunks.
"""
import base64
import logging
import re
from typing import Dict, List, Optional

import fitz  # PyMuPDF
import httpx

from core.config import settings
from ingestion.analyzer import classify_page, RICH_IMG_AREA

logger = logging.getLogger(__name__)

# Attempt to load OCR dependencies, gracefully fall back if unavailable
try:
    from pdf2image import convert_from_path
    import pytesseract
    TESSERACT_AVAILABLE = True
except ImportError:
    TESSERACT_AVAILABLE = False
    logger.warning("pdf2image or pytesseract not installed. Tesseract fallback will be disabled.")


def glm_ocr_available(timeout: float = 3.0) -> bool:
    """True when the configured vision model is pulled in Ollama."""
    base_name = settings.ocr_model.split(":")[0]
    try:
        res = httpx.get(f"{settings.ollama_base_url}/api/tags", timeout=timeout)
        res.raise_for_status()
        models = res.json().get("models", [])
        return any(str(m.get("name", "")).split(":")[0] == base_name for m in models)
    except Exception:
        return False


class GlmOcrClient:
    """Thin wrapper over Ollama's chat API for the three GLM-OCR prompt modes."""

    PROMPTS = {
        "text": "Text Recognition:",
        "table": "Table Recognition:",
        "figure": "Figure Recognition:",
    }

    def _render_page(self, page: "fitz.Page") -> str:
        pix = page.get_pixmap(dpi=settings.ocr_page_dpi)
        return base64.b64encode(pix.tobytes("png")).decode("ascii")

    def recognize(self, page: "fitz.Page", mode: str, image_b64: Optional[str] = None) -> str:
        """Run one recognition mode on a page. Returns '' on any failure so a
        dead model can never fail an ingest job."""
        prompt = self.PROMPTS[mode]
        try:
            payload = {
                "model": settings.ocr_model,
                "messages": [{
                    "role": "user",
                    "content": prompt,
                    "images": [image_b64 or self._render_page(page)],
                }],
                "stream": False,
                # Vision calls come in bursts during one document; keep the model warm.
                "keep_alive": "10m",
            }
            res = httpx.post(
                f"{settings.ollama_base_url}/api/chat",
                json=payload,
                timeout=settings.ocr_timeout_seconds,
            )
            res.raise_for_status()
            content = (res.json().get("message", {}).get("content") or "").strip()
            # The model tends to echo its prompt ("Figure Recognition:") back at the
            # start (sometimes repeatedly) — strip those echoes from the output.
            changed = True
            while changed:
                changed = False
                for echo in self.PROMPTS.values():
                    if content.startswith(echo):
                        content = content[len(echo):].lstrip("\n ").lstrip()
                        changed = True
            return content
        except Exception as e:
            logger.error(f"GLM-OCR {mode} failed on page {page.number + 1}: {e}")
            return ""


def _table_to_markdown(table) -> str:
    """Serialize a PyMuPDF table to markdown, tolerating old versions."""
    try:
        if hasattr(table, "to_markdown"):
            return table.to_markdown().strip()
    except Exception:
        pass
    try:
        rows = table.extract()
        if not rows:
            return ""
        clean = [[("" if c is None else str(c).replace("\n", " ").strip()) for c in row] for row in rows]
        header = "| " + " | ".join(clean[0]) + " |"
        sep = "|" + "|".join(" --- " for _ in clean[0]) + "|"
        body = ["| " + " | ".join(r) + " |" for r in clean[1:]]
        return "\n".join([header, sep] + body)
    except Exception:
        return ""


class DocumentParser:
    def __init__(self):
        self.ocr_available = TESSERACT_AVAILABLE  # kept for backward compatibility
        self.glm = GlmOcrClient()

    def normalize_text(self, text: str) -> str:
        """
        Normalize flowing text: de-hyphenate across line breaks, collapse spaces.
        Never applied to atomic blocks — it would corrupt markdown table rows.
        """
        text = re.sub(r'-\n\s*', '', text)
        text = re.sub(r' +', ' ', text)
        return text.strip()

    def _extract_text_ocr(self, pdf_path: str, page_num: int) -> str:
        """Tesseract fallback for a specific page (pdf2image indices are 1-based)."""
        if not TESSERACT_AVAILABLE:
            return ""
        try:
            images = convert_from_path(pdf_path, first_page=page_num + 1, last_page=page_num + 1)
            if images:
                return pytesseract.image_to_string(images[0])
        except Exception as e:
            logger.error(f"OCR failed for {pdf_path} page {page_num}: {e}")
        return ""

    # ------------------------------------------------------------------ #
    # New routed entry point
    # ------------------------------------------------------------------ #
    def parse(self, pdf_path: str, mode: str = "standard") -> Dict:
        """Parse a PDF with per-page engine routing.

        Returns {"pages": [{page, text}], "blocks": [{page, kind, text}],
                 "engines": [names...]}.
        mode="standard": text layer + free digital-table recovery + legacy OCR
                         fallback for empty pages.
        mode="deep":     additionally classify pages and send scanned/rich pages
                         through GLM-OCR (text / table / figure prompts).
        """
        use_glm = mode == "deep" and glm_ocr_available()
        if mode == "deep" and not use_glm:
            logger.warning(
                f"Deep scan requested but '{settings.ocr_model}' is not pulled in "
                "Ollama — falling back to Tesseract/text layer."
            )

        doc = fitz.open(pdf_path)
        pages: List[Dict] = []
        blocks: List[Dict] = []
        engines = set()

        for i in range(len(doc)):
            page = doc[i]
            info = classify_page(page) if mode == "deep" else None
            page_class = info["class"] if info else None
            text = page.get_text()
            page_image_b64: Optional[str] = None  # rendered lazily, reused per page

            # ---- scanned page: no usable text layer, needs vision ----
            if (page_class == "scanned") or (not text.strip()):
                ocr_text = ""
                if use_glm:
                    page_image_b64 = self.glm._render_page(page)
                    ocr_text = self.glm.recognize(page, "text", page_image_b64)
                    if ocr_text:
                        engines.add("glm-ocr")
                if not ocr_text and TESSERACT_AVAILABLE:
                    logger.info(f"Page {i + 1}: falling back to Tesseract OCR...")
                    ocr_text = self._extract_text_ocr(pdf_path, i)
                    if ocr_text:
                        engines.add("tesseract")
                if ocr_text:
                    text = ocr_text
            else:
                engines.add("pymupdf")

            # ---- digital tables: free structural recovery, any mode ----
            n_tables_found = 0
            if hasattr(page, "find_tables") and text.strip():
                try:
                    for table in page.find_tables().tables:
                        md = _table_to_markdown(table)
                        # A one-row "table" is usually a layout artifact — skip.
                        if md and md.count("\n") >= 2:
                            blocks.append({"page": i + 1, "kind": "table", "text": md})
                            n_tables_found += 1
                except Exception as e:
                    logger.warning(f"Table extraction failed on page {i + 1}: {e}")

            # ---- deep mode extras on rich pages ----
            if use_glm and info and page_class == "rich":
                # Tables the digital finder saw but couldn't serialize → vision pass.
                if info["tables"] > n_tables_found:
                    page_image_b64 = page_image_b64 or self.glm._render_page(page)
                    md = self.glm.recognize(page, "table", page_image_b64)
                    if md:
                        blocks.append({"page": i + 1, "kind": "table", "text": md})
                        engines.add("glm-ocr")
                # Charts / big embedded images → describe them so they're retrievable.
                if info["chart_likely"] or info["img_area"] > RICH_IMG_AREA:
                    page_image_b64 = page_image_b64 or self.glm._render_page(page)
                    desc = self.glm.recognize(page, "figure", page_image_b64)
                    if desc:
                        blocks.append({"page": i + 1, "kind": "figure", "text": desc})
                        engines.add("glm-ocr")

            text = self.normalize_text(text)
            if text:
                pages.append({"page": i + 1, "text": text})

        doc.close()
        return {"pages": pages, "blocks": blocks, "engines": sorted(engines)}

    # ------------------------------------------------------------------ #
    # Legacy entry point (kept for compatibility with older callers/tests)
    # ------------------------------------------------------------------ #
    def parse_pdf(self, pdf_path: str) -> List[Dict[str, str]]:
        """Extract flowing text only, standard routing. Prefer parse()."""
        return self.parse(pdf_path, mode="standard")["pages"]
