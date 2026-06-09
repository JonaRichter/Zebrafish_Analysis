"""
Check and install required packages into Slicer's bundled Python.

Usage (called once at extension startup):
    from ZebrafishAnalysisLib.dependency_installer import check_and_install
    check_and_install()  # no-op if everything already installed
"""

REQUIRED_PACKAGES = [
    "segmentation_models_pytorch",
    "timm",
    "scikit-image",
    "opencv-python-headless",
    "huggingface_hub",
    "openpyxl",
    "pytesseract",
]

TORCH_PACKAGES = ["torch", "torchvision"]
TORCH_INDEX    = "https://download.pytorch.org/whl/cpu"


def _is_importable(name: str) -> bool:
    import importlib.util
    import_name = {
        "scikit-image":                "skimage",
        "opencv-python-headless":      "cv2",
        "huggingface_hub":             "huggingface_hub",
        "segmentation_models_pytorch": "segmentation_models_pytorch",
    }.get(name, name)
    return importlib.util.find_spec(import_name) is not None


def _numpy_major() -> int:
    """Return installed numpy major version, or 0 on failure."""
    try:
        import numpy as np
        return int(np.__version__.split(".")[0])
    except Exception:
        return 0


def check_and_install(show_restart_message: bool = True) -> None:
    """Install missing dependencies via slicer.util.pip_install."""
    try:
        import slicer
    except ImportError:
        return  # running outside Slicer (e.g. unit tests) — skip

    needs_restart = False

    # torch 2.2 (latest CPU WHL for macOS) was compiled against NumPy 1.x C API;
    # downgrade numpy before touching torch so the bridge works after restart.
    if _numpy_major() >= 2:
        slicer.util.showStatusMessage("Downgrading NumPy for torch compatibility…")
        slicer.util.pip_install("\"numpy<2\"")
        needs_restart = True

    missing_torch   = [p for p in TORCH_PACKAGES    if not _is_importable(p)]
    missing_general = [p for p in REQUIRED_PACKAGES if not _is_importable(p)]

    if missing_torch:
        slicer.util.showStatusMessage("Installing PyTorch…")
        slicer.util.pip_install(
            "torch torchvision --index-url " + TORCH_INDEX
        )
        needs_restart = True

    for pkg in missing_general:
        slicer.util.showStatusMessage(f"Installing {pkg}…")
        slicer.util.pip_install(pkg)
        needs_restart = True

    if needs_restart:
        slicer.util.showStatusMessage("Dependencies installed — restart required.")
        if show_restart_message:
            slicer.util.messageBox(
                "Required packages have been installed.\n"
                "Please restart 3D Slicer to complete setup."
            )
    else:
        slicer.util.showStatusMessage("Dependencies OK.")
