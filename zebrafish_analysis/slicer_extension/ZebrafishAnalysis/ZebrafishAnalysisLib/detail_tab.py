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


class _ClickableLabel(qt.QLabel):
    """QLabel that forwards left-click coords to a handler when click mode is active."""

    def __init__(self, click_handler=None, parent=None):
        super().__init__(parent)
        self._click_handler = click_handler

    def mousePressEvent(self, event):
        if self._click_handler and event.button() == qt.Qt.LeftButton:
            self._click_handler(event.x(), event.y())
        super().mousePressEvent(event)


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

        self._manual_mode = False
        self._manual_points = []   # list of (row, col) in original image space
        self._params_getter = None  # set by widget after construction
        self._swipe_accum = 0         # accumulated horizontal wheel delta for swipe navigation
        self._swipe_triggered = False  # fire at most once per gesture

        self._poll_timer = qt.QTimer()
        self._poll_timer.setInterval(40)
        self._poll_timer.timeout.connect(self._poll_pending)
        self._poll_timer.start()

        self._image_label = _ClickableLabel(self._on_image_click)
        self._image_label.setText("Select an image from the Gallery.")
        self._image_label.setAlignment(qt.Qt.AlignCenter)
        self._image_label.setStyleSheet("background: #1a1a1a; color: #666;")
        self._image_label.setMinimumHeight(300)
        self._image_label.setSizePolicy(
            qt.QSizePolicy.Ignored, qt.QSizePolicy.Ignored
        )

        self._metrics_label = qt.QLabel("")
        self._metrics_label.setWordWrap(True)
        self._metrics_label.setStyleSheet("font-size: 12px; padding: 4px;")

        self._btn_manual_adjust = qt.QPushButton("✏ Manual Adjust")
        self._btn_revert_auto = qt.QPushButton("↩ Revert to Auto")
        self._btn_revert_auto.setVisible(False)
        self._manual_status = qt.QLabel("")
        self._manual_status.setAlignment(qt.Qt.AlignCenter)
        self._manual_status.setStyleSheet("font-size: 11px; color: #aaa; padding: 2px;")
        self._manual_status.setVisible(False)

        self._btn_manual_adjust.clicked.connect(self._on_manual_adjust_clicked)
        self._btn_revert_auto.clicked.connect(self._on_revert_auto_clicked)

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

        _manual_row = qt.QHBoxLayout()
        _manual_row.addStretch(1)
        _manual_row.addWidget(self._btn_manual_adjust)
        _manual_row.addWidget(self._btn_revert_auto)
        _manual_row.addStretch(1)

        layout = qt.QVBoxLayout(self)
        layout.addWidget(self._image_label, 1)
        layout.addLayout(_manual_row, 0)
        layout.addWidget(self._manual_status, 0)
        layout.addLayout(_nav_row, 0)
        layout.addWidget(self._metrics_label, 0)

        self._btn_prev.setEnabled(False)
        self._btn_next.setEnabled(False)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def show_result(self, index: int, results: list) -> None:
        # Exit click mode when navigating to a new image
        if self._manual_mode:
            self._manual_mode = False
            self._manual_points = []
            self._manual_status.setVisible(False)

        self._results = results
        self._current_idx = index
        result = results[index]

        self._metrics_label.setText(_format_metrics(result))

        # Sync button state
        is_corrected = bool(result.get("manual_corrected"))
        self._btn_revert_auto.setVisible(is_corrected)
        self._btn_manual_adjust.setText(
            "✏ Redo Manual" if is_corrected else "✏ Manual Adjust"
        )
        self._manual_status.setText("")
        self._manual_status.setVisible(False)

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
            if idx == self._current_idx:
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

    def wheelEvent(self, event):
        """Two-finger horizontal trackpad swipe → navigate one image per gesture."""
        # Ignore momentum phase (post-lift inertia that causes multi-image scroll)
        _MOMENTUM = getattr(qt.Qt, "ScrollMomentum", 4)
        if event.phase() == _MOMENTUM:
            event.accept()
            return

        dx = event.angleDelta().x()
        dy = event.angleDelta().y()

        if abs(dx) > abs(dy) and self._on_navigate:
            # New gesture starting — reset state
            _BEGIN = getattr(qt.Qt, "ScrollBegin", 1)
            if event.phase() == _BEGIN:
                self._swipe_accum = 0
                self._swipe_triggered = False

            if not self._swipe_triggered:
                self._swipe_accum += dx
                if self._swipe_accum > 60:
                    self._swipe_triggered = True
                    self._on_navigate(-1)  # fingers left → previous
                elif self._swipe_accum < -60:
                    self._swipe_triggered = True
                    self._on_navigate(1)   # fingers right → next
        else:
            self._swipe_accum = 0
            self._swipe_triggered = False
            super().wheelEvent(event)

    def resizeEvent(self, event):
        self._update_display()

    # ------------------------------------------------------------------
    # Manual correction — click mode
    # ------------------------------------------------------------------

    def _on_manual_adjust_clicked(self):
        """Enter click mode to place head/tail points."""
        if not self._results:
            return
        self._manual_mode = True
        self._manual_points = []
        self._manual_status.setText("Click HEAD point (1/2)")
        self._manual_status.setVisible(True)
        # Restore clean overlay (no stale dots)
        self._update_display()

    def _on_revert_auto_clicked(self):
        """Restore auto-computed values for current fish."""
        if not self._results:
            return
        result = self._results[self._current_idx]
        import logic
        logic.revert_manual_correction(result)

        self._cache.pop(self._current_idx, None)
        self._jobs.discard(self._current_idx)

        self._manual_mode = False
        self._manual_points = []
        self._manual_status.setText("Reverted to auto.")
        self._manual_status.setVisible(True)
        self._btn_revert_auto.setVisible(False)
        self._btn_manual_adjust.setText("✏ Manual Adjust")
        self._metrics_label.setText(_format_metrics(result))

        self._start_job(self._current_idx)

    def _on_image_click(self, click_x, click_y):
        """Handle a left-click on the image label during manual mode."""
        if not self._manual_mode:
            return
        coords = self._label_to_orig_coords(click_x, click_y)
        if coords is None:
            return

        self._manual_points.append(coords)
        self._redraw_with_dots()

        if len(self._manual_points) == 1:
            self._manual_status.setText("Click TAIL point (2/2)")
        elif len(self._manual_points) >= 2:
            self._manual_mode = False
            self._manual_status.setText("Computing…")
            self._apply_correction()

    def _label_to_orig_coords(self, click_x, click_y):
        """Map label pixel (x, y) → original image (row, col).  Returns None on failure."""
        if self._full_pixmap is None or self._full_pixmap.isNull():
            return None
        if not self._results or self._current_idx >= len(self._results):
            return None

        orig = self._results[self._current_idx].get("original")
        if orig is None:
            return None

        orig_h, orig_w = orig.shape[:2]
        label_w = self._image_label.width
        label_h = self._image_label.height
        pix_w = self._full_pixmap.width()
        pix_h = self._full_pixmap.height()

        if pix_w == 0 or pix_h == 0 or label_w == 0 or label_h == 0:
            return None

        scale = min(label_w / pix_w, label_h / pix_h)
        offset_x = (label_w - pix_w * scale) / 2
        offset_y = (label_h - pix_h * scale) / 2

        img_col = (click_x - offset_x) / scale
        img_row = (click_y - offset_y) / scale

        col = int(np.clip(img_col, 0, orig_w - 1))
        row = int(np.clip(img_row, 0, orig_h - 1))
        return (row, col)

    def _redraw_with_dots(self):
        """Draw placed manual points on a copy of the current scaled pixmap."""
        if self._full_pixmap is None or self._full_pixmap.isNull():
            return

        label_w = self._image_label.width
        label_h = self._image_label.height
        pix_w = self._full_pixmap.width()
        pix_h = self._full_pixmap.height()

        scaled = self._full_pixmap.scaled(
            label_w, label_h, qt.Qt.KeepAspectRatio, qt.Qt.SmoothTransformation
        )

        if not self._manual_points:
            self._image_label.setPixmap(scaled)
            return

        # scale maps original-image coords → pixmap coords (no letterbox offsets:
        # the label centers the scaled pixmap automatically, so dots must be in
        # pixmap space, not label space)
        scale = min(label_w / pix_w, label_h / pix_h)
        pix_draw_w = pix_w * scale
        pix_draw_h = pix_h * scale

        colors = [qt.QColor(0, 220, 0), qt.QColor(220, 0, 0)]  # green=head, red=tail
        painter = qt.QPainter(scaled)
        for i, (row, col) in enumerate(self._manual_points):
            lx = int(np.clip(col * scale, 8, pix_draw_w - 9))
            ly = int(np.clip(row * scale, 8, pix_draw_h - 9))
            c = colors[i]
            painter.setPen(qt.QPen(c, 3))
            painter.setBrush(qt.QBrush(qt.QColor(c.red(), c.green(), c.blue(), 180)))
            painter.drawEllipse(lx - 8, ly - 8, 16, 16)
        painter.end()
        self._image_label.setPixmap(scaled)

    def _apply_correction(self):
        """Apply 2-point manual correction to current result and refresh."""
        if len(self._manual_points) < 2:
            return
        result = self._results[self._current_idx]
        params = self._params_getter() if callable(self._params_getter) else {}

        import logic
        logic.apply_manual_correction(
            result, self._manual_points[0], self._manual_points[1], params
        )

        self._cache.pop(self._current_idx, None)
        self._jobs.discard(self._current_idx)
        self._manual_points = []
        self._full_pixmap = None  # force _poll_pending to update display on rebuild

        self._manual_status.setText("Manual correction applied.")
        self._btn_revert_auto.setVisible(True)
        self._btn_manual_adjust.setText("✏ Redo Manual")
        self._metrics_label.setText(_format_metrics(result))

        self._start_job(self._current_idx)


def _format_metrics(r: dict) -> str:
    if r.get("error"):
        return f"<b>{r['filename']}</b>  ERROR: {r['error']}"
    parts = [f"<b>{r['filename']}</b>"]
    if r.get("length")    is not None: parts.append(f"Length: {r['length']:.1f} µm")
    if r.get("curvature") is not None: parts.append(f"Class: {r['curvature']}")
    if r.get("ratio")     is not None: parts.append(f"Ratio: {r['ratio']:.3f}")
    if r.get("eye_area")  is not None: parts.append(f"Eye area: {r['eye_area']:.1f} µm²")
    return "  |  ".join(parts)
