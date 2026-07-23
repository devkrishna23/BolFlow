# PyInstaller build recipe: three windowed exes sharing one folder.
# Build:  .venv\Scripts\pyinstaller bolflow.spec --noconfirm
# Output: dist/BolFlow/  (BolFlow.exe + BolFlow-Settings.exe
#         + BolFlow-Onboarding.exe + shared _internal/)

datas = [("app.ico", ".")]

a_app = Analysis(["app.py"], datas=datas)
a_set = Analysis(["settings.py"], datas=datas)
a_onb = Analysis(["onboarding.py"], datas=datas)

MERGE((a_app, "app", "BolFlow"),
      (a_set, "settings", "BolFlow-Settings"),
      (a_onb, "onboarding", "BolFlow-Onboarding"))

exe_app = EXE(PYZ(a_app.pure), a_app.scripts, exclude_binaries=True,
              name="BolFlow", icon="app.ico", console=False)
exe_set = EXE(PYZ(a_set.pure), a_set.scripts, exclude_binaries=True,
              name="BolFlow-Settings", icon="app.ico", console=False)
exe_onb = EXE(PYZ(a_onb.pure), a_onb.scripts, exclude_binaries=True,
              name="BolFlow-Onboarding", icon="app.ico", console=False)

COLLECT(exe_app, a_app.binaries, a_app.datas,
        exe_set, a_set.binaries, a_set.datas,
        exe_onb, a_onb.binaries, a_onb.datas,
        name="BolFlow")
