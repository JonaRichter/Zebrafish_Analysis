set(MODULE_NAME ZebrafishAnalysis)

slicerMacroBuildScriptedModule(
  NAME ${MODULE_NAME}
  SCRIPTS ${MODULE_NAME}.py
  RESOURCES
    Resources/Icons/${MODULE_NAME}.png
)
