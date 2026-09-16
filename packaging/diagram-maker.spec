# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller recipe for the Windows build of Diagram Maker.

Run it through ``scripts/build_installer.py``, which supplies the environment
variables this spec reads and then wraps the result in an installer.  Calling
PyInstaller with this spec directly works too, as long as it is run from the
repository root::

    uv run pyinstaller --noconfirm --clean packaging/diagram-maker.spec

Environment variables, all optional:

``DIAGRAM_MAKER_VERSION``       version stamped into the .exe (default 0.0.0.0)
``DIAGRAM_MAKER_VERSION_FILE``  Windows version resource to compile in
``DIAGRAM_MAKER_ICON``          .ico to use (default src/diagram_maker/icon.ico)
``DIAGRAM_MAKER_CONSOLE``       set to ``1`` for a console build, for debugging
"""

from __future__ import annotations

import os
from pathlib import Path

#: PyInstaller sets SPECPATH to the directory holding this file
_spec_dir = Path(globals().get("SPECPATH") or os.getcwd()).resolve()
ROOT = _spec_dir.parent if _spec_dir.name == "packaging" else _spec_dir

APP_NAME = "Diagram Maker"
ICON = Path(os.environ.get("DIAGRAM_MAKER_ICON") or ROOT / "src" / "diagram_maker" / "icon.ico")
VERSION_FILE = Path(
    os.environ.get("DIAGRAM_MAKER_VERSION_FILE")
    or ROOT / "build" / "windows" / "version_info.txt"
)
CONSOLE = os.environ.get("DIAGRAM_MAKER_CONSOLE") == "1"

analysis = Analysis(  # noqa: F821 - injected by PyInstaller
    [str(ROOT / "src" / "diagram_maker" / "__main__.py")],
    pathex=[str(ROOT / "src")],
    binaries=[],
    # the window sets this as its icon at run time; see window.app_icon
    datas=[(str(ICON), ".")] if ICON.is_file() else [],
    # preview.py imports these inside a try/except so the app can fall back to
    # opening the diagram in a browser; the fallback is exactly the case that
    # makes it easy for a frozen build to end up without them
    hiddenimports=[
        "PyQt6.QtWebEngineCore",
        "PyQt6.QtWebEngineWidgets",
        "PyQt6.QtWebChannel",
        "PyQt6.QtNetwork",
        "PyQt6.QtPrintSupport",
        "PyQt6.QtQuick",
        "PyQt6.QtQuickWidgets",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    # keeping these out saves ~60 MB; none of them belong to this app, but the
    # Qt Designer extra drags PySide6 into the environment
    excludes=[
        "PySide6",
        "shiboken6",
        "tkinter",
        "numpy",
        "matplotlib",
        "PIL",
        "pandas",
        "scipy",
        "pytest",
        "IPython",
    ],
    noarchive=False,
    optimize=0,
)

pyz = PYZ(analysis.pure)  # noqa: F821

# QtWebEngine ships a second, 72 MB copy of the devtools front end that only a
# debug build of Chromium ever reads; nothing here opens devtools, so let it go
analysis.datas = [
    entry
    for entry in analysis.datas
    if not entry[0].endswith("qtwebengine_devtools_resources.debug.pak")
]

exe = EXE(  # noqa: F821
    pyz,
    analysis.scripts,
    [],
    exclude_binaries=True,
    name=APP_NAME,
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=CONSOLE,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=str(ICON) if ICON.exists() else None,
    version=str(VERSION_FILE) if VERSION_FILE.exists() else None,
)

# onedir, not onefile: QtWebEngine unpacks ~200 MB next to the .exe on every
# start when it is squeezed into a single file, which makes launch crawl
bundle = COLLECT(  # noqa: F821
    exe,
    analysis.binaries,
    analysis.datas,
    strip=False,
    upx=False,
    name=APP_NAME,
)
