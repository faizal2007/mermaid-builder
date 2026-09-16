"""The application window: a structure tree, a property editor and a preview.

The UI is generated from the same :mod:`~diagram_maker.specs` data the
generators use, so a diagram type is never described in two places.  Selecting
an element in the tree builds a property form for it; any edit regenerates the
mermaid source and redraws the preview.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from PyQt6.QtCore import QPointF, QRectF, Qt, QTimer
from PyQt6.QtGui import QAction, QColor, QIcon, QKeySequence, QPainter, QPen, QPixmap
from PyQt6.QtWidgets import (
    QCheckBox,
    QColorDialog,
    QComboBox,
    QDockWidget,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QSplitter,
    QStyle,
    QToolBar,
    QTreeWidget,
    QTreeWidgetItem,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from . import shapes, style
from .document import FILE_SUFFIX, DiagramDocument, TextTarget, sample
from .generators import Result, generate
from .preview import MERMAID_VERSION, PreviewPane, standalone_html
from .specs import BOOL, CHOICE, COLOUR, FLOAT, INT, LINES, SPECS, SPEC_ORDER, Field

APP_NAME = "Diagram Maker"

#: drawn by ``packaging/make_icon.py``, and embedded in the .exe as well
ICON_FILE = "icon.ico"

#: how long to wait after the last keystroke before regenerating
DEBOUNCE_MS = 250

#: the colour swatches in the property form, in logical pixels
SWATCH_SIZE = 14

_ROLE_KIND = Qt.ItemDataRole.UserRole
_ROLE_SECTION = Qt.ItemDataRole.UserRole + 1
_ROLE_INDEX = Qt.ItemDataRole.UserRole + 2

#: tree item kinds
_KIND_OPTIONS = "options"
_KIND_SECTION = "section"
_KIND_ITEM = "item"


def icon_path() -> Path:
    """The icon file: beside this module, or in the root of a frozen bundle."""
    if (base := getattr(sys, "_MEIPASS", None)) is not None:
        return Path(base) / ICON_FILE
    return Path(__file__).resolve().parent / ICON_FILE


def app_icon() -> QIcon:
    """The window and taskbar icon.

    Worth setting explicitly: without it the taskbar button has no icon of its
    own, and Windows leaves the space blank even though the .exe carries one.
    """
    path = icon_path()
    return QIcon(str(path)) if path.is_file() else QIcon()


def swatch(colour: str | None) -> QIcon:
    """A filled square of ``colour``, or a crossed out box when there is none.

    Painted rather than styled: a stylesheet border would not follow the
    palette, and the swatch has to read on a light and a dark theme alike.
    """
    pixels = SWATCH_SIZE * 2
    pixmap = QPixmap(pixels, pixels)
    pixmap.fill(Qt.GlobalColor.transparent)

    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    painter.scale(2.0, 2.0)
    painter.setPen(QPen(QColor(128, 128, 128)))
    chosen = QColor(colour or "")
    painter.setBrush(chosen if chosen.isValid() else Qt.BrushStyle.NoBrush)
    painter.drawRoundedRect(QRectF(0.5, 0.5, SWATCH_SIZE - 1.0, SWATCH_SIZE - 1.0), 2.0, 2.0)
    if not chosen.isValid():
        # nothing picked yet, which is worth seeing rather than guessing at
        corner = SWATCH_SIZE - 4.0
        painter.drawLine(QPointF(3.5, 3.5), QPointF(corner, corner))
    painter.end()

    pixmap.setDevicePixelRatio(2.0)
    return QIcon(pixmap)


class MainWindow(QMainWindow):
    def __init__(self, document: DiagramDocument | None = None, path: Path | None = None):
        super().__init__()
        self.document = document or sample("flowchart")
        self.path = path
        self._loading = False
        self._dirty = False
        self._result = Result(code="")
        #: what a double click in the preview pointed at, until it is written
        self._editing: TextTarget | None = None

        self.setWindowTitle(APP_NAME)
        self.setWindowIcon(app_icon())
        self.resize(1280, 840)

        self._build_ui()
        self._build_actions()
        self._rebuild_tree(select=("options", None))
        self._schedule_update(immediate=True)

    # ------------------------------------------------------------------ ui #

    def _build_ui(self) -> None:
        self.preview = PreviewPane(self)
        self.preview.rendered.connect(self._on_rendered)
        self.preview.edit_requested.connect(self._edit_label)
        self.preview.edit_committed.connect(self._write_label)

        splitter = QSplitter(Qt.Orientation.Horizontal, self)
        splitter.addWidget(self.preview)

        self.source_view = QPlainTextEdit()
        self.source_view.setReadOnly(True)
        self.source_view.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self.source_view.setPlaceholderText("The generated mermaid source appears here.")
        font = self.source_view.font()
        font.setFamily("monospace")
        self.source_view.setFont(font)

        source_holder = QWidget()
        source_layout = QVBoxLayout(source_holder)
        source_layout.setContentsMargins(0, 0, 0, 0)
        source_layout.setSpacing(0)
        self.warning_label = QLabel()
        self.warning_label.setWordWrap(True)
        self.warning_label.setStyleSheet(
            "background:#5c4a00; color:#ffe9a8; padding:6px 8px; font-size:12px;"
        )
        self.warning_label.hide()
        source_layout.addWidget(self.warning_label)

        copy_row = QWidget()
        copy_layout = QHBoxLayout(copy_row)
        copy_layout.setContentsMargins(6, 4, 6, 4)
        copy_layout.addStretch(1)
        self.copy_button = QPushButton("Copy mermaid")
        self.copy_button.clicked.connect(self._copy_source)
        copy_layout.addWidget(self.copy_button)
        source_layout.addWidget(copy_row)
        source_layout.addWidget(self.source_view, 1)

        self.source_dock = QDockWidget("Mermaid source", self)
        self.source_dock.setObjectName("source")
        self.source_dock.setWidget(source_holder)
        self.addDockWidget(Qt.DockWidgetArea.BottomDockWidgetArea, self.source_dock)

        self._build_structure_dock()
        self._build_property_dock()
        self.setCentralWidget(splitter)
        self.statusBar().showMessage("Ready")

        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(DEBOUNCE_MS)
        self._timer.timeout.connect(self._refresh)

    def _build_structure_dock(self) -> None:
        self.type_combo = QComboBox()
        for key in SPEC_ORDER:
            spec = SPECS[key]
            self.type_combo.addItem(spec.name, key)
        self.type_combo.setToolTip("Switch diagram type")
        self.type_combo.currentIndexChanged.connect(self._on_type_changed)

        self.tree = QTreeWidget()
        self.tree.setHeaderHidden(True)
        self.tree.setUniformRowHeights(True)
        self.tree.currentItemChanged.connect(self._on_selection_changed)
        self.tree.itemDoubleClicked.connect(self._on_item_double_clicked)

        buttons = QWidget()
        button_row = QHBoxLayout(buttons)
        button_row.setContentsMargins(0, 0, 0, 0)
        button_row.setSpacing(4)

        def tool_button(text: str, tip: str, slot, icon: QStyle.StandardPixmap) -> QPushButton:
            button = QPushButton()
            button.setIcon(self.style().standardIcon(icon))
            button.setToolTip(f"{text} - {tip}")
            button.setFixedWidth(32)
            button.clicked.connect(slot)
            button_row.addWidget(button)
            return button

        self.add_button = tool_button(
            "Add", "add a new element (Ctrl+Return)", self._add_item, QStyle.StandardPixmap.SP_FileDialogNewFolder
        )
        self.duplicate_button = tool_button(
            "Duplicate", "duplicate (Ctrl+D)", self._duplicate_item, QStyle.StandardPixmap.SP_FileDialogDetailedView
        )
        self.remove_button = tool_button(
            "Remove", "remove (Del)", self._remove_item, QStyle.StandardPixmap.SP_TrashIcon
        )
        self.up_button = tool_button(
            "Up", "move up (Alt+Up)", self._move_up, QStyle.StandardPixmap.SP_ArrowUp
        )
        self.down_button = tool_button(
            "Down", "move down (Alt+Down)", self._move_down, QStyle.StandardPixmap.SP_ArrowDown
        )
        button_row.addStretch(1)

        holder = QWidget()
        layout = QVBoxLayout(holder)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(6)
        layout.addWidget(self.type_combo)
        layout.addWidget(self.tree, 1)
        layout.addWidget(buttons)

        self.structure_dock = QDockWidget("Structure", self)
        self.structure_dock.setObjectName("structure")
        self.structure_dock.setWidget(holder)
        self.structure_dock.setMinimumWidth(260)
        self.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea, self.structure_dock)

    def _build_property_dock(self) -> None:
        self.form_scroll = QScrollArea()
        self.form_scroll.setWidgetResizable(True)
        self.form_scroll.setFrameShape(QScrollArea.Shape.NoFrame)

        self.hint_label = QLabel()
        self.hint_label.setWordWrap(True)
        self.hint_label.setStyleSheet("color:#8a8f98; font-size:12px; padding:10px;")

        holder = QWidget()
        layout = QVBoxLayout(holder)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.hint_label)
        layout.addWidget(self.form_scroll, 1)

        self.property_dock = QDockWidget("Properties", self)
        self.property_dock.setObjectName("properties")
        self.property_dock.setWidget(holder)
        self.property_dock.setMinimumWidth(320)
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self.property_dock)

    def _build_actions(self) -> None:
        toolbar = QToolBar("Main")
        toolbar.setObjectName("main")
        toolbar.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.addToolBar(toolbar)
        style = self.style()
        file_actions: list[QAction] = []

        def act(
            text: str,
            slot,
            shortcut: str | QKeySequence | None = None,
            pixmap: QStyle.StandardPixmap | None = None,
            tip: str = "",
            on_toolbar: bool = True,
            in_file_menu: bool = False,
        ) -> QAction:
            action = QAction(text, self)
            action.triggered.connect(slot)
            if shortcut is not None:
                action.setShortcut(QKeySequence(shortcut))
            if pixmap is not None:
                action.setIcon(style.standardIcon(pixmap))
            if tip:
                action.setToolTip(tip)
                action.setStatusTip(tip)
            self.addAction(action)
            if on_toolbar:
                toolbar.addAction(action)
            if in_file_menu:
                file_actions.append(action)
            return action

        act("New", self._new, QKeySequence.StandardKey.New,
            QStyle.StandardPixmap.SP_FileIcon, "Start an empty diagram (Ctrl+N)",
            in_file_menu=True)
        act("Open", self._open, QKeySequence.StandardKey.Open,
            QStyle.StandardPixmap.SP_DialogOpenButton, "Open a saved diagram (Ctrl+O)",
            in_file_menu=True)
        act("Save", self._save, QKeySequence.StandardKey.Save,
            QStyle.StandardPixmap.SP_DialogSaveButton, "Save the diagram (Ctrl+S)",
            in_file_menu=True)
        act("Save as", self._save_as, QKeySequence.StandardKey.SaveAs, None,
            "Save under a new name", on_toolbar=False, in_file_menu=True)
        toolbar.addSeparator()
        act("Export mermaid", self._export_mermaid, "Ctrl+E",
            QStyle.StandardPixmap.SP_ArrowDown, "Write a .mmd file", in_file_menu=True)
        act("Export HTML", self._export_html, "Ctrl+Shift+E",
            QStyle.StandardPixmap.SP_FileLinkIcon, "Write a standalone web page",
            in_file_menu=True)
        act("Export SVG", self._export_svg, "Ctrl+Alt+S",
            QStyle.StandardPixmap.SP_FileDialogDetailedView, "Save the rendered picture",
            in_file_menu=True)
        toolbar.addSeparator()
        act("Redraw", self._reload_preview, "F5",
            QStyle.StandardPixmap.SP_BrowserReload, "Reload the preview (F5)")
        act("Zoom in", lambda: self._zoom(1.15), QKeySequence.StandardKey.ZoomIn, None, "Zoom in")
        act("Zoom out", lambda: self._zoom(1 / 1.15), QKeySequence.StandardKey.ZoomOut, None,
            "Zoom out")
        act("Reset zoom", lambda: self._zoom_to(1.0), "Ctrl+0", None, "Reset zoom")

        file_menu = self.menuBar().addMenu("&File")
        file_menu.addActions(file_actions)
        file_menu.addSeparator()
        samples = file_menu.addMenu("New from sample")
        for key in SPEC_ORDER:
            action = QAction(SPECS[key].name, self)
            action.triggered.connect(lambda _checked=False, k=key: self._new_sample(k))
            samples.addAction(action)
        file_menu.addSeparator()
        file_menu.addAction(self._action("Quit", self.close, QKeySequence.StandardKey.Quit))

        edit_menu = self.menuBar().addMenu("&Edit")
        edit_menu.addAction(self._action("Add element", self._add_item, "Ctrl+Return"))
        edit_menu.addAction(self._action("Duplicate element", self._duplicate_item, "Ctrl+D"))
        edit_menu.addAction(
            self._action("Remove element", self._remove_item, QKeySequence.StandardKey.Delete)
        )
        edit_menu.addAction(self._action("Move up", self._move_up, "Alt+Up"))
        edit_menu.addAction(self._action("Move down", self._move_down, "Alt+Down"))
        edit_menu.addSeparator()
        edit_menu.addAction(self._action("Copy mermaid", self._copy_source, "Ctrl+Shift+C"))

        view_menu = self.menuBar().addMenu("&View")
        view_menu.addAction(self.structure_dock.toggleViewAction())
        view_menu.addAction(self.property_dock.toggleViewAction())
        view_menu.addAction(self.source_dock.toggleViewAction())
        view_menu.addSeparator()
        self.dark_action = QAction("Dark preview background", self)
        self.dark_action.setCheckable(True)
        self.dark_action.toggled.connect(self.preview.set_dark)
        view_menu.addAction(self.dark_action)

        help_menu = self.menuBar().addMenu("&Help")
        help_menu.addAction(self._action("About", self._about))

    def _action(self, text: str, slot, shortcut=None) -> QAction:
        action = QAction(text, self)
        action.triggered.connect(slot)
        if shortcut is not None:
            action.setShortcut(QKeySequence(shortcut))
        self.addAction(action)
        return action

    # -------------------------------------------------------------- updates #

    def _schedule_update(self, *, immediate: bool = False) -> None:
        if immediate:
            self._timer.stop()
            self._refresh()
        else:
            self._timer.start()

    def _refresh(self) -> None:
        self._result = generate(self.document)
        self.source_view.setPlainText(self._result.code)
        self.preview.set_source(self._result.code)
        self._show_warnings()

    def _show_warnings(self) -> None:
        warnings = self._result.warnings
        if not warnings:
            self.warning_label.hide()
            return
        self.warning_label.setText(
            f"{len(warnings)} element(s) were left out:\n"
            + "\n".join(f"  - {w}" for w in warnings[:8])
            + ("\n  ..." if len(warnings) > 8 else "")
        )
        self.warning_label.show()

    def _on_rendered(self, ok: bool, message: str) -> None:
        if ok:
            self.statusBar().showMessage(
                f"{SPECS[self.document.kind].name} - {len(self._result.warnings)} warning(s)"
                if self._result.warnings
                else f"{SPECS[self.document.kind].name} - rendered"
            )
        else:
            self.statusBar().showMessage(f"Preview problem: {message[:200]}")

    # -------------------------------------------------------------- editing #

    def _edit_label(self, element_id: str, text: str, classes: list, order: int) -> None:
        """A label in the preview was double clicked: edit it where it sits.

        The element is selected as well, so the tree and the property form show
        where the text lives while it is being changed.
        """
        target = self.document.find_text(element_id, text, classes, order)
        if target is None:
            self.statusBar().showMessage(
                f"Nothing to edit there - {text!r} is not drawn from an element", 4000
            )
            return
        self._editing = target
        self._rebuild_tree(select=(target.section, target.index))
        self.preview.edit_text(self.document.text_at(target))

    def _write_label(self, text: str) -> None:
        """Keep what was typed over a label, and redraw."""
        if self._editing is None or not self.document.set_text(self._editing, text):
            return
        self._mark_modified()
        self._rebuild_tree(select=(self._editing.section, self._editing.index))
        self._schedule_update()

    # ------------------------------------------------------------- tree view #

    def _rebuild_tree(self, select: tuple[str, int | None] | None = None) -> None:
        self._loading = True
        try:
            self.tree.clear()
            spec = self.document.spec

            options_item = QTreeWidgetItem(["Diagram settings"])
            options_item.setData(0, _ROLE_KIND, _KIND_OPTIONS)
            options_item.setData(0, _ROLE_SECTION, None)
            options_item.setData(0, _ROLE_INDEX, None)
            options_item.setForeground(0, self.palette().brush(self.palette().ColorRole.Mid))
            self.tree.addTopLevelItem(options_item)

            for item_spec in spec.sections:
                rows = self.document.rows(item_spec.key)
                parent = QTreeWidgetItem([f"{item_spec.label} ({len(rows)})"])
                parent.setData(0, _ROLE_KIND, _KIND_SECTION)
                parent.setData(0, _ROLE_SECTION, item_spec.key)
                parent.setData(0, _ROLE_INDEX, None)
                parent.setFlags(parent.flags() & ~Qt.ItemFlag.ItemIsSelectable)
                font = parent.font(0)
                font.setBold(True)
                parent.setFont(0, font)
                self.tree.addTopLevelItem(parent)
                parent.setExpanded(True)

                for index, row in enumerate(rows):
                    child = QTreeWidgetItem([item_spec.summarize(row)])
                    child.setData(0, _ROLE_KIND, _KIND_ITEM)
                    child.setData(0, _ROLE_SECTION, item_spec.key)
                    child.setData(0, _ROLE_INDEX, index)
                    parent.addChild(child)
        finally:
            self._loading = False

        self._type_combo_sync()
        self._select(select or ("options", None))

    def _type_combo_sync(self) -> None:
        index = self.type_combo.findData(self.document.kind)
        if index >= 0 and index != self.type_combo.currentIndex():
            self.type_combo.blockSignals(True)
            self.type_combo.setCurrentIndex(index)
            self.type_combo.blockSignals(False)

    def _select(self, target: tuple[str, int | None]) -> None:
        section_key, index = target
        for position in range(self.tree.topLevelItemCount()):
            top = self.tree.topLevelItem(position)
            if section_key == _KIND_OPTIONS and top.data(0, _ROLE_KIND) == _KIND_OPTIONS:
                self.tree.setCurrentItem(top)
                return
            if top.data(0, _ROLE_SECTION) != section_key:
                continue
            if index is None:
                self.tree.setCurrentItem(top)
                return
            if 0 <= index < top.childCount():
                self.tree.setCurrentItem(top.child(index))
                return
        self.tree.setCurrentItem(self.tree.topLevelItem(0))

    def _current_target(self) -> tuple[str, int | None] | None:
        item = self.tree.currentItem()
        if item is None:
            return None
        kind = item.data(0, _ROLE_KIND)
        return (item.data(0, _ROLE_SECTION) or _KIND_OPTIONS, item.data(0, _ROLE_INDEX)) if kind != _KIND_SECTION else None

    def _on_selection_changed(self, *_args) -> None:
        if self._loading:
            return
        self._update_buttons()
        target = self._current_target()
        if target is not None:
            self._build_form(*target)
            return
        item = self.tree.currentItem()
        section_key = item.data(0, _ROLE_SECTION) if item is not None else None
        item_spec = self.document.spec.section(section_key) if section_key else None
        if item_spec is not None:
            self._show_placeholder(
                f"{item_spec.label}\n\n"
                + (item_spec.tip or "Double-click this group to add an element.")
            )

    def _on_item_double_clicked(self, item: QTreeWidgetItem, _column: int) -> None:
        if item.data(0, _ROLE_KIND) == _KIND_SECTION:
            self._add_to_section(item.data(0, _ROLE_SECTION))

    def _update_buttons(self) -> None:
        item = self.tree.currentItem()
        kind = item.data(0, _ROLE_KIND) if item is not None else None
        section_key = item.data(0, _ROLE_SECTION) if item is not None else None
        index = item.data(0, _ROLE_INDEX) if item is not None else None
        rows = self.document.rows(section_key) if section_key else []

        self.add_button.setEnabled(bool(section_key))
        self.duplicate_button.setEnabled(kind == _KIND_ITEM)
        self.remove_button.setEnabled(kind == _KIND_ITEM)
        self.up_button.setEnabled(kind == _KIND_ITEM and index is not None and index > 0)
        self.down_button.setEnabled(
            kind == _KIND_ITEM and index is not None and index < len(rows) - 1
        )

    # ----------------------------------------------------------- form editor #

    def _show_placeholder(self, message: str) -> None:
        self.hint_label.setText(message)
        self._set_form_host(None)

    def _set_form_host(self, host: QWidget | None) -> None:
        """Swap in a new form widget, disposing of the previous one."""
        previous = self.form_scroll.takeWidget()
        if previous is not None:
            previous.deleteLater()
        self.form_host = host
        self.form_scroll.setWidget(host)

    def _build_form(self, section_key: str, index: int | None) -> None:
        self._loading = True
        try:
            host = QWidget()
            layout = QFormLayout(host)
            layout.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
            layout.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
            layout.setContentsMargins(10, 6, 10, 10)
            layout.setSpacing(8)

            if section_key == _KIND_OPTIONS:
                spec = self.document.spec
                self.hint_label.setText(
                    f"{spec.name}\n\n{spec.blurb}\n\n"
                    "These settings apply to the whole diagram."
                )
                for field in spec.options:
                    self._add_row(layout, field, self.document.options)
            else:
                item_spec = self.document.spec.section(section_key)
                rows = self.document.rows(section_key)
                if item_spec is None or index is None or not (0 <= index < len(rows)):
                    layout.addRow(QLabel("Select an element on the left."))
                else:
                    self.hint_label.setText(
                        f"{item_spec.label} #{index + 1}"
                        + (f"\n\n{item_spec.tip}" if item_spec.tip else "")
                    )
                    for field in item_spec.fields:
                        self._add_row(layout, field, rows[index])

            self._set_form_host(host)
        finally:
            self._loading = False

    def _add_row(self, layout: QFormLayout, field: Field, holder: dict) -> None:
        label = QLabel(field.label)
        if field.tip:
            label.setToolTip(field.tip)
        layout.addRow(label, self._make_editor(field, holder.get(field.name, field.default)))

    def _make_editor(self, field: Field, value) -> QWidget:
        def store(new_value) -> None:
            if self._loading:
                return
            self._commit(field, new_value)

        if field.kind == LINES:
            editor = QPlainTextEdit()
            editor.setPlainText(str(value or ""))
            editor.setPlaceholderText(field.placeholder)
            editor.setFixedHeight(96)
            editor.textChanged.connect(lambda e=editor: store(e.toPlainText()))
            return editor

        if field.kind == CHOICE:
            editor = QComboBox()
            choices = list(field.choices)
            text = str(value or "")
            if text and text not in choices:
                choices.insert(0, text)
            if field.shape_icons:
                # "Stadium" and "Rhombus" mean little until they are drawn, so
                # every entry carries the outline mermaid will produce
                for choice in choices:
                    editor.addItem(shapes.icon(choice), choice)
            else:
                editor.addItems(choices)
            if text:
                editor.setCurrentText(text)
            editor.currentTextChanged.connect(store)
            return editor

        if field.kind == COLOUR:
            return self._colour_editor(field, value, store)

        if field.kind == BOOL:
            editor = QCheckBox()
            editor.setChecked(bool(value))
            editor.toggled.connect(store)
            return editor

        if field.kind == INT:
            editor = QSpinBox()
            editor.setRange(int(field.minimum), int(field.maximum))
            editor.setValue(int(value or 0))
            editor.valueChanged.connect(store)
            return editor

        if field.kind == FLOAT:
            editor = QDoubleSpinBox()
            editor.setRange(field.minimum, field.maximum)
            editor.setDecimals(field.decimals)
            editor.setSingleStep(field.step)
            editor.setValue(float(value or 0))
            editor.valueChanged.connect(store)
            return editor

        editor = QLineEdit(str(value or ""))
        editor.setPlaceholderText(field.placeholder)
        editor.textEdited.connect(store)
        return editor

    def _colour_editor(self, field: Field, value, store) -> QWidget:
        """One swatch per style property, opening a colour dialog.

        The field's value stays the mermaid style text, so the generators and
        the saved documents are untouched: picking a colour rewrites only the
        property it belongs to.
        """
        holder = QWidget()
        row = QHBoxLayout(holder)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(6)

        current = style.read(str(value or ""))
        buttons: dict[str, QToolButton] = {}

        def refresh(name: str) -> None:
            button = buttons[name]
            chosen = current.get(name)
            button.setIcon(swatch(chosen))
            button.setToolTip(
                f"{name}: {chosen or 'unset'} - click to pick, right-click to clear"
            )

        def set_property(name: str, colour: str | None) -> None:
            if colour is None:
                current.pop(name, None)
            else:
                current[name] = colour
            refresh(name)
            store(style.write(current))

        def choose(name: str) -> None:
            existing = QColor(current.get(name, ""))
            picked = QColorDialog.getColor(
                existing if existing.isValid() else QColor(Qt.GlobalColor.white),
                self,
                f"{field.label}: {name}",
            )
            if picked.isValid():
                set_property(name, picked.name())

        for name in field.colours:
            button = QToolButton()
            button.setText(name.capitalize())
            button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
            button.clicked.connect(lambda _checked=False, n=name: choose(n))
            # clearing has to be reachable, and a right click is where a swatch
            # keeps it in every other colour picker
            button.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
            button.customContextMenuRequested.connect(
                lambda _point, n=name: set_property(n, None)
            )
            buttons[name] = button
            refresh(name)
            row.addWidget(button)

        row.addStretch(1)
        return holder

    def _commit(self, field: Field, value) -> None:
        target = self._current_target()
        if target is None:
            return
        section_key, index = target
        if section_key == _KIND_OPTIONS:
            self.document.options[field.name] = value
        elif index is not None:
            rows = self.document.rows(section_key)
            if 0 <= index < len(rows):
                rows[index][field.name] = value
                self._update_tree_row(section_key, index)
        self._mark_modified()
        self._schedule_update()

    def _update_tree_row(self, section_key: str, index: int) -> None:
        item_spec = self.document.spec.section(section_key)
        if item_spec is None:
            return
        for position in range(self.tree.topLevelItemCount()):
            top = self.tree.topLevelItem(position)
            if top.data(0, _ROLE_SECTION) == section_key and 0 <= index < top.childCount():
                rows = self.document.rows(section_key)
                top.child(index).setText(0, item_spec.summarize(rows[index]))
                top.setText(0, f"{item_spec.label} ({len(rows)})")
                return

    # ------------------------------------------------------------- structure #

    def _add_item(self) -> None:
        item = self.tree.currentItem()
        if item is None:
            return
        section_key = item.data(0, _ROLE_SECTION)
        if not section_key:
            section_key = self.document.spec.sections[0].key
        self._add_to_section(section_key)

    def _add_to_section(self, section_key: str) -> None:
        item_spec = self.document.spec.section(section_key)
        if item_spec is None:
            return
        rows = self.document.rows(section_key)
        rows.append(item_spec.blank())
        self._mark_modified()
        self._rebuild_tree(select=(section_key, len(rows) - 1))
        self._schedule_update()

    def _duplicate_item(self) -> None:
        target = self._current_target()
        if target is None or target[1] is None:
            return
        section_key, index = target
        rows = self.document.rows(section_key)
        if 0 <= index < len(rows):
            rows.insert(index + 1, dict(rows[index]))
            self._mark_modified()
            self._rebuild_tree(select=(section_key, index + 1))
            self._schedule_update()

    def _remove_item(self) -> None:
        target = self._current_target()
        if target is None or target[1] is None:
            return
        section_key, index = target
        rows = self.document.rows(section_key)
        if 0 <= index < len(rows):
            del rows[index]
            self._mark_modified()
            self._rebuild_tree(select=(section_key, min(index, len(rows) - 1) if rows else None))
            self._schedule_update()

    def _move(self, offset: int) -> None:
        target = self._current_target()
        if target is None or target[1] is None:
            return
        section_key, index = target
        rows = self.document.rows(section_key)
        new_index = index + offset
        if 0 <= index < len(rows) and 0 <= new_index < len(rows):
            rows[index], rows[new_index] = rows[new_index], rows[index]
            self._mark_modified()
            self._rebuild_tree(select=(section_key, new_index))
            self._schedule_update()

    def _move_up(self) -> None:
        self._move(-1)

    def _move_down(self) -> None:
        self._move(1)

    def _on_type_changed(self, combo_index: int) -> None:
        key = self.type_combo.itemData(combo_index)
        if not key or key == self.document.kind:
            return
        self.document.set_kind(key)
        if self.document.is_empty():
            # a brand new type would show nothing at all, so start from the sample
            self.document = sample(key)
        self._mark_modified()
        self._rebuild_tree(select=("options", None))
        self._schedule_update(immediate=True)

    # ------------------------------------------------------------- documents #

    def _mark_modified(self) -> None:
        self._dirty = True
        self._update_window_title()

    def _update_window_title(self) -> None:
        name = self.path.name if self.path else "Untitled"
        star = "*" if self._dirty else ""
        self.setWindowTitle(f"{name}{star} - {APP_NAME}")

    def _confirm_discard(self) -> bool:
        if not self._dirty:
            return True
        answer = QMessageBox.question(
            self,
            APP_NAME,
            "The diagram has unsaved changes. Save before continuing?",
            QMessageBox.StandardButton.Save
            | QMessageBox.StandardButton.Discard
            | QMessageBox.StandardButton.Cancel,
        )
        if answer == QMessageBox.StandardButton.Save:
            return self._save()
        return answer == QMessageBox.StandardButton.Discard

    def _load_document(self, document: DiagramDocument, path: Path | None) -> None:
        self.document = document
        self.path = path
        self._dirty = False
        self._rebuild_tree(select=("options", None))
        self._schedule_update(immediate=True)
        self._update_window_title()

    def _new(self) -> None:
        if not self._confirm_discard():
            return
        self._load_document(DiagramDocument.blank(self.document.kind), None)
        self.statusBar().showMessage("New empty diagram")

    def _new_sample(self, key: str) -> None:
        if not self._confirm_discard():
            return
        self._load_document(sample(key), None)
        self.statusBar().showMessage(f"Loaded the {SPECS[key].name} sample")

    def _open(self) -> None:
        if not self._confirm_discard():
            return
        chosen, _ = QFileDialog.getOpenFileName(
            self, "Open diagram", str(Path.home()), f"Diagram files (*{FILE_SUFFIX});;JSON (*.json)"
        )
        if not chosen:
            return
        try:
            document = DiagramDocument.load(chosen)
        except (OSError, ValueError, json.JSONDecodeError) as error:
            QMessageBox.critical(self, APP_NAME, f"Could not open the file:\n{error}")
            return
        self._load_document(document, Path(chosen))

    def _save(self) -> bool:
        if self.path is None:
            return self._save_as()
        try:
            self.document.save(self.path)
        except OSError as error:
            QMessageBox.critical(self, APP_NAME, f"Could not save the file:\n{error}")
            return False
        self._dirty = False
        self._update_window_title()
        self.statusBar().showMessage(f"Saved {self.path.name}")
        return True

    def _save_as(self) -> bool:
        suggested = str(self.path) if self.path else str(Path.home() / f"diagram{FILE_SUFFIX}")
        chosen, _ = QFileDialog.getSaveFileName(
            self, "Save diagram", suggested, f"Diagram files (*{FILE_SUFFIX})"
        )
        if not chosen:
            return False
        self.path = Path(chosen)
        return self._save()

    # --------------------------------------------------------------- exports #

    def _suggested_path(self, suffix: str) -> str:
        stem = self.path.name.replace(FILE_SUFFIX, "") if self.path else ""
        folder = self.path.parent if self.path else Path.home()
        return str(folder / f"{stem or 'diagram'}{suffix}")

    def _export_mermaid(self) -> None:
        chosen, _ = QFileDialog.getSaveFileName(
            self, "Export mermaid", self._suggested_path(".mmd"), "Mermaid (*.mmd);;Text (*.txt)"
        )
        if not chosen:
            return
        try:
            Path(chosen).write_text(self._result.code, encoding="utf-8")
        except OSError as error:
            QMessageBox.critical(self, APP_NAME, f"Could not write the file:\n{error}")
            return
        self.statusBar().showMessage(f"Exported {Path(chosen).name}")

    def _export_html(self) -> None:
        chosen, _ = QFileDialog.getSaveFileName(
            self, "Export HTML", self._suggested_path(".html"), "Web page (*.html)"
        )
        if not chosen:
            return
        page = standalone_html(self._result.code, SPECS[self.document.kind].name)
        try:
            Path(chosen).write_text(page, encoding="utf-8")
        except OSError as error:
            QMessageBox.critical(self, APP_NAME, f"Could not write the file:\n{error}")
            return
        self.statusBar().showMessage(f"Exported {Path(chosen).name}")

    def _export_svg(self) -> None:
        chosen, _ = QFileDialog.getSaveFileName(
            self, "Export SVG", self._suggested_path(".svg"), "Scalable vector graphics (*.svg)"
        )
        if not chosen:
            return

        def done(ok: bool, message: str) -> None:
            if ok:
                self.statusBar().showMessage(f"Exported {Path(message).name}")
            else:
                QMessageBox.warning(
                    self, APP_NAME, f"Could not export the picture:\n{message}"
                )

        self.preview.save_svg(chosen, done)

    def _copy_source(self) -> None:
        from PyQt6.QtWidgets import QApplication

        QApplication.clipboard().setText(self._result.code)
        self.statusBar().showMessage("Mermaid source copied to the clipboard")

    def _reload_preview(self) -> None:
        self.preview.refresh()
        self._schedule_update(immediate=True)

    def _zoom_to(self, factor: float) -> None:
        self.preview.set_zoom(factor)
        self.statusBar().showMessage(f"Zoom {self.preview.zoom() * 100:.0f}%")

    def _zoom(self, factor: float) -> None:
        self._zoom_to(self.preview.zoom() * factor)

    def _about(self) -> None:
        QMessageBox.about(
            self,
            APP_NAME,
            f"<h3>{APP_NAME}</h3>"
            "<p>Build diagrams visually and export them as mermaid.</p>"
            f"<p>{len(SPEC_ORDER)} diagram types, rendered by mermaid "
            f"{MERMAID_VERSION}.</p>"
            "<p>The preview loads mermaid from jsdelivr, so it needs a network "
            "connection. Exports never do.</p>",
        )

    # ------------------------------------------------------------- overrides #

    def closeEvent(self, event) -> None:  # noqa: N802 - Qt naming
        if self._confirm_discard():
            event.accept()
        else:
            event.ignore()
