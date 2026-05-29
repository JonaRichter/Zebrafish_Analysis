"""
Logic layer for the ZebrafishAnalysis Slicer extension.

Wraps core/ functions and provides a clean public API:
  - analyse_images()   — batch segmentation + measurements
  - detect_scalebar()  — thin wrapper around core scalebar

Path setup (sys.path) is handled by ZebrafishAnalysis.py, not here.
Export functions (export_excel, export_csv) live in export.py.
"""

import os
import tempfile
import numpy as np  # must precede torch imports to enable the numpy bridge
import cv2

from zebrafish_analysis.core.scalebar import detect_scalebar as _detect_scalebar

_MODEL_CACHE: dict = {}

# ---------------------------------------------------------------------------
# Result dict schema — every key must be present, missing values use None
# ---------------------------------------------------------------------------
_RESULT_KEYS = (
    "filename",
    "image_path",
    "original",
    "mask",
    "grown",
    "eye_mask",
    "path_points",
    "straight_line_points",
    "length",
    "curvature",
    "ratio",
    "eye_area",
    "eye_diameter",
    "spacing",
    "error",
)


def _empty_result(image_path: str) -> dict:
    r = {k: None for k in _RESULT_KEYS}
    r["filename"] = os.path.basename(image_path)
    r["image_path"] = image_path
    return r


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def detect_scalebar(image_path: str, label_um: float | None = None) -> dict:
    """
    Detect scale bar in an image file.

    Returns the dict produced by core detect_scalebar, or a failure dict
    if the image cannot be read.
    """
    img_bgr = cv2.imread(image_path)
    if img_bgr is None:
        return {"success": False, "bar_found": False,
                "message": "Could not read image."}
    img_rgb = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2RGB)
    return _detect_scalebar(img_rgb, label_um=label_um)


def analyse_images(image_paths: list, params: dict,
                   progress_callback=None) -> list:
    """
    Run segmentation + measurements on a list of image paths.

    Parameters
    ----------
    image_paths : list[str]
        Absolute paths to input images. Must be sorted before calling.
    params : dict
        Keys:
          length, curvature, ratio, eyes : bool
          hitl                           : bool  — use confidence threshold
          threshold                      : float 0–1
          um_per_px                      : float — physical scale (µm/pixel)
          body_model_filename            : str   — HF filename for body U-Net
          body_encoder_name              : str   — encoder (vgg16 / vgg19)
          eye_model_filename             : str   — HF filename for eye U-Net
          body_force_download            : bool  — force re-download of body model
    progress_callback : callable(current, total) | None

    Returns
    -------
    list[dict]
        One result dict per image. Every dict contains all keys from the
        schema. On per-image errors the numeric fields are None and
        ``error`` holds the exception message.
    """
    from zebrafish_analysis.core.seg import segmentation_pipeline
    from zebrafish_analysis.core.length import (
        load_model,
        tube_length_border2border,
        classification_curvature,
        compute_eye_metrics,
    )

    um_per_px = float(params.get("um_per_px", 22.99))
    include_eyes = params.get("eyes", False)
    body_filename = params.get("body_model_filename",
                               "best_model_body_3400_vgg19.pth")
    body_encoder = params.get("body_encoder_name", "vgg19")
    eye_filename = params.get("eye_model_filename", "best_model_eye_3400.pth")
    force_download = params.get("body_force_download", False)

    # ---- load curvature model once (cached across calls) ----
    if params.get("curvature", True):
        if "curvature" not in _MODEL_CACHE:
            _MODEL_CACHE["curvature"] = load_model()
        curv_model = _MODEL_CACHE["curvature"]
    else:
        curv_model = None

    # ---- segmentation (all images at once) ----
    # segmentation_pipeline takes a folder_path; symlink selected files into a temp dir
    _IMG_EXTS = ('.png', '.jpg', '.jpeg', '.bmp', '.tiff', '.tif')
    with tempfile.TemporaryDirectory() as _tmp:
        name_to_path: dict = {}
        for p in image_paths:
            name = os.path.basename(p)
            if name in name_to_path:
                raise ValueError(f"Duplicate filename '{name}' in image list.")
            name_to_path[name] = p
            os.symlink(p, os.path.join(_tmp, name))

        _seg_kwargs = dict(
            include_eyes=include_eyes,
            body_model_filename=body_filename,
            body_encoder_name=body_encoder,
            body_force_download=force_download,
        )
        if include_eyes and eye_filename:
            _seg_kwargs["eye_model_filename"] = eye_filename
        seg_result = segmentation_pipeline(_tmp, **_seg_kwargs)

        # capture order before temp dir is cleaned up (mirrors load_images_from_path)
        _ordered_names = [
            f for f in os.listdir(_tmp)
            if f.lower().endswith(_IMG_EXTS)
        ]

    name_to_seg_idx = {name: idx for idx, name in enumerate(_ordered_names)}

    if include_eyes and len(seg_result) == 4:
        originals_bgr, masks, growns, eyes = seg_result
    else:
        originals_bgr, masks, growns = seg_result[:3]
        eyes = [None] * len(image_paths)

    n = len(image_paths)
    results = []

    for _loop_i, image_path in enumerate(sorted(image_paths)):
        if progress_callback:
            progress_callback(_loop_i, n)

        r = _empty_result(image_path)

        try:
            _name = os.path.basename(image_path)
            i = name_to_seg_idx.get(_name)
            if i is None:
                r["error"] = f"Segmentation result not found for {_name}."
                results.append(r)
                continue

            orig_bgr = originals_bgr[i]
            if orig_bgr is None:
                r["error"] = "Could not read image."
                results.append(r)
                continue

            # seg.py returns BGR — convert to RGB for storage
            r["original"] = cv2.cvtColor(orig_bgr, cv2.COLOR_BGR2RGB)
            r["mask"] = masks[i]
            r["grown"] = growns[i]
            r["eye_mask"] = eyes[i]

            mask_bin = (masks[i] > 0) if masks[i] is not None else None
            eye_bin = (eyes[i] > 0) if eyes[i] is not None else None

            # spacing: mask is 256×256, original may be larger
            h_orig, w_orig = orig_bgr.shape[:2]
            mask_h, mask_w = masks[i].shape[:2] if masks[i] is not None else (256, 256)
            spacing = (
                um_per_px * h_orig / mask_h,
                um_per_px * w_orig / mask_w,
            )
            r["spacing"] = spacing

            # ---- length + ratio ----
            if params.get("length", True) and mask_bin is not None:
                try:
                    length, straight, path_pts, sl_pts = tube_length_border2border(
                        mask_bin,
                        spacing=spacing,
                        return_path=True,
                        return_straight_line=True,
                        mask_eye=eye_bin,
                        return_eye_info=False,
                    )
                    r["length"] = float(length)
                    r["path_points"] = path_pts
                    r["straight_line_points"] = sl_pts
                    if params.get("ratio", True) and straight and straight > 0:
                        r["ratio"] = float(length) / float(straight)
                except Exception as exc:
                    r["error"] = f"Length error: {exc}"

            # ---- curvature ----
            if params.get("curvature", True) and curv_model is not None:
                try:
                    use_thr = params.get("hitl", False)
                    thr = float(params.get("threshold", 0.85))
                    _, cls = classification_curvature(
                        r["original"], r["grown"], curv_model, use_thr, thr
                    )
                    r["curvature"] = int(cls.item())
                except Exception as exc:
                    # do not overwrite an existing error from length
                    if r["error"] is None:
                        r["error"] = f"Curvature error: {exc}"

            # ---- eye metrics ----
            if params.get("eyes", False) and eye_bin is not None and mask_bin is not None:
                try:
                    info = compute_eye_metrics(
                        eye_bin, mask_fish=mask_bin, spacing=spacing
                    )
                    r["eye_area"] = float(info.get("eye_area", 0))
                    r["eye_diameter"] = float(info.get("eye_diameter", 0))
                except Exception as exc:
                    if r["error"] is None:
                        r["error"] = f"Eye metrics error: {exc}"

        except Exception as exc:
            import traceback
            r["error"] = f"Unhandled error: {exc}\n{traceback.format_exc()}"

        results.append(r)

    if progress_callback:
        progress_callback(n, n)

    return results


# ---------------------------------------------------------------------------
# Manual correction
# ---------------------------------------------------------------------------

def apply_manual_correction(result, point1_orig, point2_orig, params=None):
    """
    Recompute length, ratio, and curvature from manually placed head/tail points.

    Parameters
    ----------
    result : dict
        Result dict (mutated in-place).  Must contain 'mask', 'original', 'spacing'.
    point1_orig, point2_orig : tuple
        (row, col) in original image coordinate space (as clicked on the display).
    params : dict | None
        Optional keys: 'hitl' (bool), 'threshold' (float).
        Used for curvature re-classification.  Defaults to hitl=False, threshold=0.85.

    Returns
    -------
    result : dict
        The same dict, updated in-place.
    """
    if params is None:
        params = {}

    spacing = result.get("spacing")
    if spacing is None:
        print("apply_manual_correction: spacing is None — skipping (fish had an error?)")
        return result

    mask = result.get("mask")
    original = result.get("original")
    if mask is None or original is None:
        print("apply_manual_correction: mask or original missing — skipping")
        return result

    from zebrafish_analysis.core.manual import compute_manual_length
    from zebrafish_analysis.core.length import classification_curvature

    # Snapshot auto values on first correction only
    if "_auto_length" not in result:
        result["_auto_length"] = result.get("length")
        result["_auto_ratio"] = result.get("ratio")
        result["_auto_path_points"] = result.get("path_points")
        result["_auto_straight_line_points"] = result.get("straight_line_points")
        result["_auto_curvature"] = result.get("curvature")

    # Convert original-image coords → mask coords
    orig_h, orig_w = original.shape[:2]
    mask_h, mask_w = mask.shape[:2]
    scale_y = mask_h / orig_h
    scale_x = mask_w / orig_w

    point1_mask = (
        int(np.clip(point1_orig[0] * scale_y, 0, mask_h - 1)),
        int(np.clip(point1_orig[1] * scale_x, 0, mask_w - 1)),
    )
    point2_mask = (
        int(np.clip(point2_orig[0] * scale_y, 0, mask_h - 1)),
        int(np.clip(point2_orig[1] * scale_x, 0, mask_w - 1)),
    )

    # Recompute length + path
    length, straight_length, path_pts, sl_pts = compute_manual_length(
        mask, point1_mask, point2_mask, spacing
    )
    result["length"] = float(length)
    result["ratio"] = float(length / straight_length) if straight_length > 0 else None
    result["path_points"] = path_pts
    result["straight_line_points"] = sl_pts

    # Recompute curvature if model is loaded
    curv_model = _MODEL_CACHE.get("curvature")
    if curv_model is not None:
        try:
            use_thr = params.get("hitl", False)
            thr = float(params.get("threshold", 0.85))
            _, cls = classification_curvature(
                result["original"], result["grown"], curv_model, use_thr, thr
            )
            result["curvature"] = int(cls.item())
        except Exception as exc:
            print(f"apply_manual_correction: curvature recompute failed ({exc})")
    else:
        print("apply_manual_correction: curvature model not in cache — skipping")

    result["manual_corrected"] = True
    return result


def revert_manual_correction(result):
    """
    Restore auto-computed values saved before the first manual correction.
    No-op if result['manual_corrected'] is not set.

    Returns
    -------
    result : dict
        The same dict, updated in-place.
    """
    if not result.get("manual_corrected"):
        return result

    result["length"] = result.pop("_auto_length", result.get("length"))
    result["ratio"] = result.pop("_auto_ratio", result.get("ratio"))
    result["path_points"] = result.pop("_auto_path_points", result.get("path_points"))
    result["straight_line_points"] = result.pop(
        "_auto_straight_line_points", result.get("straight_line_points")
    )
    result["curvature"] = result.pop("_auto_curvature", result.get("curvature"))
    result.pop("manual_corrected", None)
    return result
