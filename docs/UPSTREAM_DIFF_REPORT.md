# Upstream Diff Report
Generated: 2026-06-09
Comparing: upstream/main (MarkDanielArndt/Zebrafish_webapp) vs origin/main (JonaRichter/Zebrafish_Analysis)

---

## Summary
- 44 files changed (4 modified, 2 deleted, 4 renamed/moved, 34 added)
- 96 commits we have that upstream doesn't
- 3 commits upstream has that we don't

---

## Commits only in our fork (96 commits, most recent first)
```
4ce36bc Fix progress bar flash and model-loading freeze on first run
7742072 Merge branch 'feat/code-review-fixes'
825bcb9 Revert "Replace bare logic imports with relative imports in widget.py"
cb5e171 Document stale MODEL_REGISTRY entries and test-only status
2b146f7 Fix misleading docstring in analyse_images()
ea90569 Remove dead _enter_manual_mode() from webapp/app.py
edbb59e Remove dead parameters from load_model() in length.py
c69a4eb Remove ~450 lines of dead legacy functions from length.py
... (+ 88 earlier commits — full Slicer extension development history)
```

---

## Commits only in upstream (3 commits)
```
0946d49 Merge pull request #3 from Zholubak/olehs_branch
43df1c7 eye diameters added          ← CRITICAL: new function missing from our core
4227cf5 hf-button size changed
4e9bdd4 edited documentation 04.06
```

Author of upstream changes: Oleh Zholubak (collaborator on MarkDanielArndt's repo)

---

## Changed Files

### CRITICAL — core/ changes

| File | Status | Summary |
|---|---|---|
| `length.py` (root) → `zebrafish_analysis/core/length.py` | RENAMED + MODIFIED | Root stub moved to core package. We removed ~450 lines of dead legacy functions. **Upstream added `compute_eye_diameters()` in commit `43df1c7` — this function does NOT exist in our `core/length.py`.** |
| `scalebar.py` → `zebrafish_analysis/core/scalebar.py` | RENAMED + MODIFIED | 80% similar. Moved to core. Our version has OCR enhancements (pytesseract). |
| `seg.py` → `zebrafish_analysis/core/seg.py` | RENAMED + MODIFIED | 94% similar. Moved to core. Our version adds edema segmentation support and model caching. |
| `seg_helper.py` → `zebrafish_analysis/core/seg_helper.py` | RENAMED + MODIFIED | 96% similar. Moved to core. Minor fixes (`.tif` extension check). |

**Missing function detail — `compute_eye_diameters()` (upstream `length.py`, commit `43df1c7`):**
- Measures horizontal (eye_width_um) and vertical (eye_height_um) diameters from binary eye mask
- Uses cv2 connected components to isolate largest region, then bounding-box width/height × spacing
- Used in upstream `app.py` to add Eye Width / Eye Height columns to Excel export and overlay
- **Not present in our `zebrafish_analysis/core/length.py` — needs to be ported to core and wired into both frontends**

---

### Webapp changes

| File | Status | Summary |
|---|---|---|
| `app.py` (root) | MODIFIED | Upstream added eye diameter measurements (width + height columns in Excel, overlay drawing of diameter lines). Our `zebrafish_analysis/webapp/app.py` does not have this. |
| `zebrafish_analysis/webapp/app.py` | ADDED | Our structured webapp module — full Gradio app, ported from root. Missing upstream's eye diameter additions. |
| `zebrafish_analysis/webapp/__init__.py` | ADDED | Package init. Not in upstream. |

---

### Slicer Extension changes

All slicer_extension files are **ADDED** by us — upstream has no Slicer extension at all.

| File | Status | Summary |
|---|---|---|
| `zebrafish_analysis/slicer_extension/CMakeLists.txt` | ADDED | Extension build config |
| `zebrafish_analysis/slicer_extension/README.md` | ADDED | Extension-specific README |
| `zebrafish_analysis/slicer_extension/ZebrafishAnalysis.s4ext` | ADDED | ExtensionsIndex descriptor |
| `zebrafish_analysis/slicer_extension/ZebrafishAnalysis/CMakeLists.txt` | ADDED | Module CMakeLists |
| `zebrafish_analysis/slicer_extension/ZebrafishAnalysis/ZebrafishAnalysis.py` | ADDED | Entry point |
| `zebrafish_analysis/slicer_extension/ZebrafishAnalysis/ZebrafishAnalysisLib/*.py` | ADDED | 10 modules (widget, logic, gallery_tab, detail_tab, results_tab, exclude_tab, zoom_view, overlay, export, dependency_installer) |

---

### Root-level changes

| File | Status | Summary |
|---|---|---|
| `.gitignore` | MODIFIED | We added: `__pycache__/`, `*.pyc`, `.gradio/`, `CLAUDE.md`, `notes_jona.md`, `docs/`, `.DS_Store`, `.claude/` |
| `README.md` | MODIFIED | We added: project structure section, Slicer extension install instructions, removed two screenshot references (for deleted images). Upstream added: HF badge size tweak, two documentation screenshots. |
| `requirements.txt` | MODIFIED | We added `huggingface_hub`. |
| `requirements-dev.txt` | ADDED | New — dev/test dependencies (pytest, pillow, etc.) |
| `Documentation_images/screenshot_exclude_excel.png` | DELETED (by us) / ADDED (by upstream) | We removed these two screenshots from README; upstream added them in `4e9bdd4`. |
| `Documentation_images/screenshot_sheet_name.png` | DELETED (by us) / ADDED (by upstream) | Same as above. |

---

### Package structure changes (all ADDED by us)

| File | Status | Summary |
|---|---|---|
| `zebrafish_analysis/__init__.py` | ADDED | Top-level package init |
| `zebrafish_analysis/core/__init__.py` | ADDED | Core package init |
| `zebrafish_analysis/core/manual.py` | ADDED | Manual endpoint correction logic |
| `zebrafish_analysis/core/models/__init__.py` | ADDED | Models subpackage init |
| `zebrafish_analysis/core/models/registry.py` | ADDED | Model registry (HuggingFace filenames/repo IDs) |
| `tests/` (11 files) | ADDED | Full test suite: seg, length, scalebar, overlay, export, logic, zoom_view, registry, dependency_installer |

---

## Recommendation

**Do NOT merge upstream into our branch directly** — would cause conflicts in all 4 renamed core files.

**Action required — port `compute_eye_diameters()` to our core:**

The only substantive upstream change we're missing is the eye diameter function. The other upstream changes (README badge, screenshots) are minor and already superseded by our README overhaul.

Recommended approach:
1. Copy `compute_eye_diameters()` from upstream's `length.py` into `zebrafish_analysis/core/length.py`
2. Wire it into `zebrafish_analysis/webapp/app.py` (Excel export + overlay)
3. Consider wiring into Slicer extension export as well
4. Add a test for it in `tests/test_length.py`

**Risk of not porting:** Fork diverges from supervisor's feature additions. Eye diameter is a user-visible metric.

**Conflict risk if we later try to merge upstream:** High — all 4 core files were substantially restructured. Cherry-pick of `43df1c7` onto our `main` will conflict in both `length.py` (upstream root vs our core path) and `app.py` (upstream monolith vs our structured webapp).
