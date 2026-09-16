"""Diagram Maker - build diagrams visually and export them as mermaid.

The public entry point is :func:`main`, wired up as the ``diagram-maker``
console script::

    uv run diagram-maker                      # start with a sample flowchart
    uv run diagram-maker path.diagram.json    # open a saved document
    uv run diagram-maker --sample usecase     # start from a use case sample
    uv run diagram-maker --export out.mmd     # write mermaid and exit

Every diagram is mermaid source: the window is a visual builder in front of the
mermaid text that the exporters write out.
"""

from __future__ import annotations

import sys
from pathlib import Path

from .document import FILE_SUFFIX, DiagramDocument, sample
from .generators import Result, generate
from .specs import SPECS, SPEC_ORDER

__all__ = [
    "APP_ID",
    "FILE_SUFFIX",
    "DiagramDocument",
    "Result",
    "SPECS",
    "SPEC_ORDER",
    "generate",
    "main",
    "sample",
]

__version__ = "0.1.0"

#: the app's taskbar identity on Windows, kept in step by hand with the
#: AppUserModelId define in packaging\\diagram-maker.iss
APP_ID = "FaizalSadri.DiagramMaker"

_USAGE = f"""\
usage: diagram-maker [options] [FILE]

  FILE           open a saved {FILE_SUFFIX} document
  --sample TYPE  start from the built-in sample for TYPE
  --export FILE  write the mermaid source to FILE and exit, without the GUI
  --list         list the supported diagram types and exit
  -h, --help     show this message

diagram types: {", ".join(SPEC_ORDER)}
"""


def _sample_argument(argv: list[str]) -> str | None:
    """Read ``--sample TYPE``, reporting an unknown type to stderr."""
    if "--sample" not in argv:
        return None
    position = argv.index("--sample")
    if position + 1 >= len(argv):
        print("--sample needs a diagram type", file=sys.stderr)
        return None
    kind = argv[position + 1]
    if kind not in SPECS:
        print(f"unknown diagram type {kind!r}; try --list", file=sys.stderr)
        return None
    return kind


def _run_headless(argv: list[str]) -> int | None:
    """Handle the arguments that do not need a window.

    Returns an exit code, or ``None`` to mean "carry on and open the window".
    """
    if "--list" in argv:
        for key in SPEC_ORDER:
            print(f"{key:<10} {SPECS[key].name}")
        return 0

    if "--export" in argv:
        position = argv.index("--export")
        if position + 1 >= len(argv):
            print("--export needs a file name", file=sys.stderr)
            return 2
        target = Path(argv[position + 1])
        result = generate(sample(_sample_argument(argv) or "flowchart"))
        try:
            target.write_text(result.code, encoding="utf-8")
        except OSError as error:
            print(f"could not write {target}: {error}", file=sys.stderr)
            return 2
        for warning in result.warnings:
            print(f"warning: {warning}", file=sys.stderr)
        print(f"wrote {target}")
        return 0

    return None


def _claim_taskbar_identity() -> None:
    """Claim a taskbar identity of this app's own, on Windows.

    Windows groups taskbar buttons - and picks the icon to draw on them - by
    "AppUserModelID".  Left unset, the ID is inherited from the executable, so
    a run from source shares python.exe's button and gets Python's icon in
    place of the one the window carries.  The installer stamps the same string
    on the shortcuts it creates, which is what keeps the icon right once the
    app is pinned.
    """
    if sys.platform != "win32":
        return
    try:
        import ctypes

        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_ID)
    except (AttributeError, OSError):
        # a nicety, not a requirement: without it the taskbar falls back to
        # whatever the host process advertises
        pass


def main() -> None:
    """Start the application."""
    # before anything is imported or shown, so no window can be created while
    # the process is still advertising the interpreter's identity
    _claim_taskbar_identity()

    argv = list(sys.argv[1:])
    if any(argument in {"-h", "--help"} for argument in argv):
        print(_USAGE)
        return

    if (exit_code := _run_headless(argv)) is not None:
        raise SystemExit(exit_code)

    # QtWebEngine should be imported, and its OpenGL sharing flag set, before the
    # QApplication exists - so these imports deliberately stay inside main().
    # Importing it can fail when the host lacks its system libraries; the window
    # then falls back to opening the diagram in a browser.
    from PyQt6.QtCore import Qt
    from PyQt6.QtWidgets import QApplication

    from .preview import WEBENGINE_ERROR
    from .window import APP_NAME, MainWindow, app_icon

    if WEBENGINE_ERROR is not None:
        print(f"note: no embedded preview ({WEBENGINE_ERROR})", file=sys.stderr)
    QApplication.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts, True)
    application = QApplication(sys.argv)
    application.setApplicationName(APP_NAME)
    application.setApplicationVersion(__version__)
    # dialogs take this too, and it is what the taskbar draws
    application.setWindowIcon(app_icon())

    document = None
    path = None
    if kind := _sample_argument(argv):
        document = sample(kind)
    else:
        candidates = [a for a in argv if not a.startswith("-")]
        if candidates:
            path = Path(candidates[0])
            try:
                document = DiagramDocument.load(path)
            except (OSError, ValueError) as error:
                print(f"could not open {path}: {error}", file=sys.stderr)
                raise SystemExit(2) from error

    window = MainWindow(document, path)
    window.show()
    raise SystemExit(application.exec())


if __name__ == "__main__":
    main()
