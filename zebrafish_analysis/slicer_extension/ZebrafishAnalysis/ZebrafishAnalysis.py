import os
import sys

import qt
import slicer
from slicer.ScriptedLoadableModule import (
    ScriptedLoadableModule,
    ScriptedLoadableModuleWidget,
    ScriptedLoadableModuleLogic,
)


def _add_lib_to_path():
    lib_dir = os.path.join(os.path.dirname(__file__), "ZebrafishAnalysisLib")
    if lib_dir not in sys.path:
        sys.path.insert(0, lib_dir)

    repo_root = os.path.dirname(
        os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
    )
    if repo_root not in sys.path:
        sys.path.insert(0, repo_root)


_add_lib_to_path()

_LIB_MODULES = (
    "widget", "gallery_tab", "detail_tab", "logic", "overlay", "export",
    "dependency_installer",
)

def _evict_lib_modules():
    for _m in _LIB_MODULES:
        sys.modules.pop(_m, None)

_evict_lib_modules()


class ZebrafishAnalysis(ScriptedLoadableModule):
    def __init__(self, parent):
        ScriptedLoadableModule.__init__(self, parent)
        self.parent.title = "Zebrafish Analysis"
        self.parent.categories = ["Quantification"]
        self.parent.dependencies = []
        self.parent.contributors = ["Jona Richter", "Mark Daniel Arndt"]
        self.parent.helpText = (
            "Segment zebrafish from 2-D microscopy images and measure "
            "body length, curvature class, length/straight-line ratio, "
            "and eye metrics."
        )
        self.parent.acknowledgementText = (
            "Based on the Zebrafish Webapp "
            "(github.com/MarkDanielArndt/Zebrafish_webapp)."
        )


class ZebrafishAnalysisWidget(ScriptedLoadableModuleWidget):
    def setup(self):
        ScriptedLoadableModuleWidget.setup(self)
        _evict_lib_modules()

        from dependency_installer import check_and_install
        check_and_install()

        from widget import ZebrafishAnalysisMainWidget
        self._main = ZebrafishAnalysisMainWidget(self.layout)

    def cleanup(self):
        pass


class ZebrafishAnalysisLogic(ScriptedLoadableModuleLogic):
    pass
