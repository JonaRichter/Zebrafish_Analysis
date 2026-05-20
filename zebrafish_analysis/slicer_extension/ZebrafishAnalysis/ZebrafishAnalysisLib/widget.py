"""
Main widget for the ZebrafishAnalysis Slicer extension.

Left panel: input, analysis toggles, model selection, scalebar, run, export.
Right panel: QTabWidget with Gallery / Detail / Results / Exclude tabs.
"""

import qt
import ctk
import slicer

from overlay   import make_overlay, make_full_overlay
from logic     import detect_scalebar, analyse_images
from export    import export_excel, export_csv


class ZebrafishAnalysisMainWidget:
    def __init__(self, parent_layout):
        slicer.app.layoutManager().setLayout(
            slicer.vtkMRMLLayoutNode.SlicerLayoutOneUpRedSliceView
        )

        self._results = []
        self._excluded = set()
        self._image_paths = []

        self._build_ui(parent_layout)
        self._connect_signals()

    def _build_ui(self, layout):
        splitter = qt.QSplitter(qt.Qt.Horizontal)
        splitter.setChildrenCollapsible(False)
        layout.addWidget(splitter)

        self._build_left_panel(splitter)
        self._build_right_panel(splitter)
        splitter.setStretchFactor(1, 1)

        self._progress = qt.QProgressBar()
        self._progress.setVisible(False)
        layout.addWidget(self._progress)

    def _build_left_panel(self, splitter):
        left = qt.QWidget()
        left.setFixedWidth(275)
        vbox = qt.QVBoxLayout(left)
        vbox.setContentsMargins(4, 4, 4, 4)
        vbox.setSpacing(6)
        splitter.addWidget(left)

        input_box = ctk.ctkCollapsibleButton()
        input_box.text = "Input"
        vbox.addWidget(input_box)
        in_layout = qt.QVBoxLayout(input_box)

        self._btn_folder = qt.QPushButton("Load Folder…")
        self._btn_files  = qt.QPushButton("Load Images…")
        in_layout.addWidget(self._btn_folder)
        in_layout.addWidget(self._btn_files)
        in_layout.addWidget(qt.QLabel("Queue:"))
        self._queue_list = qt.QListWidget()
        self._queue_list.setMaximumHeight(120)
        in_layout.addWidget(self._queue_list)

        analysis_box = ctk.ctkCollapsibleButton()
        analysis_box.text = "Analysis"
        vbox.addWidget(analysis_box)
        an_layout = qt.QVBoxLayout(analysis_box)

        self._chk_length    = qt.QCheckBox("Body length");        self._chk_length.setChecked(True)
        self._chk_curvature = qt.QCheckBox("Curvature class");    self._chk_curvature.setChecked(True)
        self._chk_ratio     = qt.QCheckBox("Length/straight ratio"); self._chk_ratio.setChecked(True)
        self._chk_eyes      = qt.QCheckBox("Eye segmentation");   self._chk_eyes.setChecked(False)
        self._chk_hitl      = qt.QCheckBox("Confidence threshold"); self._chk_hitl.setChecked(True)

        for chk in (self._chk_length, self._chk_curvature, self._chk_ratio,
                    self._chk_eyes, self._chk_hitl):
            an_layout.addWidget(chk)

        self._threshold_slider = ctk.ctkSliderWidget()
        self._threshold_slider.minimum    = 0.0
        self._threshold_slider.maximum    = 1.0
        self._threshold_slider.singleStep = 0.01
        self._threshold_slider.value      = 0.85
        self._threshold_slider.decimals   = 2
        an_layout.addWidget(self._threshold_slider)

        model_box = ctk.ctkCollapsibleButton()
        model_box.text      = "Model"
        model_box.collapsed = True
        vbox.addWidget(model_box)
        m_layout = qt.QFormLayout(model_box)

        self._model_combo = qt.QComboBox()
        self._model_combo.addItem("General Model",   ("best_model_body_3400_vgg19.pth", "vgg19", None))
        self._model_combo.addItem("Fine-tuned DESY", ("best_model_body_finetuned.pth",  "vgg19", "best_model_eye_finetuned.pth"))
        m_layout.addRow("Segmentation model:", self._model_combo)

        scale_box = ctk.ctkCollapsibleButton()
        scale_box.text      = "Scale bar"
        scale_box.collapsed = True
        vbox.addWidget(scale_box)
        sc_layout = qt.QVBoxLayout(scale_box)

        self._btn_detect_scale = qt.QPushButton("Auto-detect from first image")
        sc_layout.addWidget(self._btn_detect_scale)

        self._scale_status = qt.QLabel("Load images first.")
        self._scale_status.setWordWrap(True)
        self._scale_status.setStyleSheet("color: #888; font-size: 11px;")
        sc_layout.addWidget(self._scale_status)

        form = qt.QFormLayout()
        self._bar_um_edit = qt.QLineEdit()
        self._bar_um_edit.setPlaceholderText("e.g. 500")
        form.addRow("Physical bar length (µm):", self._bar_um_edit)
        sc_layout.addLayout(form)

        self._btn_apply_scale = qt.QPushButton("Apply")
        sc_layout.addWidget(self._btn_apply_scale)

        sep = qt.QLabel("— or enter µm/px directly —")
        sep.setStyleSheet("color: #888; font-size: 11px;")
        sep.setAlignment(qt.Qt.AlignCenter)
        sc_layout.addWidget(sep)

        direct = qt.QFormLayout()
        self._um_per_px = ctk.ctkDoubleSpinBox()
        self._um_per_px.minimum    = 0.001
        self._um_per_px.maximum    = 9999.0
        self._um_per_px.singleStep = 0.01
        self._um_per_px.value      = 22.99
        self._um_per_px.decimals   = 4
        self._um_per_px.suffix     = " µm/px"
        direct.addRow("µm per pixel:", self._um_per_px)
        sc_layout.addLayout(direct)

        self._btn_run = qt.QPushButton("▶  Run Analysis")
        self._btn_run.setStyleSheet("font-weight: bold; padding: 6px;")
        vbox.addWidget(self._btn_run)

        export_box = ctk.ctkCollapsibleButton()
        export_box.text = "Export"
        vbox.addWidget(export_box)
        ex_layout = qt.QHBoxLayout(export_box)
        self._btn_excel = qt.QPushButton("Excel")
        self._btn_csv   = qt.QPushButton("CSV")
        ex_layout.addWidget(self._btn_excel)
        ex_layout.addWidget(self._btn_csv)

        vbox.addStretch()

    def _build_right_panel(self, splitter):
        self._tabs = qt.QTabWidget()
        splitter.addWidget(self._tabs)

        for name in ("Gallery", "Detail", "Results", "Exclude"):
            placeholder = qt.QLabel(f"{name} tab — coming soon")
            placeholder.setAlignment(qt.Qt.AlignCenter)
            self._tabs.addTab(placeholder, name)

    def _connect_signals(self):
        self._btn_folder.clicked.connect(self._on_load_folder)
        self._btn_files.clicked.connect(self._on_load_files)
        self._btn_detect_scale.clicked.connect(self._on_detect_scale)
        self._btn_apply_scale.clicked.connect(self._on_apply_scale)
        self._btn_run.clicked.connect(self._on_run)
        self._btn_excel.clicked.connect(self._on_export_excel)
        self._btn_csv.clicked.connect(self._on_export_csv)

    def _on_load_folder(self):
        folder = qt.QFileDialog.getExistingDirectory(None, "Select image folder")
        if not folder:
            return
        import os
        exts = {".png", ".tif", ".tiff", ".jpg", ".jpeg"}
        paths = sorted([
            os.path.join(folder, f)
            for f in os.listdir(folder)
            if os.path.splitext(f)[1].lower() in exts
        ])
        self._set_queue(paths)

    def _on_load_files(self):
        paths, _ = qt.QFileDialog.getOpenFileNames(
            None, "Select images", "",
            "Images (*.png *.tif *.tiff *.jpg *.jpeg)"
        )
        if paths:
            self._set_queue(sorted(paths))

    def _set_queue(self, paths):
        self._image_paths = paths
        self._queue_list.clear()
        import os
        for p in paths:
            self._queue_list.addItem(os.path.basename(p))

    def _on_detect_scale(self):
        if not self._image_paths:
            self._scale_status.setText("Load images first.")
            return
        result = detect_scalebar(self._image_paths[0])
        if result.get("bar_found"):
            self._um_per_px.value = result["scale_um_per_px"]
            self._scale_status.setText(
                f"Detected: {result['scale_um_per_px']:.4f} µm/px"
            )
        else:
            self._scale_status.setText(
                "Not detected. Enter bar length + click Apply, or set µm/px directly."
            )

    def _on_apply_scale(self):
        text = self._bar_um_edit.text.strip()
        if not text or not self._image_paths:
            return
        try:
            label_um = float(text)
        except ValueError:
            self._scale_status.setText("Invalid value — enter a number.")
            return
        result = detect_scalebar(self._image_paths[0], label_um=label_um)
        if result.get("success"):
            self._um_per_px.value = result["scale_um_per_px"]
            self._scale_status.setText(
                f"Applied: {result['scale_um_per_px']:.4f} µm/px"
            )

    def _on_run(self):
        if not self._image_paths:
            slicer.util.warningDisplay("No images loaded.")
            return
        self._progress.setVisible(True)
        self._progress.setRange(0, len(self._image_paths))

        model_data = self._model_combo.currentData()
        body_file, body_enc, eye_file = model_data

        params = {
            "length":              self._chk_length.isChecked(),
            "curvature":           self._chk_curvature.isChecked(),
            "ratio":               self._chk_ratio.isChecked(),
            "eyes":                self._chk_eyes.isChecked(),
            "hitl":                self._chk_hitl.isChecked(),
            "threshold":           self._threshold_slider.value,
            "um_per_px":           self._um_per_px.value,
            "body_model_filename": body_file,
            "body_encoder_name":   body_enc,
            "eye_model_filename":  eye_file,
        }

        def _progress_cb(i, n):
            self._progress.setValue(i)
            slicer.app.processEvents()

        self._results = analyse_images(self._image_paths, params, _progress_cb)
        self._progress.setVisible(False)
        self._on_results_ready()

    def _on_results_ready(self):
        errors = [r for r in self._results if r.get("error")]
        if errors:
            msg = "\n".join(f"• {r['filename']}: {r['error']}" for r in errors)
            slicer.util.warningDisplay(f"Errors in {len(errors)} image(s):\n\n{msg}")

    def _on_export_excel(self):
        if not self._results:
            return
        path, _ = qt.QFileDialog.getSaveFileName(None, "Save Excel", "", "Excel (*.xlsx)")
        if path:
            active = [r for r in self._results if r["filename"] not in self._excluded]
            export_excel(active, path)

    def _on_export_csv(self):
        if not self._results:
            return
        path, _ = qt.QFileDialog.getSaveFileName(None, "Save CSV", "", "CSV (*.csv)")
        if path:
            active = [r for r in self._results if r["filename"] not in self._excluded]
            export_csv(active, path)
