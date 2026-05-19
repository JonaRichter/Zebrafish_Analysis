"""
Logic layer for the ZebrafishAnalysis Slicer extension.

Processes images one-by-one (not via segmentation_pipeline) so that:
  - file → result ordering is guaranteed
  - per-image numpy arrays are available for overlay rendering
  - progress callbacks work correctly
"""

import os
import sys


def _ensure_core_on_path():
    here     = os.path.dirname(os.path.abspath(__file__))   # ZebrafishAnalysisLib/
    repo_root = os.path.dirname(                             # repo root
                os.path.dirname(                             # zebrafish_analysis/
                os.path.dirname(                             # slicer_extension/
                os.path.dirname(here))))                     # ZebrafishAnalysis/
    if repo_root not in sys.path:
        sys.path.insert(0, repo_root)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def analyse_images(image_paths, params, progressCallback=None):
    """
    Run segmentation + measurements on ordered list of image paths.

    params keys
    -----------
    length, curvature, ratio, eyes : bool
    hitl                           : bool  – use confidence threshold
    threshold                      : float 0–1
    um_per_px                      : float – physical scale (µm/pixel)
    body_model_filename            : str   – HF filename for body U-Net
    body_encoder_name              : str   – encoder (vgg16 / vgg19)
    eye_model_filename             : str   – HF filename for eye U-Net

    Each result dict contains
    -------------------------
    filename, image_path, original (H×W×3 RGB uint8),
    mask (H×W uint8), grown (H×W uint8), eye_mask (H×W uint8 | None),
    path_points (N×2 int | None), straight_line_points (2-tuple | None),
    length, curvature, ratio, eye_area, eye_diameter  (float | None)
    """
    _ensure_core_on_path()

    import cv2
    import numpy as np
    import torch

    from zebrafish_analysis.core.seg import _load_unet_model, target_size
    from zebrafish_analysis.core.seg_helper import segment_fish, fill_holes, grow_mask
    from zebrafish_analysis.core.length import (
        load_model,
        tube_length_border2border,
        classification_curvature,
        compute_eye_metrics,
    )

    body_filename  = params.get("body_model_filename", "best_model_body_3400_vgg19.pth")
    body_encoder   = params.get("body_encoder_name",  "vgg19")
    eye_filename   = params.get("eye_model_filename",  "best_model_eye_3400.pth")
    um_per_px      = float(params.get("um_per_px", 22.99))
    spacing        = (um_per_px, um_per_px)

    # ---- load models once ----
    body_model = _load_unet_model(
        repo_id="markdanielarndt/Zebrafish_Segmentation",
        filename=body_filename,
        label="body model",
        encoder_name=body_encoder,
        force_download=False,
    )
    if body_model is None:
        raise RuntimeError("Body segmentation model could not be loaded.")

    eye_model = None
    if params.get("eyes", False):
        eye_model = _load_unet_model(
            repo_id="markdanielarndt/Zebrafish_Segmentation",
            filename=eye_filename,
            label="eye model",
            encoder_name="vgg16",
            force_download=False,
        )

    curv_model = load_model() if params.get("curvature", True) else None

    mean = np.array([0.485, 0.456, 0.406])
    std  = np.array([0.229, 0.224, 0.225])

    results = []
    n = len(image_paths)

    for i, image_path in enumerate(image_paths):
        if progressCallback:
            progressCallback(i, n)

        r = {
            "filename":             os.path.basename(image_path),
            "image_path":           image_path,
            "original":             None,
            "mask":                 None,
            "grown":                None,
            "eye_mask":             None,
            "path_points":          None,
            "straight_line_points": None,
            "length":               None,
            "curvature":            None,
            "ratio":                None,
            "eye_area":             None,
            "eye_diameter":         None,
        }

        try:
            original_bgr = cv2.imread(image_path)
            if original_bgr is None:
                print(f"Could not read {image_path}")
                results.append(r)
                continue

            original_rgb = cv2.cvtColor(original_bgr, cv2.COLOR_BGR2RGB)
            r["original"] = original_rgb

            # resize to model input size (256×256)
            img_resized = cv2.resize(original_bgr, target_size, interpolation=cv2.INTER_LINEAR)
            img_rgb_resized = cv2.cvtColor(img_resized, cv2.COLOR_BGR2RGB)
            processed = (img_rgb_resized / 255.0 - mean) / std
            tensor = (torch.tensor(processed, dtype=torch.float32)
                          .permute(2, 0, 1).unsqueeze(0))

            # body segmentation
            seg_mask, _ = segment_fish(tensor, body_model)
            seg_mask  = np.array(seg_mask, dtype=np.uint8)
            seg_mask  = fill_holes(seg_mask)
            grown     = grow_mask(seg_mask)
            r["mask"]  = seg_mask
            r["grown"] = grown

            # eye segmentation
            if eye_model is not None:
                eye_seg, _ = segment_fish(tensor, eye_model, biggest_only=True)
                r["eye_mask"] = np.array(eye_seg, dtype=np.uint8)

            mask_bin     = seg_mask > 0
            eye_mask_bin = (r["eye_mask"] > 0) if r["eye_mask"] is not None else None

            # length + ratio
            if params.get("length", True):
                try:
                    length, straight, path_pts, sl_pts = tube_length_border2border(
                        mask_bin,
                        spacing=spacing,
                        return_path=True,
                        return_straight_line=True,
                        mask_eye=eye_mask_bin,
                        return_eye_info=False,
                    )
                    r["length"]               = float(length)
                    r["path_points"]          = path_pts
                    r["straight_line_points"] = sl_pts
                    if params.get("ratio", True) and straight > 0:
                        r["ratio"] = float(length) / float(straight)
                except Exception as exc:
                    print(f"Length error for {image_path}: {exc}")

            # curvature
            if params.get("curvature", True) and curv_model is not None:
                try:
                    use_thr = params.get("hitl", False)
                    thr     = float(params.get("threshold", 0.85))
                    _, cls  = classification_curvature(
                        original_rgb, grown, curv_model, use_thr, thr
                    )
                    r["curvature"] = int(cls.item())
                except Exception as exc:
                    print(f"Curvature error for {image_path}: {exc}")

            # eye metrics
            if params.get("eyes", False) and eye_mask_bin is not None:
                try:
                    info = compute_eye_metrics(
                        eye_mask_bin, mask_fish=mask_bin, spacing=spacing
                    )
                    r["eye_area"]     = float(info.get("eye_area",     0))
                    r["eye_diameter"] = float(info.get("eye_diameter", 0))
                except Exception as exc:
                    print(f"Eye metrics error for {image_path}: {exc}")

        except Exception as exc:
            import traceback
            print(f"Unhandled error processing {image_path}: {exc}")
            traceback.print_exc()

        results.append(r)

    if progressCallback:
        progressCallback(n, n)

    return results


def export_excel(results, path):
    import openpyxl
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Zebrafish Results"
    headers = ["Filename", "Length (µm)", "Curvature class",
               "Length/straight ratio", "Eye area (µm²)", "Eye diameter (µm)"]
    keys    = ["filename", "length", "curvature", "ratio", "eye_area", "eye_diameter"]
    ws.append(headers)
    for r in results:
        ws.append([r.get(k) for k in keys])
    wb.save(path)


def export_csv(results, path):
    import csv
    headers = ["Filename", "Length (µm)", "Curvature class",
               "Length/straight ratio", "Eye area (µm²)", "Eye diameter (µm)"]
    keys    = ["filename", "length", "curvature", "ratio", "eye_area", "eye_diameter"]
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(headers)
        for r in results:
            w.writerow([r.get(k) for k in keys])
