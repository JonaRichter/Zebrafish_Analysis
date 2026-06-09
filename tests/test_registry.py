from zebrafish_analysis.core.models.registry import MODEL_REGISTRY, MODEL_PRESETS, get_model_config


def test_required_models_present():
    assert "segmentation_vgg19" in MODEL_REGISTRY
    assert "curvature_classifier" in MODEL_REGISTRY
    assert "eye_segmentation" in MODEL_REGISTRY


def test_model_config_has_required_keys():
    cfg = get_model_config("segmentation_vgg19")
    assert "repo" in cfg
    assert "filename" in cfg
    assert "encoder" in cfg


def test_unknown_model_raises():
    import pytest
    with pytest.raises(KeyError):
        get_model_config("nonexistent_model")


def test_presets_reference_valid_models():
    for preset_name, preset in MODEL_PRESETS.items():
        assert "body" in preset
        assert preset["body"] in MODEL_REGISTRY
