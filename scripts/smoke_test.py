"""Drive the real window through every diagram type without a display.

Runs the whole UI offscreen: switches diagram type, selects every element to
build its property form, adds / duplicates / moves / removes elements, checks
the preview renders, and round-trips a save and load.

Usage::

    uv run python scripts/smoke_test.py
"""

from __future__ import annotations

import html
import os
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault(
    "QTWEBENGINE_CHROMIUM_FLAGS", "--no-sandbox --disable-gpu --disable-dev-shm-usage"
)
os.environ.setdefault("QT_LOGGING_RULES", "qt.webenginecontext.debug=false")

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from PyQt6.QtCore import QEventLoop, QTimer  # noqa: E402
from PyQt6.QtGui import QColor  # noqa: E402
from PyQt6.QtWidgets import (  # noqa: E402
    QApplication,
    QColorDialog,
    QComboBox,
    QToolButton,
    QWidget,
)

from diagram_maker import shapes, style  # noqa: E402
from diagram_maker.document import DiagramDocument, sample  # noqa: E402
from diagram_maker.generators import generate  # noqa: E402
from diagram_maker.preview import WEBENGINE_ERROR  # noqa: E402
from diagram_maker.specs import SPECS, SPEC_ORDER  # noqa: E402
from diagram_maker.window import MainWindow, icon_path  # noqa: E402

SETTLE_MS = 2500
FIRST_SETTLE_MS = 9000
FALLBACK_SETTLE_MS = 50

#: the keyword each generator must emit after any frontmatter
KEYWORDS = {
    "flowchart": "flowchart",
    "sequence": "sequenceDiagram",
    "class": "classDiagram",
    "er": "erDiagram",
    "usecase": "usecase-beta",
    "mindmap": "mindmap",
    "gantt": "gantt",
    "timeline": "timeline",
    "pie": "pie",
    "quadrant": "quadrantChart",
    "xychart": "xychart-beta",
}

failures: list[str] = []
checks = 0


def check(condition: bool, message: str) -> None:
    global checks
    checks += 1
    if not condition:
        failures.append(message)
        print(f"  FAIL  {message}")


def settle(milliseconds: int) -> None:
    loop = QEventLoop()
    QTimer.singleShot(milliseconds, loop.quit)
    loop.exec()


def evaluate(window: MainWindow, script: str, wait: int = 3000):
    """Run an expression in the preview page and return its value."""
    box: list[object] = []
    window.preview.evaluate(script, box.append)
    loop = QEventLoop()
    QTimer.singleShot(wait, loop.quit)
    loop.exec()
    return box[0] if box else None


def body_first_line(code: str) -> str:
    """The first line after the optional YAML frontmatter."""
    lines = code.splitlines()
    if lines and lines[0].strip() == "---":
        for index in range(1, len(lines)):
            if lines[index].strip() == "---":
                lines = lines[index + 1 :]
                break
    return next((line.strip() for line in lines if line.strip()), "")


def exercise_forms(window: MainWindow) -> int:
    """Select every node in the structure tree and return how many widgets were built."""
    widgets = 0
    tree = window.tree
    for position in range(tree.topLevelItemCount()):
        top = tree.topLevelItem(position)
        tree.setCurrentItem(top)
        widgets += len(window.form_host.findChildren(QWidget)) if window.form_host else 0
        for child in range(top.childCount()):
            tree.setCurrentItem(top.child(child))
            if window.form_host is not None:
                widgets += len(window.form_host.findChildren(QWidget))
            else:
                failures.append(f"no form built for {top.text(0)} child {child}")
    return widgets


def main() -> int:
    has_webengine = WEBENGINE_ERROR is None
    if not has_webengine:
        print(f"note: no embedded preview ({WEBENGINE_ERROR})")
        print("      render checks are skipped; the browser fallback is exercised instead\n")

    application = QApplication(sys.argv)
    window = MainWindow(sample("flowchart"))
    window.show()

    print("checking the window icon\n")
    check(icon_path().is_file(), f"no icon file at {icon_path()}")
    # the taskbar draws the window's icon, and ignores the one inside the .exe
    check(not window.windowIcon().isNull(), "the window has no icon, so the taskbar is blank")
    check(bool(window.windowIcon().availableSizes()), "the icon file holds no images")

    print("checking the shape outlines\n")
    drawn = 0
    for spec_key in SPEC_ORDER:
        for section in SPECS[spec_key].sections:
            for field in section.fields:
                if not field.shape_icons:
                    continue
                for choice in field.choices:
                    drawn += 1
                    check(
                        not shapes.icon(choice).isNull(),
                        f"{spec_key}: the {field.name} choice {choice!r} has no outline",
                    )
    check(bool(drawn), "no dropdown offers shapes, so nothing above was checked")
    check(shapes.icon("Not a shape").isNull(), "an unknown shape drew an outline anyway")

    # the specs are not the widgets: check the dropdown the window really builds
    nodes = window.tree.topLevelItem(1)
    check(nodes is not None and nodes.childCount() > 0, "the sample flowchart has no nodes")
    if nodes is not None and nodes.childCount() > 0:
        window.tree.setCurrentItem(nodes.child(0))
        application.processEvents()
        combos = window.form_host.findChildren(QComboBox) if window.form_host else []
        shape_combo = next((box for box in combos if box.findText("Stadium") >= 0), None)
        check(shape_combo is not None, "a node form has no shape dropdown")
        if shape_combo is not None:
            for name in ("Rectangle", "Rhombus", "Trapezoid"):
                row = shape_combo.findText(name)
                check(row >= 0, f"{name} is missing from the shape dropdown")
                check(
                    row >= 0 and not shape_combo.itemIcon(row).isNull(),
                    f"{name} carries no outline in the shape dropdown",
                )

    print("checking the style text and its colour swatches\n")
    check(
        style.read("fill:#f9f,stroke:#333") == {"fill": "#f9f", "stroke": "#333"},
        "a style statement was not read back as its properties",
    )
    check(
        style.update("fill:#f9f,stroke:#333", "fill", "#ff0000") == "fill:#ff0000,stroke:#333",
        "writing one style property disturbed the others",
    )
    check(
        style.update("fill:#f9f,stroke-width:4px", "fill", "#00ff00")
        == "fill:#00ff00,stroke-width:4px",
        "a style property with no swatch of its own was dropped",
    )
    check(
        style.update("fill:#f9f,stroke:#333", "stroke", None) == "fill:#f9f",
        "clearing a colour left the property behind",
    )
    check(
        style.read(r"stroke-dasharray:9\,5,fill:#fff")
        == {"stroke-dasharray": r"9\,5", "fill": "#fff"},
        "an escaped comma was taken for a separator",
    )

    # the swatches the form builds are what gets clicked, so exercise one
    nodes = window.tree.topLevelItem(1)
    node = nodes.child(0) if nodes is not None and nodes.childCount() else None
    if node is None:
        failures.append("the sample flowchart has no first node to style")
    else:
        rows = window.document.rows("nodes")
        original = rows[0].get("style", "")
        rows[0]["style"] = "fill:#ff0000,stroke:#00ff00,stroke-width:4px"
        # the form is rebuilt on a selection change, which is what re-reads it
        window.tree.setCurrentItem(window.tree.topLevelItem(0))
        window.tree.setCurrentItem(node)
        application.processEvents()

        swatches = {
            button.text(): button
            for button in (
                window.form_host.findChildren(QToolButton) if window.form_host else []
            )
        }
        check(
            set(swatches) == {"Fill", "Stroke", "Color"},
            f"the style row offers {sorted(swatches)}, not fill, stroke and color",
        )
        if set(swatches) == {"Fill", "Stroke", "Color"}:
            check("#ff0000" in swatches["Fill"].toolTip(), "the fill swatch ignored the document")
            check("#00ff00" in swatches["Stroke"].toolTip(), "the stroke swatch ignored it too")
            check("unset" in swatches["Color"].toolTip(), "an unset colour does not look unset")

            # stand in for the modal dialog, then click the swatch for real
            blocking = QColorDialog.getColor
            QColorDialog.getColor = staticmethod(  # type: ignore[method-assign]
                lambda *args, **kwargs: QColor("#123456")
            )
            try:
                swatches["Fill"].click()
            finally:
                QColorDialog.getColor = blocking  # type: ignore[method-assign]

            check(
                rows[0]["style"] == "fill:#123456,stroke:#00ff00,stroke-width:4px",
                f"clicking the fill swatch wrote {rows[0]['style']!r}",
            )
            check("#123456" in swatches["Fill"].toolTip(), "the swatch kept the old colour")

        rows[0]["style"] = original

    renders: list[tuple[bool, str]] = []
    window.preview.rendered.connect(lambda ok, message: renders.append((ok, message)))

    print("switching through every diagram type\n")
    for index, key in enumerate(SPEC_ORDER):
        window.type_combo.setCurrentIndex(index)
        application.processEvents()
        check(window.document.kind == key, f"type did not switch to {key}")

        result = generate(window.document)
        check(not result.warnings, f"{key}: sample produced warnings {result.warnings}")
        check(bool(result.code.strip()), f"{key}: generated empty mermaid")
        check(
            body_first_line(result.code).startswith(KEYWORDS[key]),
            f"{key}: body starts with {body_first_line(result.code)!r}, "
            f"expected {KEYWORDS[key]!r}",
        )

        widgets = exercise_forms(window)
        check(widgets > 0, f"{key}: no property widgets were built")
        check(window.tree.topLevelItemCount() == len(SPECS[key].sections) + 1,
              f"{key}: tree has {window.tree.topLevelItemCount()} groups, expected "
              f"{len(SPECS[key].sections) + 1}")

        if has_webengine:
            renders.clear()
            settle(FIRST_SETTLE_MS if index == 0 else SETTLE_MS)
            application.processEvents()
            check(bool(renders), f"{key}: the preview never reported back")
            bad = [m for ok, m in renders if not ok]
            check(not bad, f"{key}: preview reported {bad[:1]}")
        else:
            settle(FALLBACK_SETTLE_MS)
            application.processEvents()
            page = window.preview.write_preview_page()
            check(page.is_file(), f"{key}: the fallback preview page was not written")
            check(
                html.escape(result.code) in page.read_text(encoding="utf-8"),
                f"{key}: the fallback page does not contain the mermaid source",
            )

        print(f"  {key:<9} {len(window.document.rows(SPECS[key].sections[0].key))} rows in "
              f"{SPECS[key].sections[0].key}, {widgets} widgets, "
              f"{len(renders)} preview update(s)")

    if has_webengine:
        print("\nchecking the SVG export, which reads the picture back out of the page")
        svg_path = Path(tempfile.gettempdir()) / "diagram-maker-smoke.svg"
        outcome: dict[str, object] = {}
        window.preview.save_svg(
            svg_path, lambda ok, message: outcome.update(ok=ok, message=message)
        )
        settle(3000)
        application.processEvents()
        check(outcome.get("ok") is True, f"SVG export failed: {outcome.get('message')}")
        markup = svg_path.read_text(encoding="utf-8") if svg_path.is_file() else ""
        check("<svg" in markup, "the exported SVG contains no <svg> element")
        check(len(markup) > 500, "the exported SVG looks empty")

        print("checking that an invalid diagram is reported instead of failing silently")
        renders.clear()
        window.preview.set_source("flowchart TD\n  A --> ]]] not valid mermaid")
        settle(3000)
        application.processEvents()
        failures_seen = [message for ok, message in renders if not ok]
        check(bool(failures_seen), "an invalid diagram produced no error report")
        check(
            any(message for message in failures_seen),
            "the error report carried no message to show the user",
        )

        print("checking that repeated failures do not pile up stray elements")
        for _ in range(3):
            window.preview.set_source("flowchart TD\n  A --> ]]] not valid")
            settle(900)
            application.processEvents()
        children = evaluate(
            window,
            "Array.from(document.body.children).map(n => n.id || n.tagName).join(',')",
        )
        check(
            children == "banner,stage,SCRIPT,SCRIPT",
            f"the preview page accumulated stray elements: {children}",
        )

        window._schedule_update(immediate=True)
        settle(2000)
        application.processEvents()

    print("\nexercising structure edits on the flowchart section")
    window.type_combo.setCurrentIndex(SPEC_ORDER.index("flowchart"))
    application.processEvents()
    section = SPECS["flowchart"].sections[0].key
    before = len(window.document.rows(section))

    window.tree.setCurrentItem(window.tree.topLevelItem(1).child(0))
    window._add_item()
    check(len(window.document.rows(section)) == before + 1, "add did not append a row")

    window.tree.setCurrentItem(window.tree.topLevelItem(1).child(0))
    window._duplicate_item()
    check(len(window.document.rows(section)) == before + 2, "duplicate did not insert a row")

    rows_before_move = [dict(row) for row in window.document.rows(section)]
    window.tree.setCurrentItem(window.tree.topLevelItem(1).child(1))
    window._move_up()
    rows_after_move = window.document.rows(section)
    check(
        rows_after_move[0] == rows_before_move[1] and rows_after_move[1] == rows_before_move[0],
        "move up did not swap the first two rows",
    )

    window.tree.setCurrentItem(window.tree.topLevelItem(1).child(0))
    window._remove_item()
    check(len(window.document.rows(section)) == before + 1, "remove did not drop a row")

    print("checking that an incomplete row is reported instead of breaking the preview")
    window.tree.setCurrentItem(window.tree.topLevelItem(1).child(0))
    original_id = window.document.rows(section)[0]["id"]
    window.document.rows(section)[0]["id"] = ""
    result = generate(window.document)
    check(bool(result.warnings), "a node without an id should produce a warning")
    check(bool(result.code.strip()), "the diagram should still generate")
    window._schedule_update(immediate=True)
    if has_webengine:
        settle(1500)
        application.processEvents()
    window.document.rows(section)[0]["id"] = original_id

    print("round-tripping a save and load")
    with tempfile.TemporaryDirectory() as folder:
        target = Path(folder) / f"roundtrip{'.diagram.json'}"
        window.document.save(target)
        reloaded = DiagramDocument.load(target)
        check(reloaded.to_data() == window.document.to_data(), "save/load changed the document")
        check(reloaded.kind == window.document.kind, "save/load lost the diagram type")

    print("checking a blank document still behaves")
    window.document = DiagramDocument.blank("flowchart")
    window._rebuild_tree(select=("options", None))
    window._schedule_update(immediate=True)
    if has_webengine:
        renders.clear()
        settle(SETTLE_MS)
        application.processEvents()
        check(not [m for ok, m in renders if not ok], "a blank diagram reported a preview error")
    check(
        generate(window.document).code.strip() != "",
        "a blank diagram should still generate a mermaid header",
    )

    window._dirty = False
    window.close()

    print()
    if failures:
        print(f"{len(failures)} of {checks} checks failed")
        for failure in failures:
            print(f"  - {failure}")
        return 1
    print(f"all {checks} checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
