# NOTE: This registry is currently used by tests only (tests/test_registry.py).
# Production code (webapp/app.py, slicer_extension/logic.py) uses its own model
# configuration directly. The metadata below may be stale — do not rely on it
# for production model loading without verification.
#
# Known stale entries (as of 2026-06-08):
#   curvature_classifier: repo should be markdanielarndt/Classification,
#                         filename should be best_model_class.pth
#   eye_segmentation: encoder should be vgg16, not vgg19
MODEL_REGISTRY = {
    "segmentation_vgg19": {
        "repo":     "markdanielarndt/Zebrafish_Segmentation",
        "filename": "best_model_body_3400_vgg19.pth",
        "encoder":  "vgg19",
    },
    "curvature_classifier": {
        "repo":     "markdanielarndt/Zebrafish_Segmentation",
        "filename": "curvature_model.pth",
        "encoder":  None,
    },
    "eye_segmentation": {
        "repo":     "markdanielarndt/Zebrafish_Segmentation",
        "filename": "best_model_eye_3400.pth",
        "encoder":  "vgg19",
    },
}

MODEL_PRESETS = {
    "General Model": {
        "body": "segmentation_vgg19",
        "eye":  "eye_segmentation",
    },
}


def get_model_config(name: str) -> dict:
    return MODEL_REGISTRY[name]
