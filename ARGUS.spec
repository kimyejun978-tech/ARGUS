from pathlib import Path


project_root = Path(SPECPATH)
common_datas = [
    (str(project_root / "verifier" / "semantic_seed.json"), "verifier"),
]

gui_analysis = Analysis(
    [str(project_root / "gui.py")],
    pathex=[str(project_root)],
    binaries=[],
    datas=[
        *common_datas,
        (str(project_root / "webui"), "webui"),
        (
            str(project_root / "tests" / "manual_fixtures"),
            "samples",
        ),
    ],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["tkinter", "PyQt5", "PyQt6", "PySide2", "PySide6"],
    noarchive=False,
    optimize=0,
)
gui_pyz = PYZ(gui_analysis.pure)
gui_exe = EXE(
    gui_pyz,
    gui_analysis.scripts,
    [],
    exclude_binaries=True,
    name="ARGUS",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

engine_analysis = Analysis(
    [str(project_root / "main.py")],
    pathex=[str(project_root)],
    binaries=[],
    datas=common_datas,
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["tkinter", "PyQt5", "PyQt6", "PySide2", "PySide6"],
    noarchive=False,
    optimize=0,
)
engine_pyz = PYZ(engine_analysis.pure)
engine_exe = EXE(
    engine_pyz,
    engine_analysis.scripts,
    [],
    exclude_binaries=True,
    name="argus-engine",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

app = COLLECT(
    gui_exe,
    engine_exe,
    gui_analysis.binaries,
    gui_analysis.datas,
    engine_analysis.binaries,
    engine_analysis.datas,
    name="ARGUS",
)
