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
]

TORCH_PACKAGES = ["torch", "torchvision"]
TORCH_INDEX    = "https://download.pytorch.org/whl/cpu"


def _is_importable(name: str) -> bool:
    import importlib
    import_name = {
        "scikit-image":                "skimage",
        "opencv-python-headless":      "cv2",
        "huggingface_hub":             "huggingface_hub",
        "segmentation_models_pytorch": "segmentation_models_pytorch",
    }.get(name, name)
    try:
        importlib.import_module(import_name)
        return True
    except ImportError:
        return False


def check_and_install(show_restart_message: bool = True) -> None:
    """Install missing dependencies via slicer.util.pip_install."""
    try:
        import slicer
    except ImportError:
        return  # running outside Slicer (e.g. unit tests) — skip

    missing_torch   = [p for p in TORCH_PACKAGES    if not _is_importable(p)]
    missing_general = [p for p in REQUIRED_PACKAGES if not _is_importable(p)]

    if not missing_torch and not missing_general:
        return

    slicer.util.showStatusMessage("Installing dependencies…")

    if missing_torch:
        slicer.util.pip_install(
            "torch torchvision --index-url " + TORCH_INDEX
        )

    for pkg in missing_general:
        slicer.util.pip_install(pkg)

    slicer.util.showStatusMessage("Dependencies installed.")

    if show_restart_message:
        slicer.util.messageBox(
            "Required packages have been installed.\n"
            "Please restart 3D Slicer to complete setup."
        )
