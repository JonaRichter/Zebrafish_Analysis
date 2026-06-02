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
