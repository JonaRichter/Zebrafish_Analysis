# ZebrafishAnalysis — Extension Index Publishing Checklist

## Automatically checked (Phases 1–5)
- [x] Legacy root files removed
- [x] .s4ext file present and complete
- [x] LICENSE present
- [x] CMakeLists.txt icon URL set
- [x] CMakeLists.txt screenshot URL set
- [x] README Installation section present
- [x] All __init__.py present
- [x] No legacy imports
- [x] No hardcoded paths
- [x] Tests: 44/48 passing (4 skipped — widget-dependent and OCR/tesseract tests)

## Manual steps (before PR to ExtensionsIndex)
- [ ] Create real Slicer screenshot (1280×800px) → Documentation_images/slicer_screenshot.png
- [ ] Finalize icon (128×128 PNG) → Resources/Icons/ZebrafishAnalysis.png
- [ ] Test extension live in Slicer 5.x (clean load, no Python Console errors)
- [ ] Merge feat/publish-ready into main (after review)
- [ ] Fork https://github.com/Slicer/ExtensionsIndex
- [ ] Add ZebrafishAnalysis.s4ext to fork
- [ ] Open PR: title "Add ZebrafishAnalysis extension"
- [ ] PR description: brief summary + screenshot + repo link

## PR template for ExtensionsIndex
Title: `Add ZebrafishAnalysis extension`

Description:
> **Summary:** Automated zebrafish body length, spinal curvature classification, and eye metrics from 2D microscopy images.
>
> **Features:** U-Net body/eye segmentation, ConvNeXt curvature classifier (grade 1–4), scale bar detection, manual endpoint correction, Excel/CSV export.
>
> **Models:** Hosted on Hugging Face Hub, downloaded automatically on first use.
>
> **Tested on:** 3D Slicer 5.x, macOS
>
> **Screenshot:** [insert screenshot]
>
> **Repository:** https://github.com/MarkDanielArndt/Zebrafish_webapp
