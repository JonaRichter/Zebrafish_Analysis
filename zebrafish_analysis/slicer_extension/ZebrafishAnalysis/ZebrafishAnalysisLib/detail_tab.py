"""
Detail tab — full-resolution overlay + metrics for the selected image.

show_result(index, results) — display result at index, preload neighbours.
"""

import os
import sys
import threading

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
    import io
    arr = np.ascontiguousarray(rgb_array.clip(0, 255).astype("uint8"))
    buf = io.BytesIO()
    PILImage.fromarray(arr).save(buf, format="BMP")  # BMP: no compression, fast encode
    data = qt.QByteArray(buf.getvalue())
    pixmap = qt.QPixmap()
    pixmap.loadFromData(data)
    return pixmap


def _build_rgb_array(result: dict) -> np.ndarray:
    """Pure numpy/OpenCV — safe to call from any thread."""
    from overlay import make_full_overlay
    import cv2
    bgr = make_full_overlay(result)
    return cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)


class DetailTab(qt.QWidget):
    def __init__(self, on_navigate=None):
        super().__init__()
        self._on_navigate = on_navigate
        self._full_pixmap = None
        self._results = []
        self._current_idx = 0
        self._cache = {}          # index → QPixmap  (main thread only)
        self._jobs = set()        # indices currently being built
        self._pending = {}        # index → rgb ndarray  (written by workers, read by poll)
        self.setFocusPolicy(qt.Qt.StrongFocus)

        self._poll_timer = qt.QTimer()
        self._poll_timer.setInterval(40)
        self._poll_timer.timeout.connect(self._poll_pending)
        self._poll_timer.start()

        self._image_label = qt.QLabel("Select an image from the Gallery.")
        self._image_label.setAlignment(qt.Qt.AlignCenter)
        self._image_label.setStyleSheet("background: #1a1a1a; color: #666;")
        self._image_label.setMinimumHeight(300)
        self._image_label.setSizePolicy(
            qt.QSizePolicy.Ignored, qt.QSizePolicy.Ignored
        )

        self._metrics_label = qt.QLabel("")
        self._metrics_label.setWordWrap(True)
        self._metrics_label.setStyleSheet("font-size: 12px; padding: 4px;")

        self._btn_prev = qt.QPushButton("◄")
        self._btn_next = qt.QPushButton("►")
        self._nav_label = qt.QLabel("")
        self._nav_label.setAlignment(qt.Qt.AlignCenter)

        for btn in (self._btn_prev, self._btn_next):
            btn.setFixedWidth(48)
            btn.setFixedHeight(32)
            btn.setStyleSheet("font-size: 16px;")

        self._btn_prev.clicked.connect(lambda: self._on_navigate and self._on_navigate(-1))
        self._btn_next.clicked.connect(lambda: self._on_navigate and self._on_navigate(1))

        _nav_row = qt.QHBoxLayout()
        _nav_row.addStretch(1)
        _nav_row.addWidget(self._btn_prev)
        _nav_row.addWidget(self._nav_label)
        _nav_row.addWidget(self._btn_next)
        _nav_row.addStretch(1)

        layout = qt.QVBoxLayout(self)
        layout.addWidget(self._image_label, 1)
        layout.addLayout(_nav_row, 0)
        layout.addWidget(self._metrics_label, 0)

        self._btn_prev.setEnabled(False)
        self._btn_next.setEnabled(False)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def show_result(self, index: int, results: list) -> None:
        self._results = results
        self._current_idx = index
        result = results[index]

        self._metrics_label.setText(_format_metrics(result))

        if index in self._cache:
            self._full_pixmap = self._cache[index]
            qt.QTimer.singleShot(0, self._update_display)
        else:
            self._image_label.setPixmap(qt.QPixmap())
            self._image_label.setText("Loading…")
            self._full_pixmap = None
            self._start_job(index)

        self._schedule_preload(index)
        self._update_nav_state()

    def show_raw_image(self, rgb: np.ndarray, caption: str = "") -> None:
        """Display an arbitrary RGB numpy array — used for scalebar preview."""
        self._results = []
        self._current_idx = 0
        self._cache.clear()
        self._jobs.clear()
        self._pending.clear()
        self._full_pixmap = _numpy_to_qpixmap(rgb)
        self._metrics_label.setText(caption)
        self._btn_prev.setEnabled(False)
        self._btn_next.setEnabled(False)
        self._nav_label.setText("")
        self._image_label.setText("")
        qt.QTimer.singleShot(0, self._update_display)

    def invalidate_cache(self):
        """Call after a new batch run so stale pixmaps are discarded."""
        self._cache.clear()
        self._jobs.clear()
        self._pending.clear()

    def _update_nav_state(self) -> None:
        n = len(self._results)
        self._btn_prev.setEnabled(self._current_idx > 0)
        self._btn_next.setEnabled(self._current_idx < n - 1)
        if n > 0:
            self._nav_label.setText(f"{self._current_idx + 1} / {n}")
        else:
            self._nav_label.setText("")

    # ------------------------------------------------------------------
    # Background loading
    # ------------------------------------------------------------------

    def _start_job(self, index: int) -> None:
        if index in self._cache or index in self._jobs:
            return
        if index < 0 or index >= len(self._results):
            return
        result = self._results[index]
        self._jobs.add(index)

        def worker(idx=index, res=result):
            rgb = _build_rgb_array(res)
            self._pending[idx] = rgb  # CPython dict write is GIL-atomic

        threading.Thread(target=worker, daemon=True).start()

    def _poll_pending(self) -> None:
        """Main-thread timer: drain pending rgb arrays → QPixmap → cache."""
        if not self._pending:
            return
        for idx, rgb in list(self._pending.items()):
            del self._pending[idx]
            self._jobs.discard(idx)
            pixmap = _numpy_to_qpixmap(rgb)
            self._cache[idx] = pixmap
            if idx == self._current_idx and self._full_pixmap is None:
                self._full_pixmap = pixmap
                self._image_label.setText("")
                self._update_display()

    def _schedule_preload(self, center: int) -> None:
        for offset in (-1, 1, -2, 2):
            self._start_job(center + offset)

    # ------------------------------------------------------------------
    # Display
    # ------------------------------------------------------------------

    def _update_display(self) -> None:
        if self._full_pixmap is None or self._full_pixmap.isNull():
            return
        scaled = self._full_pixmap.scaled(
            self._image_label.width,
            self._image_label.height,
            qt.Qt.KeepAspectRatio,
            qt.Qt.SmoothTransformation,
        )
        self._image_label.setPixmap(scaled)

    def keyPressEvent(self, event):
        if self._on_navigate:
            if event.key() == qt.Qt.Key_Right:
                self._on_navigate(1)
                return
            if event.key() == qt.Qt.Key_Left:
                self._on_navigate(-1)
                return
        super().keyPressEvent(event)

    def resizeEvent(self, event):
        self._update_display()


def _format_metrics(r: dict) -> str:
    if r.get("error"):
        return f"<b>{r['filename']}</b>  ERROR: {r['error']}"
    parts = [f"<b>{r['filename']}</b>"]
    if r.get("length")    is not None: parts.append(f"Length: {r['length']:.1f} µm")
    if r.get("curvature") is not None: parts.append(f"Class: {r['curvature']}")
    if r.get("ratio")     is not None: parts.append(f"Ratio: {r['ratio']:.3f}")
    if r.get("eye_area")  is not None: parts.append(f"Eye area: {r['eye_area']:.1f} µm²")
    return "  |  ".join(parts)
