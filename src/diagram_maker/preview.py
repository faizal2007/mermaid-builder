"""The live mermaid preview, rendered by QtWebEngine.

Mermaid is JavaScript, so a real browser engine draws the diagram.  The page
below is loaded once and then asked to re-render on every edit; results come
back through the page title, which avoids needing a web channel object and
works even when ``QWebChannel`` is unavailable.

Title protocol (set by the page, read by :class:`PreviewPane`):

======================  ====================================================
``mermaid:boot``        page loaded, mermaid still being fetched
``mermaid:ready``       mermaid loaded, waiting for a diagram
``mermaid:ok``          the diagram rendered
``mermaid:error:<msg>`` rendering failed, ``<msg>`` is the parse error
``mermaid:offline``     the mermaid bundle could not be fetched from the CDN
``mermaid:edit:<json>`` a label was double clicked; ``<json>`` is the id and
                        text of what was hit, percent encoded
``mermaid:edit-commit:``the text typed over that label, percent encoded
======================  ====================================================
"""

from __future__ import annotations

import html
import json
import tempfile
from pathlib import Path
from urllib.parse import unquote

from PyQt6.QtCore import Qt, QUrl, pyqtSignal
from PyQt6.QtGui import QDesktopServices
from PyQt6.QtWidgets import (
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

try:
    from PyQt6.QtWebEngineCore import QWebEngineSettings
    from PyQt6.QtWebEngineWidgets import QWebEngineView

    #: ``None`` when QtWebEngine is usable, otherwise why it is not
    WEBENGINE_ERROR: str | None = None
except ImportError as error:  # depends on the host's shared libraries
    QWebEngineSettings = None  # type: ignore[assignment]
    QWebEngineView = None  # type: ignore[assignment]
    WEBENGINE_ERROR = str(error)

#: packages that provide the shared libraries QtWebEngine dlopens at import time
LINUX_PACKAGES = (
    "libasound2t64",
    "libxcomposite1",
    "libxdamage1",
    "libxrandr2",
    "libxtst6",
    "libxfixes3",
)

#: pinned so that a mermaid release cannot change how existing documents render
MERMAID_VERSION = "12.0.0"
MERMAID_CDN = f"https://cdn.jsdelivr.net/npm/mermaid@{MERMAID_VERSION}/dist/mermaid.min.js"

_TITLE_PREFIX = "mermaid:"

_PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>mermaid:boot</title>
<style>
  :root { color-scheme: light dark; }
  * { box-sizing: border-box; }
  html, body { margin: 0; height: 100%%; }
  body {
    font: 14px/1.5 system-ui, -apple-system, "Segoe UI", sans-serif;
    background: %(background)s;
    color: %(foreground)s;
    display: flex;
    flex-direction: column;
    overflow: hidden;
  }
  #banner {
    display: none;
    align-items: flex-start;
    gap: 10px;
    padding: 10px 14px;
    font-size: 13px;
  }
  #banner.error { background: #5c1a1f; color: #ffd7d7; }
  #banner.info { background: #1d3a5c; color: #d7e8ff; }
  #banner-text { flex: 1 1 auto; white-space: pre-wrap; }
  #banner-close {
    flex: 0 0 auto;
    font: inherit;
    padding: 2px 10px;
    cursor: pointer;
    border: 1px solid currentColor;
    border-radius: 4px;
    background: transparent;
    color: inherit;
  }
  #stage { flex: 1 1 auto; overflow: auto; padding: 16px; position: relative; }
  #stage svg { max-width: 100%%; height: auto; }
  #empty { color: #8a8f98; }
  #label-editor {
    position: absolute;
    z-index: 10;
    display: none;
    margin: 0;
    padding: 1px 4px;
    border: 2px solid #4c8bf5;
    border-radius: 3px;
    background: #ffffff;
    color: #1f2328;
    text-align: center;
    box-shadow: 0 2px 8px rgba(0, 0, 0, 0.4);
  }
</style>
</head>
<body>
<div id="banner"><span id="banner-text"></span><button id="banner-close" type="button" title="Hide this message">Dismiss</button></div>
<div id="stage"><p id="empty">Nothing to draw yet.</p></div>
<script src="%(cdn)s" onerror="window.__cdnFailed = true;"></script>
<script>
const stage = document.getElementById('stage');
const banner = document.getElementById('banner');
const bannerText = document.getElementById('banner-text');
let counter = 0;
let sequence = 0;

// The page title is the only channel back to Python, and Qt only emits
// titleChanged when the string actually differs - so every status carries a
// counter that guarantees it does.
function setTitle(status, detail) {
  sequence += 1;
  document.title = '%(prefix)s' + status + '#' + sequence + (detail ? ':' + detail : '');
}

document.getElementById('banner-close').addEventListener('click', function () {
  banner.style.display = 'none';
});

function showBanner(kind, message) {
  banner.className = kind;
  bannerText.textContent = message;
  banner.style.display = kind ? 'flex' : 'none';
}

// When a render fails mermaid appends its own "Syntax error in text" graphic to
// the body and never removes it, so repeated failures would stack up over the
// diagram and could not be closed. Keep only the elements this page owns.
function clearStrayNodes() {
  for (const node of Array.from(document.body.children)) {
    if (node.tagName === 'SCRIPT' || node.id === 'banner' || node.id === 'stage') continue;
    node.remove();
  }
}

// ---------------------------------------------------------------- editing # //
// Double clicking a label edits it where it sits.  The page only says what was
// clicked: Python decides which element that is and hands back the text to put
// in the box, so the document - not the rendered, possibly reformatted string -
// is what gets edited.

const labelEditor = document.createElement('input');
labelEditor.id = 'label-editor';
labelEditor.type = 'text';
labelEditor.spellcheck = false;

let editTarget = null;

function closeEditor() {
  labelEditor.style.display = 'none';
  editTarget = null;
}

// The editor lives inside the stage, and is placed against the stage's own
// coordinates, so scrolling the diagram moves the box with the label it sits
// on.  Redrawing the stage takes the box with it, which is why it is mounted
// again after every render - and why a redraw closes the edit: the label it
// pointed at no longer exists.
function placeEditor() {
  if (!editTarget) return;
  if (!editTarget.isConnected) {
    closeEditor();
    return;
  }
  const box = editTarget.getBoundingClientRect();
  const host = stage.getBoundingClientRect();
  const style = getComputedStyle(editTarget);
  const size = parseFloat(style.fontSize) || 14;
  labelEditor.style.font = size + 'px/1.3 ' + (style.fontFamily || 'sans-serif');
  labelEditor.style.left = (box.left - host.left + stage.scrollLeft) + 'px';
  labelEditor.style.top = (box.top - host.top + stage.scrollTop) + 'px';
  labelEditor.style.width = Math.max(box.width + 24, 90) + 'px';
  labelEditor.style.height = Math.max(box.height + 8, 24) + 'px';
}

function mountEditor() {
  if (labelEditor.parentElement !== stage) stage.appendChild(labelEditor);
  placeEditor();
}

window.showLabelEditor = function (text) {
  if (!editTarget) return;
  labelEditor.value = text;
  labelEditor.style.display = 'block';
  placeEditor();
  labelEditor.focus();
  labelEditor.select();
};

labelEditor.addEventListener('keydown', function (event) {
  if (event.key === 'Enter') {
    event.preventDefault();
    const typed = labelEditor.value;
    closeEditor();
    setTitle('edit-commit', encodeURIComponent(typed));
  } else if (event.key === 'Escape') {
    event.preventDefault();
    closeEditor();
  }
});
// focus going elsewhere means the edit was abandoned, not confirmed
labelEditor.addEventListener('blur', closeEditor);
// the stage is resized under the editor whenever a dock opens or the window
// changes size, and the diagram is scaled to fit it, so the label moves
new ResizeObserver(placeEditor).observe(stage);

// The label under the pointer is the nearest text beneath it, and the element
// that owns it is the nearest ancestor mermaid gave an id or a data-id to.  The
// svg itself carries an id, but it names the render, not an element.
function labelUnder(node) {
  let holder = null;
  let owner = null;
  while (node && node !== stage && (!holder || !owner)) {
    if (!holder) {
      holder = (node.textContent || '').trim() ? node
        : node.querySelector('text, p, tspan');
    }
    if (!owner && node.id && node.tagName.toLowerCase() !== 'svg') owner = node;
    node = node.parentElement;
  }
  return { holder: holder, owner: owner };
}

stage.addEventListener('dblclick', function (event) {
  const found = labelUnder(event.target);
  if (!found.holder) return;
  const text = (found.holder.textContent || '').replace(/\\s+/g, ' ').trim();
  if (!text) return;
  const owner = found.owner;
  const id = owner ? (owner.getAttribute('data-id') || owner.id || '') : '';
  editTarget = found.holder;
  event.preventDefault();
  setTitle('edit', encodeURIComponent(JSON.stringify({ id: id, text: text })));
}, true);

window.__svg = '';

if (typeof mermaid === 'undefined' || window.__cdnFailed) {
  showBanner('error', 'Could not load mermaid from the CDN.\\n\\n' + '%(cdn)s' + '\\n\\nThe editor still works and exports are unaffected - only the preview needs a network connection.');
  setTitle('offline');
} else {
  mermaid.initialize({ startOnLoad: false, securityLevel: 'strict' });
  setTitle('ready');

  window.renderDiagram = async function (code) {
    if (!code || !code.trim()) {
      stage.innerHTML = '<p id="empty">Nothing to draw yet.</p>';
      window.__svg = '';
      mountEditor();
      showBanner('', '');
      setTitle('ok');
      clearStrayNodes();
      return;
    }
    const id = 'diagram-' + (counter++);
    clearStrayNodes();
    try {
      const { svg } = await mermaid.render(id, code);
      stage.innerHTML = svg;
      window.__svg = svg;
      mountEditor();
      showBanner('', '');
      setTitle('ok');
    } catch (err) {
      const message = (err && err.message) ? err.message : String(err);
      window.__svg = '';
      showBanner('error', 'Mermaid could not draw this diagram:\\n' + message);
      setTitle('error', message.replace(/\\s+/g, ' ').slice(0, 400));
    } finally {
      clearStrayNodes();
    }
  };
}
</script>
</body>
</html>
"""


def _page_html(dark: bool) -> str:
    return _PAGE % {
        "cdn": MERMAID_CDN,
        "prefix": _TITLE_PREFIX,
        "background": "#1e1f22" if dark else "#ffffff",
        "foreground": "#e6e6e6" if dark else "#1f2328",
    }


class PreviewPane(QWidget):
    """Shows the rendered diagram, and reports whether rendering worked."""

    #: ``(ok, message)`` - emitted after every render attempt
    rendered = pyqtSignal(bool, str)

    #: ``(element_id, text)`` - a label in the diagram was double clicked
    edit_requested = pyqtSignal(str, str)

    #: the text typed over the label the window was last asked about
    edit_committed = pyqtSignal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._dark = False
        self._current = ""
        self._dirty = False
        self._ready = False
        self._view: QWebEngineView | None = None
        self._fallback_page: Path | None = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        if WEBENGINE_ERROR is None:
            self._init_web_view(layout)
        else:
            layout.addWidget(_fallback_widget(self, WEBENGINE_ERROR))

    def _init_web_view(self, layout: QVBoxLayout) -> None:
        assert QWebEngineView is not None and QWebEngineSettings is not None
        view = QWebEngineView(self)
        settings = view.settings()
        settings.setAttribute(QWebEngineSettings.WebAttribute.JavascriptEnabled, True)
        settings.setAttribute(
            QWebEngineSettings.WebAttribute.LocalContentCanAccessRemoteUrls, True
        )
        settings.setAttribute(
            QWebEngineSettings.WebAttribute.LocalContentCanAccessFileUrls, True
        )
        view.page().titleChanged.connect(self._on_title_changed)
        self._view = view
        layout.addWidget(view)
        self._load()

    # -- internals --------------------------------------------------------- #

    def _load(self) -> None:
        if self._view is None:
            return
        self._ready = False
        self._view.setHtml(_page_html(self._dark), QUrl("https://cdn.jsdelivr.net/"))

    def _flush(self) -> None:
        """Send the current source to the page if it is loaded and out of date."""
        if self._view is None or not self._ready or not self._dirty:
            return
        self._dirty = False
        payload = json.dumps(self._current)
        self._view.page().runJavaScript(f"window.renderDiagram({payload});")

    def _on_title_changed(self, title: str) -> None:
        if not title.startswith(_TITLE_PREFIX):
            return
        # the page sends ``<prefix><status>#<sequence>[:<detail>]``
        head, _, detail = title[len(_TITLE_PREFIX) :].partition(":")
        status = head.partition("#")[0]

        if status == "ready":
            self._ready = True
            self._flush()
            self.rendered.emit(True, "")
        elif status == "ok":
            self.rendered.emit(True, "")
        elif status == "error":
            self.rendered.emit(False, detail or "mermaid could not draw this diagram")
        elif status == "offline":
            self.rendered.emit(False, "mermaid could not be loaded from the CDN")
        elif status == "edit":
            self._on_edit_requested(detail)
        elif status == "edit-commit":
            self.edit_committed.emit(unquote(detail))

    def _on_edit_requested(self, detail: str) -> None:
        """Report the label a double click landed on, as ``(id, text)``."""
        try:
            clicked = json.loads(unquote(detail))
        except ValueError:
            return
        if isinstance(clicked, dict):
            self.edit_requested.emit(
                str(clicked.get("id", "")), str(clicked.get("text", ""))
            )

    # -- public API -------------------------------------------------------- #

    @property
    def is_dark(self) -> bool:
        return self._dark

    def set_dark(self, dark: bool) -> None:
        """Reload the page with a matching background, then redraw."""
        if dark == self._dark:
            return
        self._dark = dark
        self._dirty = True
        self._load()

    def set_source(self, code: str) -> None:
        """Render ``code``. Safe to call before the page has finished loading."""
        self._current = code
        self._dirty = True
        if self._view is None:
            self.rendered.emit(
                False,
                "the embedded preview is unavailable; use Redraw to open the diagram "
                "in your browser",
            )
            return
        self._flush()

    def write_preview_page(self) -> Path:
        """Write a standalone page for the current diagram and return its path."""
        target = Path(tempfile.gettempdir()) / "diagram-maker-preview.html"
        target.write_text(standalone_html(self._current), encoding="utf-8")
        self._fallback_page = target
        return target

    def open_in_browser(self) -> None:
        """Show the current diagram in the desktop's browser instead."""
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.write_preview_page())))

    def set_zoom(self, factor: float) -> None:
        if self._view is not None:
            self._view.setZoomFactor(max(0.25, min(4.0, factor)))

    def zoom(self) -> float:
        return self._view.zoomFactor() if self._view is not None else 1.0

    def refresh(self) -> None:
        """Re-render the last diagram, e.g. after a failed CDN fetch."""
        self._dirty = True
        if self._view is None:
            self.open_in_browser()
        elif self._ready:
            self._flush()
        else:
            self._load()

    def evaluate(self, script: str, callback) -> None:
        """Run ``script`` in the preview page and hand its value to ``callback``.

        ``script`` must be an expression; use an IIFE for anything longer.
        """

        def receive(value: object) -> None:
            callback(value)

        if self._view is None:
            receive(None)
            return
        self._view.page().runJavaScript(script, receive)

    def edit_text(self, text: str) -> None:
        """Open the editor over the label that was double clicked.

        Called with the text the *document* holds, which is not necessarily what
        the diagram shows: mermaid reformats labels, and editing the rendered
        version of one would lose the original.
        """
        if self._view is None:
            return
        self._view.page().runJavaScript(f"window.showLabelEditor({json.dumps(text)});")

    def svg(self, callback) -> None:
        """Hand the last rendered SVG to ``callback`` (called on the GUI thread)."""

        def receive(value: object) -> None:
            callback(value if isinstance(value, str) else "")

        self.evaluate("window.__svg || '';", receive)

    def save_svg(self, path: str | Path, callback=None) -> None:
        """Write the rendered SVG to ``path`` once the page hands it over."""

        def write(value: str) -> None:
            wrote = False
            message = "the diagram has not been rendered yet"
            if value:
                try:
                    Path(path).write_text(value, encoding="utf-8")
                    wrote, message = True, str(path)
                except OSError as error:
                    message = str(error)
            if callback is not None:
                callback(wrote, message)

        self.svg(write)


def _fallback_widget(panel: PreviewPane, error: str) -> QWidget:
    """Explain why there is no embedded preview, and offer a way around it."""
    widget = QWidget()
    layout = QVBoxLayout(widget)
    layout.setContentsMargins(28, 28, 28, 28)
    layout.setSpacing(12)

    heading = QLabel("The embedded preview is unavailable")
    heading_font = heading.font()
    heading_font.setPointSize(heading_font.pointSize() + 3)
    heading_font.setBold(True)
    heading.setFont(heading_font)

    detail = QLabel(
        "QtWebEngine could not be loaded on this machine, so diagrams cannot be "
        "drawn inside this window.<br><br>"
        f"<code>{html.escape(error)}</code><br><br>"
        "On Debian or Ubuntu the missing system libraries come from:<br>"
        f"<code>sudo apt install {' '.join(LINUX_PACKAGES)}</code><br><br>"
        "Everything else keeps working: the mermaid source, the exports and the "
        "document format are unaffected."
    )
    detail.setWordWrap(True)
    detail.setTextFormat(Qt.TextFormat.RichText)
    detail.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)

    open_button = QPushButton("Open the diagram in a browser")
    open_button.clicked.connect(panel.open_in_browser)

    layout.addWidget(heading)
    layout.addWidget(detail)
    layout.addWidget(open_button, 0, Qt.AlignmentFlag.AlignLeft)
    layout.addStretch(1)
    return widget


def standalone_html(code: str, title: str = "diagram") -> str:
    """A self-contained page that renders one diagram, for sharing or previewing."""
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>{html.escape(title)}</title>
<style>
  body {{ margin: 0; padding: 24px; font: 16px/1.5 system-ui, sans-serif; background: #fff; }}
  pre.mermaid {{ background: none; border: none; }}
</style>
</head>
<body>
<pre class="mermaid">{html.escape(code)}</pre>
<script src="{MERMAID_CDN}"></script>
<script>mermaid.initialize({{ startOnLoad: true }});</script>
</body>
</html>
"""
