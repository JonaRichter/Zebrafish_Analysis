import sys
import numpy as np
import cv2
import pytest


def _has_tesseract():
    try:
        import pytesseract
        pytesseract.get_tesseract_version()
        return True
    except Exception:
        return False


@pytest.fixture
def text_image_500um():
    """Synthetic white 200x60 image with '500 um' text in black."""
    img = np.full((60, 200, 3), 255, dtype=np.uint8)
    cv2.putText(img, "500 um", (10, 45),
                cv2.FONT_HERSHEY_SIMPLEX, 1.2, (0, 0, 0), 2, cv2.LINE_AA)
    return img


@pytest.mark.skipif(not _has_tesseract(), reason="tesseract binary not installed")
def test_detect_label_ocr_finds_um_value(text_image_500um):
    from zebrafish_analysis.core.scalebar import _detect_label_ocr
    result = _detect_label_ocr(text_image_500um)
    assert result == pytest.approx(500.0, rel=0.01)


@pytest.mark.skipif(not _has_tesseract(), reason="tesseract binary not installed")
def test_detect_label_ocr_returns_none_on_blank():
    from zebrafish_analysis.core.scalebar import _detect_label_ocr
    blank = np.full((40, 100, 3), 200, dtype=np.uint8)
    assert _detect_label_ocr(blank) is None


def test_detect_label_ocr_graceful_fallback():
    """No crash when pytesseract not importable."""
    # sys.modules[name] = None causes ImportError on 'import name'
    original = sys.modules.pop("pytesseract", ...)
    sys.modules["pytesseract"] = None  # type: ignore[assignment]
    try:
        from zebrafish_analysis.core.scalebar import _detect_label_ocr
        result = _detect_label_ocr(np.zeros((40, 100, 3), dtype=np.uint8))
        assert result is None
    finally:
        del sys.modules["pytesseract"]
        if original is not ...:
            sys.modules["pytesseract"] = original
