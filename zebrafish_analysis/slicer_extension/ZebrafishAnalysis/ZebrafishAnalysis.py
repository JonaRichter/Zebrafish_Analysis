import os
import sys
import importlib

import qt
import ctk
import slicer
from slicer.ScriptedLoadableModule import *
from slicer.util import VTKObservationMixin


# ---------------------------------------------------------------------------
# Module descriptor
# ---------------------------------------------------------------------------

class ZebrafishAnalysis(ScriptedLoadableModule):
    def __init__(self, parent):
        ScriptedLoadableModule.__init__(self, parent)
        self.parent.title = "Zebrafish Analysis"
        self.parent.categories = ["Quantification"]
        self.parent.dependencies = []
        self.parent.contributors = ["Jona Richter", "Mark Daniel Arndt"]
        self.parent.helpText = (
            "Segment zebrafish from 2-D microscopy images and measure body length, "
            "curvature class, length/straight-line ratio, and eye metrics."
        )
        self.parent.acknowledgementText = (
            "Based on the Zebrafish Webapp (github.com/MarkDanielArndt/Zebrafish_webapp)."
        )


# ---------------------------------------------------------------------------
# Helpers (module-level so they can be called without a widget instance)
# ---------------------------------------------------------------------------

def _numpy_to_qpixmap(arr):
    """Convert a H×W×3 uint8 RGB numpy array to a QPixmap via PNG bytes."""
    import numpy as np
    from PIL import Image as PILImage
    import io
    arr = np.ascontiguousarray(arr.clip(0, 255).astype("uint8"))
    if arr.ndim == 2:
        arr = np.stack([arr] * 3, axis=-1)
    buf = io.BytesIO()
    PILImage.fromarray(arr).save(buf, format="PNG")
    buf.seek(0)
    pm = qt.QPixmap()
    pm.loadFromData(buf.read())
    return pm


def _make_overlay(result):
    """
    Compose original image + body mask (yellow) + eye mask (red) +
    centerline (cyan) + straight-line (magenta) into a single H×W×3 array.
    """
    import numpy as np
    import cv2

    original = result.get("original")
    mask     = result.get("mask")
    if original is None or mask is None:
        return None

    base = original.copy().astype(np.float32)
    if base.ndim == 2:
        base = np.stack([base] * 3, axis=-1)

    # scale mask to base resolution if needed
    h_base, w_base = base.shape[:2]
    h_mask, w_mask = mask.shape[:2]

    def _resize_mask(m):
        if m.shape[:2] != (h_base, w_base):
            m = cv2.resize(m.astype(np.uint8), (w_base, h_base),
                           interpolation=cv2.INTER_NEAREST)
        return m

    # body mask → yellow at 45 % opacity
    mask_r = _resize_mask(mask)
    m = (mask_r > 0)[..., None].astype(np.float32)
    yellow = np.zeros_like(base); yellow[..., :2] = 255
    base = base * (1 - 0.45 * m) + yellow * (0.45 * m)

    # eye mask → red at 35 % opacity
    eye_mask = result.get("eye_mask")
    if eye_mask is not None:
        eye_r = _resize_mask(eye_mask)
        em = (eye_r > 0)[..., None].astype(np.float32)
        red = np.zeros_like(base); red[..., 0] = 255
        base = base * (1 - 0.35 * em) + red * (0.35 * em)

    overlay = base.clip(0, 255).astype(np.uint8)

    sx = w_base / float(max(1, w_mask))
    sy = h_base / float(max(1, h_mask))

    # centerline → cyan
    path_pts = result.get("path_points")
    if path_pts is not None:
        try:
            import numpy as np
            p = np.asarray(path_pts)
            if p.ndim == 2 and p.shape[1] == 2 and len(p) >= 2:
                pts = np.stack([
                    np.clip(np.round(p[:, 1] * sx), 0, w_base - 1),
                    np.clip(np.round(p[:, 0] * sy), 0, h_base - 1),
                ], axis=1).astype(np.int32)
                cv2.polylines(overlay, [pts], False, (0, 0, 0),    6, cv2.LINE_AA)
                cv2.polylines(overlay, [pts], False, (0, 255, 255), 3, cv2.LINE_AA)
        except Exception:
            pass

    # straight line → magenta
    sl_pts = result.get("straight_line_points")
    if sl_pts is not None:
        try:
            (r1, c1), (r2, c2) = sl_pts
            p1 = (int(np.clip(round(c1 * sx), 0, w_base - 1)),
                  int(np.clip(round(r1 * sy), 0, h_base - 1)))
            p2 = (int(np.clip(round(c2 * sx), 0, w_base - 1)),
                  int(np.clip(round(r2 * sy), 0, h_base - 1)))
            cv2.line(overlay, p1, p2, (0,   0,   0), 6, cv2.LINE_AA)
            cv2.line(overlay, p1, p2, (255, 0, 255), 3, cv2.LINE_AA)
        except Exception:
            pass

    return overlay


# ---------------------------------------------------------------------------
# Widget (UI)
# ---------------------------------------------------------------------------

class ZebrafishAnalysisWidget(ScriptedLoadableModuleWidget, VTKObservationMixin):

    MASK_ALPHA    = 0.45
    OVERLAY_COLOR = (0, 255, 255)   # cyan for centerline

    def __init__(self, parent=None):
        ScriptedLoadableModuleWidget.__init__(self, parent)
        VTKObservationMixin.__init__(self)
        self.logic          = None
        self._sceneNodeIDs  = []   # MRML node IDs owned by this widget
        self._currentPixmap = None # keep reference to avoid GC

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def setup(self):
        ScriptedLoadableModuleWidget.setup(self)
        self._checkAndInstallDependencies()
        self.logic = ZebrafishAnalysisLogic()
        self._buildUI()
        self._connectSignals()

    def cleanup(self):
        self.removeObservers()
        self._clearSceneNodes()

    # ------------------------------------------------------------------
    # Dependency installer
    # ------------------------------------------------------------------

    def _checkAndInstallDependencies(self):
        required = [
            ("torch",                      None),
            ("torchvision",                None),
            ("segmentation_models_pytorch", "segmentation-models-pytorch"),
            ("timm",                       "timm"),
            ("skimage",                    "scikit-image"),
            ("cv2",                        "opencv-python-headless"),
            ("huggingface_hub",            "huggingface_hub"),
            ("openpyxl",                   "openpyxl"),
            ("PIL",                        "pillow"),
        ]

        missing_general = []
        need_torch      = False

        for mod_name, pip_name in required:
            if importlib.util.find_spec(mod_name) is None:
                if mod_name in ("torch", "torchvision"):
                    need_torch = True
                else:
                    missing_general.append(pip_name or mod_name)

        if not need_torch and not missing_general:
            return

        slicer.util.showStatusMessage(
            "Zebrafish Analysis: installing missing dependencies…"
        )

        if need_torch:
            slicer.util.pip_install(
                "torch torchvision "
                "--index-url https://download.pytorch.org/whl/cpu"
            )

        for pkg in missing_general:
            slicer.util.pip_install(pkg)

        slicer.util.showStatusMessage("Dependencies installed.")
        slicer.util.messageBox(
            "Required packages have been installed.\n"
            "Please restart 3D Slicer to complete the setup."
        )

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _buildUI(self):
        layout = self.layout

        # top-level splitter: left panel | right viewer
        splitter = qt.QSplitter(qt.Qt.Horizontal)
        splitter.setChildrenCollapsible(False)
        layout.addWidget(splitter)

        # ── LEFT PANEL ──────────────────────────────────────────────
        leftWidget = qt.QWidget()
        leftWidget.setFixedWidth(275)
        leftLayout = qt.QVBoxLayout(leftWidget)
        leftLayout.setContentsMargins(4, 4, 4, 4)
        leftLayout.setSpacing(6)
        splitter.addWidget(leftWidget)

        # INPUT
        inputBox = ctk.ctkCollapsibleButton()
        inputBox.text = "Input"
        leftLayout.addWidget(inputBox)
        inputLayout = qt.QVBoxLayout(inputBox)

        self.loadFolderButton = qt.QPushButton("Load Folder…")
        self.loadFilesButton  = qt.QPushButton("Load Images…")
        inputLayout.addWidget(self.loadFolderButton)
        inputLayout.addWidget(self.loadFilesButton)

        inputLayout.addWidget(qt.QLabel("Queue:"))
        self.queueList = qt.QListWidget()
        self.queueList.setMaximumHeight(140)
        inputLayout.addWidget(self.queueList)

        # ANALYSIS
        analysisBox = ctk.ctkCollapsibleButton()
        analysisBox.text = "Analysis"
        leftLayout.addWidget(analysisBox)
        analysisLayout = qt.QVBoxLayout(analysisBox)

        self.chkLength    = qt.QCheckBox("Body length")
        self.chkCurvature = qt.QCheckBox("Curvature class")
        self.chkRatio     = qt.QCheckBox("Length / straight-line ratio")
        self.chkEyes      = qt.QCheckBox("Eye segmentation")
        self.chkHitL      = qt.QCheckBox("Human-in-the-loop (confidence)")
        for chk in (self.chkLength, self.chkCurvature, self.chkRatio, self.chkHitL):
            chk.setChecked(True)
            analysisLayout.addWidget(chk)
        self.chkEyes.setChecked(False)
        analysisLayout.addWidget(self.chkEyes)

        analysisLayout.addWidget(qt.QLabel("Confidence threshold:"))
        self.confidenceSlider = ctk.ctkSliderWidget()
        self.confidenceSlider.minimum    = 0.0
        self.confidenceSlider.maximum    = 1.0
        self.confidenceSlider.singleStep = 0.01
        self.confidenceSlider.value      = 0.85
        self.confidenceSlider.decimals   = 2
        analysisLayout.addWidget(self.confidenceSlider)

        # MODEL
        modelBox = ctk.ctkCollapsibleButton()
        modelBox.text      = "Model"
        modelBox.collapsed = True
        leftLayout.addWidget(modelBox)
        modelLayout = qt.QFormLayout(modelBox)

        self.modelCombo = qt.QComboBox()
        self.modelCombo.addItem("General Model",     ("best_model_body_3400_vgg19.pth", "vgg19", None))
        self.modelCombo.addItem("Fine-tuned DESY",   ("best_model_body_finetuned.pth",  "vgg19", "best_model_eye_finetuned.pth"))
        modelLayout.addRow("Segmentation model:", self.modelCombo)

        # SCALE BAR
        scaleBox = ctk.ctkCollapsibleButton()
        scaleBox.text      = "Scale bar"
        scaleBox.collapsed = True
        leftLayout.addWidget(scaleBox)
        scaleLayout = qt.QFormLayout(scaleBox)

        self.umPerPixelSpinBox = ctk.ctkDoubleSpinBox()
        self.umPerPixelSpinBox.minimum    = 0.001
        self.umPerPixelSpinBox.maximum    = 9999.0
        self.umPerPixelSpinBox.singleStep = 0.1
        self.umPerPixelSpinBox.value      = 22.99   # 5885 µm / 256 px
        self.umPerPixelSpinBox.decimals   = 4
        self.umPerPixelSpinBox.suffix     = " µm/px"
        scaleLayout.addRow("µm per pixel:", self.umPerPixelSpinBox)

        # RUN
        self.runButton = qt.QPushButton("▶  Run Analysis")
        self.runButton.setStyleSheet("font-weight: bold; padding: 6px;")
        leftLayout.addWidget(self.runButton)

        # EXPORT
        exportBox = ctk.ctkCollapsibleButton()
        exportBox.text = "Export"
        leftLayout.addWidget(exportBox)
        exportLayout = qt.QHBoxLayout(exportBox)
        self.exportExcelButton = qt.QPushButton("Excel")
        self.exportCsvButton   = qt.QPushButton("CSV")
        exportLayout.addWidget(self.exportExcelButton)
        exportLayout.addWidget(self.exportCsvButton)

        leftLayout.addStretch()

        # ── RIGHT PANEL ─────────────────────────────────────────────
        self.tabs = qt.QTabWidget()
        splitter.addWidget(self.tabs)
        splitter.setStretchFactor(1, 1)

        # Tab 1 – Viewer
        viewerWidget = qt.QWidget()
        viewerLayout = qt.QVBoxLayout(viewerWidget)

        self.imageLabel = qt.QLabel("No image loaded.")
        self.imageLabel.setAlignment(qt.Qt.AlignCenter)
        self.imageLabel.setStyleSheet("background: #1a1a1a; color: #666;")
        self.imageLabel.setMinimumHeight(300)
        self.imageLabel.setSizePolicy(qt.QSizePolicy.Expanding, qt.QSizePolicy.Expanding)
        self.imageLabel.setScaledContents(False)
        viewerLayout.addWidget(self.imageLabel, stretch=3)

        resultsBox = ctk.ctkCollapsibleButton()
        resultsBox.text = "Measurements"
        viewerLayout.addWidget(resultsBox, stretch=0)
        resLayout = qt.QVBoxLayout(resultsBox)
        self.resultsLabel = qt.QLabel("—")
        self.resultsLabel.setWordWrap(True)
        resLayout.addWidget(self.resultsLabel)

        self.tabs.addTab(viewerWidget, "Viewer")

        # Tab 2 – Exclude
        excludeWidget = qt.QWidget()
        excludeLayout = qt.QVBoxLayout(excludeWidget)
        self.excludeTable = qt.QTableWidget(0, 2)
        self.excludeTable.setHorizontalHeaderLabels(["Filename", "Exclude"])
        self.excludeTable.horizontalHeader().setSectionResizeMode(
            0, qt.QHeaderView.Stretch
        )
        excludeLayout.addWidget(self.excludeTable)
        self.tabs.addTab(excludeWidget, "Exclude")

        # Progress bar (hidden until run starts)
        self.progressBar = qt.QProgressBar()
        self.progressBar.setVisible(False)
        layout.addWidget(self.progressBar)

    # ------------------------------------------------------------------
    # Signal wiring
    # ------------------------------------------------------------------

    def _connectSignals(self):
        self.loadFolderButton.clicked.connect(self._onLoadFolder)
        self.loadFilesButton.clicked.connect(self._onLoadFiles)
        self.runButton.clicked.connect(self._onRun)
        self.exportExcelButton.clicked.connect(self._onExportExcel)
        self.exportCsvButton.clicked.connect(self._onExportCsv)
        self.queueList.currentRowChanged.connect(self._onQueueRowChanged)

    # ------------------------------------------------------------------
    # Input handlers
    # ------------------------------------------------------------------

    def _onLoadFolder(self):
        folder = qt.QFileDialog.getExistingDirectory(
            slicer.util.mainWindow(), "Select image folder"
        )
        if folder:
            self.logic.setImageFolder(folder)
            self._populateQueue(self.logic.imagePaths)

    def _onLoadFiles(self):
        paths, _ = qt.QFileDialog.getOpenFileNames(
            slicer.util.mainWindow(),
            "Select images",
            "",
            "Images (*.tif *.tiff *.png *.jpg *.jpeg *.bmp)",
        )
        if paths:
            self.logic.setImageFiles(list(paths))
            self._populateQueue(self.logic.imagePaths)

    def _populateQueue(self, paths):
        self.queueList.clear()
        self.excludeTable.setRowCount(0)
        for i, p in enumerate(paths):
            bn = os.path.basename(p)
            self.queueList.addItem(bn)
            self.excludeTable.insertRow(i)
            self.excludeTable.setItem(i, 0, qt.QTableWidgetItem(bn))
            chk = qt.QCheckBox()
            self.excludeTable.setCellWidget(i, 1, chk)

    # ------------------------------------------------------------------
    # Run
    # ------------------------------------------------------------------

    def _onRun(self):
        if not self.logic.imagePaths:
            slicer.util.messageBox("Please load images first.")
            return

        body_fn, body_enc, eye_fn = self.modelCombo.currentData()
        params = {
            "length":               self.chkLength.isChecked(),
            "curvature":            self.chkCurvature.isChecked(),
            "ratio":                self.chkRatio.isChecked(),
            "eyes":                 self.chkEyes.isChecked(),
            "hitl":                 self.chkHitL.isChecked(),
            "threshold":            self.confidenceSlider.value,
            "um_per_px":            self.umPerPixelSpinBox.value,
            "body_model_filename":  body_fn,
            "body_encoder_name":    body_enc,
            "eye_model_filename":   eye_fn or "best_model_eye_3400.pth",
        }

        self.runButton.setEnabled(False)
        self.progressBar.setRange(0, len(self.logic.imagePaths))
        self.progressBar.setValue(0)
        self.progressBar.setVisible(True)

        try:
            self.logic.run(params, progressCallback=self._onProgress)
        finally:
            self.progressBar.setVisible(False)
            self.runButton.setEnabled(True)

        # show first result
        if self.logic.results:
            self.queueList.setCurrentRow(0)

    def _onProgress(self, current, total):
        self.progressBar.setValue(current)
        slicer.app.processEvents()

    # ------------------------------------------------------------------
    # Queue navigation → display
    # ------------------------------------------------------------------

    def _onQueueRowChanged(self, row):
        if row < 0 or not self.logic.results:
            return
        if row < len(self.logic.results):
            self._displayResult(row)

    def _displayResult(self, index):
        result = self.logic.results[index]

        # 1. Composite overlay in the panel
        overlay = _make_overlay(result)
        if overlay is not None:
            self._showOverlay(overlay)

        # 2. Update measurements text
        self._updateResultsText(result)

        # 3. Load into Slicer scene
        self._loadIntoSlicerScene(result)

    def _showOverlay(self, arr):
        """Scale overlay array to fit the label and display as QPixmap."""
        pm = _numpy_to_qpixmap(arr)
        self._currentPixmap = pm   # keep reference

        w = self.imageLabel.width()
        h = self.imageLabel.height()
        if w > 0 and h > 0:
            scaled = pm.scaled(w, h, qt.Qt.KeepAspectRatio, qt.Qt.SmoothTransformation)
        else:
            scaled = pm

        self.imageLabel.setText("")
        self.imageLabel.setPixmap(scaled)

    def _updateResultsText(self, result):
        parts = []
        if result.get("length")     is not None:
            parts.append(f"Length:     {result['length']:.1f} µm")
        if result.get("curvature")  is not None:
            cls = result["curvature"]
            parts.append(f"Curvature:  Class {cls if cls != 5 else 'N/A'}")
        if result.get("ratio")      is not None:
            parts.append(f"Ratio:      {result['ratio']:.3f}")
        if result.get("eye_area")   is not None:
            parts.append(f"Eye area:   {result['eye_area']:.1f} µm²")
        if result.get("eye_diameter") is not None:
            parts.append(f"Eye ⌀:      {result['eye_diameter']:.1f} µm")
        self.resultsLabel.setText("\n".join(parts) if parts else "No measurements.")

    # ------------------------------------------------------------------
    # Slicer scene integration (Step 6)
    # ------------------------------------------------------------------

    def _clearSceneNodes(self):
        for nodeID in self._sceneNodeIDs:
            node = slicer.mrmlScene.GetNodeByID(nodeID)
            if node:
                slicer.mrmlScene.RemoveNode(node)
        self._sceneNodeIDs = []

    def _loadIntoSlicerScene(self, result):
        """
        Load the current image as a Slicer volume, overlay the body mask as
        a label map, and display the centerline as a Markup Curve.
        """
        import numpy as np
        import vtk

        self._clearSceneNodes()

        image_path = result.get("image_path")
        if not image_path or not os.path.isfile(image_path):
            return

        # ---- background volume ----
        try:
            volumeNode = slicer.util.loadVolume(image_path, {"singleFile": True})
        except Exception as exc:
            print(f"Could not load volume {image_path}: {exc}")
            return
        self._sceneNodeIDs.append(volumeNode.GetID())
        slicer.util.setSliceViewerLayers(background=volumeNode, fit=True)

        # ---- body mask as label map ----
        mask = result.get("mask")
        if mask is not None:
            try:
                # Slicer volumes are indexed as (K, J, I) = (Z, Y, X)
                # A 2D image loaded as volume has shape (1, H, W) in IJK
                mask_arr = mask.astype(np.int16)[np.newaxis, :, :]
                labelNode = slicer.util.addVolumeFromArray(
                    mask_arr,
                    nodeClassName="vtkMRMLLabelMapVolumeNode",
                )
                labelNode.SetName("ZF_Mask")
                # copy geometry so mask aligns with the volume
                ijkToRas = vtk.vtkMatrix4x4()
                volumeNode.GetIJKToRASMatrix(ijkToRas)
                labelNode.SetIJKToRASMatrix(ijkToRas)
                self._sceneNodeIDs.append(labelNode.GetID())
                slicer.util.setSliceViewerLayers(label=labelNode)
            except Exception as exc:
                print(f"Could not create label map: {exc}")

        # ---- centerline as Markup Curve ----
        path_pts = result.get("path_points")
        if path_pts is not None:
            try:
                import numpy as np
                curveNode = slicer.mrmlScene.AddNewNodeByClass(
                    "vtkMRMLMarkupsCurveNode", "ZF_Centerline"
                )
                curveNode.GetDisplayNode().SetSelectedColor(0, 1, 1)   # cyan
                curveNode.GetDisplayNode().SetGlyphScale(0)             # hide control-point glyphs

                ijkToRas = vtk.vtkMatrix4x4()
                volumeNode.GetIJKToRASMatrix(ijkToRas)

                pts = np.asarray(path_pts)
                # downsample to ≤ 80 control points for performance
                step = max(1, len(pts) // 80)
                for row, col in pts[::step]:
                    ijk = [float(col), float(row), 0.0, 1.0]
                    ras = ijkToRas.MultiplyPoint(ijk)
                    curveNode.AddControlPoint(ras[0], ras[1], ras[2])

                self._sceneNodeIDs.append(curveNode.GetID())
            except Exception as exc:
                print(f"Could not create centerline markup: {exc}")

        # fit slice views
        slicer.util.resetSliceViews()

    # ------------------------------------------------------------------
    # Export
    # ------------------------------------------------------------------

    def _excludedIndices(self):
        excluded = set()
        for i in range(self.excludeTable.rowCount()):
            chk = self.excludeTable.cellWidget(i, 1)
            if chk and chk.isChecked():
                excluded.add(i)
        return excluded

    def _onExportExcel(self):
        if not self.logic.results:
            slicer.util.messageBox("No results to export. Run the analysis first.")
            return
        path, _ = qt.QFileDialog.getSaveFileName(
            slicer.util.mainWindow(), "Save Excel",
            "zebrafish_results.xlsx", "Excel (*.xlsx)"
        )
        if path:
            excluded = self._excludedIndices()
            results  = [r for i, r in enumerate(self.logic.results)
                        if i not in excluded]
            self.logic.exportExcel(results, path)

    def _onExportCsv(self):
        if not self.logic.results:
            slicer.util.messageBox("No results to export. Run the analysis first.")
            return
        path, _ = qt.QFileDialog.getSaveFileName(
            slicer.util.mainWindow(), "Save CSV",
            "zebrafish_results.csv", "CSV (*.csv)"
        )
        if path:
            excluded = self._excludedIndices()
            results  = [r for i, r in enumerate(self.logic.results)
                        if i not in excluded]
            self.logic.exportCsv(results, path)


# ---------------------------------------------------------------------------
# Logic
# ---------------------------------------------------------------------------

class ZebrafishAnalysisLogic(ScriptedLoadableModuleLogic):

    def __init__(self):
        ScriptedLoadableModuleLogic.__init__(self)
        self.imagePaths = []
        self.results    = []

    def setImageFolder(self, folder):
        exts = {".tif", ".tiff", ".png", ".jpg", ".jpeg", ".bmp"}
        self.imagePaths = sorted(
            os.path.join(folder, f)
            for f in os.listdir(folder)
            if os.path.splitext(f)[1].lower() in exts
        )
        self.results = []

    def setImageFiles(self, paths):
        self.imagePaths = list(paths)
        self.results    = []

    def run(self, params, progressCallback=None):
        from ZebrafishAnalysisLib.logic import analyse_images
        self.results = analyse_images(
            self.imagePaths, params, progressCallback=progressCallback
        )

    def exportExcel(self, results, path):
        from ZebrafishAnalysisLib.logic import export_excel
        export_excel(results, path)

    def exportCsv(self, results, path):
        from ZebrafishAnalysisLib.logic import export_csv
        export_csv(results, path)


# ---------------------------------------------------------------------------
# Test stub
# ---------------------------------------------------------------------------

class ZebrafishAnalysisTest(ScriptedLoadableModuleTest):
    def setUp(self):
        slicer.mrmlScene.Clear()

    def runTest(self):
        self.setUp()
        self.test_placeholder()

    def test_placeholder(self):
        self.delayDisplay("ZebrafishAnalysis: placeholder test passed.")
