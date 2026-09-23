# Diagram Maker

A desktop tool for building diagrams visually — like Visio, but every diagram is
[Mermaid](https://mermaid.js.org/). You assemble a diagram from forms, and the app
generates the mermaid source, renders it live, and exports it as `.mmd`, `.html` or
`.svg`.

Thirteen diagram types, all rendered by Mermaid 12.

## Requirements

- Python 3.14 (see `.python-version`)
- A desktop session — this is a Qt application
- Network access for the live preview, which loads mermaid from jsdelivr.
  Everything else, including all exports, works offline.

The embedded preview needs QtWebEngine, which in turn needs a few system
libraries. On Debian or Ubuntu:

```bash
sudo apt install libasound2t64 libxcomposite1 libxdamage1 libxrandr2 libxtst6 libxfixes3
```

Without them the app still starts: the preview pane explains what is missing and
offers to open the diagram in your browser instead.

## Install and run

```bash
uv sync
uv run diagram-maker
```

On Windows with Smart App Control turned on, `uv run diagram-maker` can fail with
`An Application Control policy has blocked this file. (os error 4551)`. Nothing is
wrong with the app: the launcher `uv` writes into `.venv\Scripts` is unsigned, so
Windows refuses to start it. Run the module instead — that goes through the signed
interpreter:

```bash
uv run python -m diagram_maker
```

## Diagram types

| Type | Key | What it draws |
| --- | --- | --- |
| Flowchart | `flowchart` | Nodes, shaped boxes, subgraphs, labelled edges |
| Sequence | `sequence` | Participants, messages, notes |
| Class | `class` | UML classes, attributes, methods, relations |
| Entity relationship | `er` | Entities, columns, cardinality |
| Use case | `usecase` | Actors, use cases, system boundaries, include/extend |
| Mindmap | `mindmap` | Indented tree (level 1 is the root) |
| Layer stack | `layers` | Panels of bullet points, one layer above the next |
| Gantt | `gantt` | Sections, tasks, dependencies, milestones |
| Timeline | `timeline` | Sections and dated events |
| Pie chart | `pie` | Slices with values |
| Quadrant chart | `quadrant` | Points on two axes, four labelled quadrants |
| XY chart | `xychart` | Bar and line series over categories |
| Architecture | `architecture` | Services inside groups, wired port to port, with junctions |

Every type shares the same options: a title, a mermaid theme and a
`classic` / `neo` / `handDrawn` look.

A layer stack is a flowchart underneath. Its layers are listed in the order they
stack, and its columns name the layer they belong to, which is what says where
each one is drawn: a column with a title of its own is a box, and a layer with
two or more of them becomes a panel with those boxes side by side. Give a layer a
heading and every layer that shares it, one after another, is drawn inside one
panel named by that heading.

Two of them have their own ideas about text. An architecture diagram has no title
of its own, so mermaid ignores the one the title option writes into the source
and nothing appears above the picture. And an entity column is drawn as separate
cells, so clicking one in the preview edits that cell rather than the whole
column.

## Using it

The window has three parts:

- **Structure** (left) — the diagram type picker, then one group per element
  collection (Nodes, Edges, ...). Use the buttons underneath or the Edit menu to
  add, duplicate, reorder and remove elements. Double-click a group to add to it.
- **Properties** (right) — the fields of whatever is selected. "Diagram settings"
  at the top of the tree holds the whole-diagram options.
- **Preview** (centre) — the rendered diagram, redrawn as you type. Double-click
  any label to edit it where it sits: the box opens over the text, Enter keeps
  the change, Escape or clicking away drops it, and the element is selected in
  the tree meanwhile. What gets edited is what you clicked — inside a class or
  an entity box that is one member line, or one cell of a column, rather than
  the whole list. Mermaid names most of what it draws after the ids it was
  given, so a click is matched to an element by id first and by the text it
  draws second — which covers the mindmaps and charts that carry no ids.
- **Mermaid source** (bottom) — the generated code, read-only. The visual editor
  is the only editor; this pane is for reading, copying and sanity-checking.

If an element cannot be drawn — a node without an id, an edge pointing at a node
that does not exist, a gantt task with no start date — it is left out and a
warning appears above the source pane. The rest of the diagram still renders.

If mermaid itself rejects the generated source, the preview shows a dismissible
red banner with the parse error and the offending line, and the status bar
repeats it. Dismissing hides the message until the next failed render; the rest
of the diagram and every export stay usable.

### Keyboard shortcuts

| Shortcut | Action |
| --- | --- |
| `Ctrl+N` / `Ctrl+O` / `Ctrl+S` | New / open / save |
| `Ctrl+Return` | Add an element |
| `Ctrl+D` | Duplicate the selected element |
| `Del` | Remove the selected element |
| `Alt+Up` / `Alt+Down` | Move an element within its group |
| `Ctrl+E` | Export mermaid (`.mmd`) |
| `Ctrl+Shift+E` | Export HTML |
| `Ctrl+Alt+S` | Export SVG |
| `F5` | Redraw the preview |
| `Ctrl+Shift+C` | Copy the mermaid source |

## Files

| Format | Contents |
| --- | --- |
| `*.diagram.json` | The document: diagram type, options and every element. This is what Save writes. |
| `*.mmd` | Just the generated mermaid source. |
| `*.html` | A standalone page that renders the diagram with mermaid from a CDN. |
| `*.svg` | The rendered picture, taken from the preview. |

## Command line

```bash
uv run diagram-maker                       # start with a sample flowchart
uv run diagram-maker my.diagram.json       # open a saved document
uv run diagram-maker --sample usecase      # start from the use case sample
uv run diagram-maker --export out.mmd      # write mermaid and exit, no GUI
uv run diagram-maker --list                # list the diagram types
```

## How it fits together

```
src/diagram_maker/
    specs.py       one DiagramSpec per diagram type: options, sections, fields
    document.py    DiagramDocument - plain-data document plus samples
    generators.py  document -> mermaid source, with per-row warnings
    preview.py     QtWebEngine preview page, and the browser fallback
    shapes.py      outline icons, drawn for the shape dropdowns
    style.py       the mermaid style statement, read and written as properties
    window.py      the main window, built from the specs
    icon.ico       the window and taskbar icon, drawn by packaging/make_icon.py
    __init__.py    main() and the headless CLI
```

`specs.py` is the single source of truth. The property forms in `window.py` are
generated from it and `generators.py` reads the same definitions, so a diagram
type is never described twice. Adding a type means adding one `DiagramSpec`, one
generator function and one sample.

## Development

```bash
uv run python scripts/smoke_test.py     # drives the whole UI offscreen, all types
uv run python scripts/render_check.py   # writes build/render_check.html
uv run python scripts/edge_check.py     # writes build/edge_check.html
```

Serve `build/` over HTTP before opening the generated pages: the VS Code browser
refuses `file://` URLs outside a trusted folder.

`smoke_test.py` switches through every diagram type, builds a property form for
every element, exercises add/duplicate/reorder/remove, checks the preview and the
SVG export, feeds it a deliberately broken diagram, and round-trips a save and
load. It passes in either preview mode.

`render_check.py` writes a page that renders every sample with real mermaid, so
you can confirm the generated syntax is still valid — including the newest
diagram types, which the docs describe before most people have used them.

`edge_check.py` does the same for awkward-but-plausible input: colons in task
names, spaces in entity names, quotes inside labels, braces inside columns. Every
case there failed at least once during development, so it is the regression net
for the generators. Each case is on an eight-second clock, because mermaid's
layout occasionally spends tens of seconds on a diagram it can draw perfectly
well; `#results` lists the time every case took, and flags the slow ones.

## Windows installer

`scripts/build_installer.py` freezes the application with PyInstaller and wraps
it in an Inno Setup installer:

```powershell
uv sync --extra packaging
uv run python scripts/build_installer.py
```

It takes the version from `pyproject.toml` and then works through:

| Step | Result |
| --- | --- |
| icon | `src/diagram_maker/icon.ico`, drawn by `packaging/make_icon.py` if it is missing |
| freeze | `packaging/diagram-maker.spec` into `dist\Diagram Maker\` - about 430 MB, most of it QtWebEngine |
| checks | the frozen `.exe` writes a diagram through `--export`, then survives 12 s offscreen with a real window and preview |
| installer | `packaging/diagram-maker.iss` into `dist\DiagramMaker-<version>-setup.exe` - about 120 MB |

Flags worth knowing: `--skip-freeze` recompiles the installer around the bundle
already in `dist\`, `--console` produces a console build when a frozen app is
misbehaving, `--no-run` skips the two startup checks, and `--zip` also writes
`dist\DiagramMaker-<version>-portable-x64.zip`.

What the installer sets up:

- installs to `%LOCALAPPDATA%\Programs\Diagram Maker` without needing an
  administrator; the choice on the first page elevates and uses Program Files
  for all users instead
- a Start menu entry, plus a desktop shortcut if that task is ticked
- an optional `.diagram.json` association, unticked by default
- an uninstaller in Apps and features

Inno Setup is the only outside tool needed. `winget install -e --id JRSoftware.InnoSetup`
installs it; without it the build stops after the portable zip and says so.

The bundles are unsigned, so SmartScreen warns before the installer runs and
Smart App Control refuses to run it at all. It can also refuse the build's own
checks, which start the frozen application as soon as it is written: the build
says which check Windows declined, skips the rest, and still compiles the
installer. Sign the frozen app first if you have a certificate, so the payload
carries its signature too:

```powershell
signtool sign /fd SHA256 /tr http://timestamp.digicert.com /td SHA256 "dist\Diagram Maker\Diagram Maker.exe"
# then build the installer
```

## Notes

- Mermaid is pinned to `12.0.0` in `preview.py` and `render_check.py` so a new
  mermaid release cannot silently change how existing documents render. The use
  case diagram type needs 12.x: it is the `usecase-beta` keyword.
- `pyqt6-tools` is deliberately **not** a dependency. It is abandoned, pins
  `pyqt6==6.4.2`, and pulls `pyqt6-plugins`, which only ships wheels up to
  CPython 3.11 — so it can never resolve on Python 3.12+. Use PyQt6's own
  compiler for `.ui` files: `python -m PyQt6.uic.pyuic -o form.py form.ui`.
  For the Qt Designer GUI, install the optional extra: `uv sync --extra designer`.
- The app depends only on PyQt6, PyQt6-WebEngine and the Python standard library.
  There is no data-wrangling or plotting dependency. PyInstaller arrives through
  the `packaging` extra but only ever runs on the build machine.
- The application folder is a onedir build rather than a single file: a onefile
  build unpacks the whole QtWebEngine stack next to the `.exe` on every start.
- `packaging/make_icon.py` draws `src/diagram_maker/icon.ico` from nothing but
  the standard library, because every shape is a signed distance function
  rasterised per size. Run it with `--preview build/icon-preview.png` to look at
  the result before shipping it. The window loads that file at run time, which
  is what the taskbar draws, and the build embeds the same file in the `.exe`.
- A layer stack writes its label width into the frontmatter as
  `flowchart.wrappingWidth`. Mermaid sizes a box from the text it can measure,
  not from the HTML it goes on to draw, so without that a bullet line is wrapped
  in the middle even when the panel has room for it. The option's floor is 300
  rather than mermaid's own 200: once it decides these lines have to be broken,
  a layout that takes two seconds starts taking a minute.
- The window icon alone is not enough on Windows: the taskbar takes a button's
  identity from the process's AppUserModelID, and an unset one is inherited from
  the executable, so a run from source would show Python's icon. `main()` claims
  `APP_ID` before anything else, and the installer writes the same string onto
  the shortcuts it creates. Keep the two in step.
