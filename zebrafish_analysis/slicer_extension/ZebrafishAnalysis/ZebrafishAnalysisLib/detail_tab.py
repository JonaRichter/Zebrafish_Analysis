"""
Detail tab — full-resolution overlay + metrics for the selected image.

show_result(result) — display a single result dict.
"""

import os
import sys

# Ensure ZebrafishAnalysisLib is first on sys.path so 'overlay' resolves locally.
_LIB_DIR = os.path.dirname(os.path.abspath(__file__))
if _LIB_DIR not in sys.path:
    sys.path.insert(0, _LIB_DIR)
elif sys.path[0] != _LIB_DIR:
    sys.path.remove(_LIB_DIR)
    sys.path.insert(0, _LIB_DIR)

import qt
import numpy as np


def _numpy_to_qpixmap(rgb_array: np.ndarray) -> "qt.QPixmap":
    from PIL import Image as PILImage
    import tempfile
    import os
    arr = np.ascontiguousarray(rgb_array.clip(0, 255).astype("uint8"))
    tmp = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
    try:
        PILImage.fromarray(arr).save(tmp.name)
        tmp.close()
        return qt.QPixmap(tmp.name)
    finally:
        os.unlink(tmp.name)


class DetailTab(qt.QWidget):
    def __init__(self):
        super().__init__()
        self._current_result = None

        self._image_label = qt.QLabel("Select an image from the Gallery.")
        self._image_label.setAlignment(qt.Qt.AlignCenter)
        self._image_label.setStyleSheet("background: #1a1a1a; color: #666;")
        self._image_label.setMinimumHeight(300)
        self._image_label.setSizePolicy(
            qt.QSizePolicy.Expanding, qt.QSizePolicy.Expanding
        )

        self._metrics_label = qt.QLabel("")
        self._metrics_label.setWordWrap(True)
        self._metrics_label.setStyleSheet("font-size: 12px; padding: 4px;")

        layout = qt.QVBoxLayout(self)
        layout.addWidget(self._image_label, 1)
        layout.addWidget(self._metrics_label, 0)

    def show_result(self, result: dict) -> None:
        self._current_result = result
        self._render()

    def _render(self) -> None:
        if self._current_result is None:
            return
        from overlay import make_full_overlay
        import cv2

        bgr = make_full_overlay(self._current_result)
        rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
        pixmap = _numpy_to_qpixmap(rgb)

        scaled = pixmap.scaled(
            self._image_label.width,
            self._image_label.height,
            qt.Qt.KeepAspectRatio,
            qt.Qt.SmoothTransformation,
        )
        self._image_label.setPixmap(scaled)
        self._metrics_label.setText(_format_metrics(self._current_result))

    def resizeEvent(self, event):
        self._render()


def _format_metrics(r: dict) -> str:
    if r.get("error"):
        return f"<b>{r['filename']}</b>  ERROR: {r['error']}"
    parts = [f"<b>{r['filename']}</b>"]
    if r.get("length")    is not None: parts.append(f"Length: {r['length']:.1f} µm")
    if r.get("curvature") is not None: parts.append(f"Class: {r['curvature']}")
    if r.get("ratio")     is not None: parts.append(f"Ratio: {r['ratio']:.3f}")
    if r.get("eye_area")  is not None: parts.append(f"Eye area: {r['eye_area']:.1f} µm²")
    return "  |  ".join(parts)
