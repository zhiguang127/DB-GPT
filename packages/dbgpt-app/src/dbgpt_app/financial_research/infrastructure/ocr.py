"""Optional OCR fallback for filings without a usable text layer.

OCR is off unless explicitly requested. Recognized text is not equivalent to
disclosed text: character confusion in CJK digit groups can silently change a
figure, so every page produced here is tagged ``text_source="ocr"`` and the
extractor lowers the confidence of any evidence drawn from it.

No OCR dependency is declared by this package. If none is installed the caller
receives :class:`OcrUnavailableError` and surfaces it, rather than falling back
to an empty document that would look like a parsing failure.
"""

import logging
import re
from pathlib import Path
from typing import List, Tuple

logger = logging.getLogger(__name__)

# Chinese + English; pytesseract needs both traineddata files present.
_TESSERACT_LANGS = "chi_sim+eng"
_RENDER_DPI = 300


class OcrUnavailableError(RuntimeError):
    """Raised when OCR was requested but no backend is installed."""


def _ocr_with_paddle(path: Path) -> List[Tuple[int, str]]:
    import pdfplumber  # noqa: PLC0415
    from paddleocr import PaddleOCR  # noqa: PLC0415

    engine = PaddleOCR(use_angle_cls=True, lang="ch", show_log=False)
    results: List[Tuple[int, str]] = []
    with pdfplumber.open(path) as pdf:
        for index, page in enumerate(pdf.pages, start=1):
            image = page.to_image(resolution=_RENDER_DPI).original
            recognized = engine.ocr(_to_numpy(image), cls=True) or []
            lines = [
                entry[1][0]
                for block in recognized
                if block
                for entry in block
                if entry and entry[1]
            ]
            results.append((index, "\n".join(lines)))
    return results


def _to_numpy(image):
    import numpy  # noqa: PLC0415

    return numpy.array(image)


def _ocr_with_tesseract(path: Path) -> List[Tuple[int, str]]:
    import pdfplumber  # noqa: PLC0415
    import pytesseract  # noqa: PLC0415

    results: List[Tuple[int, str]] = []
    with pdfplumber.open(path) as pdf:
        for index, page in enumerate(pdf.pages, start=1):
            image = page.to_image(resolution=_RENDER_DPI).original
            text = pytesseract.image_to_string(image, lang=_TESSERACT_LANGS)
            results.append((index, text or ""))
    return results


def ocr_pdf_pages(path: Path) -> List[Tuple[int, str]]:
    """Recognize every page, returning ``(page_number, text)`` pairs.

    PaddleOCR is preferred for Simplified Chinese layout accuracy; Tesseract is
    the fallback. Both are optional imports resolved at call time.
    """
    backends = (
        ("paddleocr", _ocr_with_paddle),
        ("pytesseract", _ocr_with_tesseract),
    )
    errors: list[str] = []
    for name, backend in backends:
        try:
            pages = backend(path)
        except ImportError as exc:
            errors.append(f"{name}: {exc}")
            continue
        except Exception as exc:  # pragma: no cover - backend runtime failure
            logger.warning("OCR backend %s failed on %s: %s", name, path.name, exc)
            errors.append(f"{name}: {exc}")
            continue
        if any(re.sub(r"\s+", "", text) for _, text in pages):
            return pages
        errors.append(f"{name}: 未识别出任何文字")
    raise OcrUnavailableError(
        f"{path.name} 需要 OCR，但没有可用的 OCR 后端。"
        "请安装 paddleocr 或 pytesseract（附 chi_sim 语言包）后重试。"
        f"（诊断：{'；'.join(errors) or '无'}）"
    )
