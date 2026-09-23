"""Render diagrams built from awkward-but-plausible input and report what breaks.

The samples in ``render_check.py`` are all tidy.  Real users type colons in task
names, spaces in class names, quotes in labels.  This script feeds those through
the generators and renders the result with real mermaid, so a generator gap
shows up here instead of in the app.

Usage::

    uv run python scripts/edge_check.py        # writes build/edge_check.html

Serve ``build/`` over HTTP and open the page; ``window.__results`` lists each
case, and ``#results`` lists the failures.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from diagram_maker.document import DiagramDocument, sample  # noqa: E402
from diagram_maker.generators import generate  # noqa: E402

MERMAID_VERSION = "12.0.0"
CDN = f"https://cdn.jsdelivr.net/npm/mermaid@{MERMAID_VERSION}/dist/mermaid.min.js"

PAGE = """<!doctype html>
<html lang="en">
<head><meta charset="utf-8"><title>edge cases</title>
<style>
  body {{ font: 13px/1.4 system-ui, sans-serif; margin: 0; padding: 12px; }}
  pre#results {{ background: #101418; color: #d7e0ea; padding: 10px; }}
  pre#results.ok {{ background: #12351f; }}
  .case {{ font-family: monospace; white-space: pre-wrap; margin: 4px 0; padding: 4px 6px; }}
  .case.bad {{ background: #fff0f0; color: #a01020; }}
</style>
</head>
<body>
<script src="{cdn}"></script>
<script>
const cases = {payload};
// A handful of diagrams send mermaid's layout into a long spin - a layer stack
// that runs left to right took twenty seconds, and one case never answered at
// all - so each render is on the clock.  Without this the page simply stops
// partway through and looks like a broken case rather than a slow one.
const LIMIT_MS = 8000;
mermaid.initialize({{ startOnLoad: false }});
(async () => {{
  const results = [];
  // the page says what it has done as it goes: mermaid's layout can block the
  // thread for a minute on one case, and a page that only reports at the end
  // looks simply broken while that happens
  const pre = document.createElement('pre');
  pre.id = 'results';
  document.body.appendChild(pre);
  const flag = r => (r.ok ? (r.slow ? 'SLOW ' : 'ok   ') : 'FAIL ');
  const line = r => flag(r) + String(r.seconds).padStart(6) + 's  ' + r.name + (r.ok ? '' : '  <- ' + r.error);
  for (let i = 0; i < cases.length; i++) {{
    const c = cases[i];
    const started = Date.now();
    try {{
      const outcome = await Promise.race([
        mermaid.render('edge-' + i, c.code).then(() => 'ok'),
        new Promise(res => setTimeout(() => res('slow'), LIMIT_MS))
      ]);
      const seconds = Math.round((Date.now() - started) / 100) / 10;
      results.push({{ name: c.name, ok: true, slow: outcome === 'slow', seconds: seconds }});
    }} catch (err) {{
      results.push({{ name: c.name, ok: false, error: String(err && err.message || err) }});
      // a failed render leaves mermaid's own error graphic on the body, and it
      // would sit there for every case that follows
      for (const node of Array.from(document.body.children)) {{
        if (node.tagName !== 'SCRIPT' && node !== pre) node.remove();
      }}
    }}
    pre.textContent += line(results[results.length - 1]) + '\\n';
  }}
  window.__results = results;
  if (results.every(r => r.ok)) pre.className = 'ok';
  const blown = results.filter(r => !r.ok).length;
  const slow = results.filter(r => r.slow).length;
  document.title = blown ? 'FAILURES' : (slow ? 'ALL OK, ' + slow + ' SLOW' : 'ALL OK');
}})();
</script>
</body>
</html>
"""


def edited(kind: str, group: str, index: int, **fields: Any) -> DiagramDocument:
    """A sample with one element's fields replaced by awkward values.

    The position argument is called ``group`` rather than ``section`` because
    gantt and timeline elements have a field of that name.
    """
    doc = sample(kind)
    doc.sections[group][index].update(fields)
    return doc


def with_options(kind: str, **options: Any) -> DiagramDocument:
    doc = sample(kind)
    doc.options.update(options)
    return doc


def added(kind: str, group: str, **fields: Any) -> DiagramDocument:
    doc = sample(kind)
    doc.sections[group].append(fields)
    return doc


def fielded(kind: str, group: str, index: int, fields: dict[str, Any]) -> DiagramDocument:
    """Like :func:`edited`, for a field named after one of its parameters.

    An architecture service has a ``group`` field, which cannot be passed as a
    keyword to :func:`edited` because that is what its own argument is called.
    """
    doc = sample(kind)
    doc.sections[group][index].update(fields)
    return doc


def group_of(kind: str, heading: str, *indexes: int, **options: Any) -> DiagramDocument:
    """A sample whose numbered rows share a heading, and options of its own."""
    doc = sample(kind)
    for index in indexes:
        doc.sections["layers"][index]["heading"] = heading
    doc.options.update(options)
    return doc


#: (case name, document builder)
CASES: list[tuple[str, Callable[[], DiagramDocument]]] = [
    # -- flowchart ---------------------------------------------------------- #
    ("flowchart: quotes and brackets in a label",
     lambda: edited("flowchart", "nodes", 0, label='He said "hi" [ok] {#1}')),
    ("flowchart: backslash and percent in a label",
     lambda: edited("flowchart", "nodes", 0, label=r"C:\temp 50% <done>")),
    ("flowchart: the word end as a label",
     lambda: edited("flowchart", "nodes", 0, label="end")),
    ("flowchart: hostile node id",
     lambda: edited("flowchart", "nodes", 0, id="my node-1!")),
    ("flowchart: raw css in the style field",
     lambda: edited("flowchart", "nodes", 0, style="fill:#f9f,stroke:#333,stroke-width:2px")),
    ("flowchart: quotes in an edge label",
     lambda: edited("flowchart", "edges", 1, label='yes: "maybe"')),
    ("flowchart: quotes in a subgraph name",
     lambda: edited("flowchart", "nodes", 2, container='Fulfilment "team"')),
    ("flowchart: unicode label",
     lambda: edited("flowchart", "nodes", 0, label="Start \u2192 \u30c6\u30b9\u30c8")),

    # -- sequence ----------------------------------------------------------- #
    ("sequence: colon in message text",
     lambda: edited("sequence", "messages", 0, text="Note: place order")),
    ("sequence: parens and quotes in a participant",
     lambda: edited("sequence", "participants", 0, label='Alice "the admin" (ops)')),
    ("sequence: end in message text",
     lambda: edited("sequence", "messages", 0, text="end loop now")),
    ("sequence: colon in a note",
     lambda: edited("sequence", "notes", 0, text="Retries: twice")),

    # -- class -------------------------------------------------------------- #
    ("class: space in the class name",
     lambda: edited("class", "classes", 0, name="Order Line")),
    ("class: generics in the class name",
     lambda: edited("class", "classes", 1, name="List<Int>")),
    ("class: braces in an attribute",
     lambda: edited("class", "classes", 2, attributes="+meta : Map<string,int>")),
    ("class: colon in a relation label",
     lambda: edited("class", "relations", 0, label="owns: exactly one")),
    ("class: interface stereotype",
     lambda: edited("class", "classes", 0, stereotype="interface")),

    # -- er ----------------------------------------------------------------- #
    ("er: braces in a column",
     lambda: edited("er", "entities", 0, attributes='string meta {json}\nstring name')),
    ("er: quoted comment in a column",
     lambda: edited("er", "entities", 1, attributes='int qty PK "the "qty" column"')),
    ("er: spaces in an entity name",
     lambda: edited("er", "entities", 0, name="Order Line")),

    # -- use case ----------------------------------------------------------- #
    ("usecase: stereotype with a space",
     lambda: edited("usecase", "usecases", 1, stereotype="Core Feature")),
    ("usecase: angle brackets in a label",
     lambda: edited("usecase", "usecases", 1, label="Checkout <<core>>")),
    ("usecase: quotes in an actor label",
     lambda: edited("usecase", "actors", 0, label='Customer "vip"')),
    ("usecase: space in a boundary id",
     lambda: edited("usecase", "boundaries", 0, id="my ordering")),

    # -- gantt -------------------------------------------------------------- #
    ("gantt: colon in a task name",
     lambda: edited("gantt", "tasks", 0, name="Design: phase 1")),
    ("gantt: colon in a section name",
     lambda: edited("gantt", "tasks", 0, section="Phase 1: design")),
    ("gantt: comma in a task name",
     lambda: edited("gantt", "tasks", 0, name="Design, review")),

    # -- timeline ----------------------------------------------------------- #
    ("timeline: colon in the event text",
     lambda: edited("timeline", "events", 0, text="Release: v12")),

    # -- mindmap ------------------------------------------------------------ #
    ("mindmap: colon in a label",
     lambda: edited("mindmap", "nodes", 1, label="Input: forms")),
    ("mindmap: parens in a plain label",
     lambda: edited("mindmap", "nodes", 2, label="Forms (draft)")),
    ("mindmap: brackets in a shaped label",
     lambda: edited("mindmap", "nodes", 1, label="Input [raw]")),

    # -- pie / quadrant / xychart ------------------------------------------- #
    ("pie: quote in a label",
     lambda: edited("pie", "slices", 0, label='He said "hi"')),
    ("quadrant: comma in a point name",
     lambda: edited("quadrant", "points", 0, name="Campaign A, phase 2")),
    ("quadrant: colon in a point name",
     lambda: edited("quadrant", "points", 0, name="Campaign: A")),
    ("xychart: category with a space",
     lambda: with_options("xychart", categories="jan 2026, feb 2026, mar 2026")),
    ("xychart: negative values",
     lambda: with_options("xychart", y_min=-100, y_max=100,
                          categories="a, b, c")),
    ("xychart: comma inside a value list is fine",
     lambda: edited("xychart", "series", 0, values="1, 2, 3, 4, 5, 6")),

    # -- architecture ------------------------------------------------------- #
    ("architecture: brackets in a title",
     lambda: edited("architecture", "services", 0, title="Laptop [work]")),
    ("architecture: quotes and colons in a title",
     lambda: edited("architecture", "services", 0, title='Ops: "night shift"')),
    ("architecture: hostile service id",
     lambda: edited("architecture", "services", 0, id="my laptop-1!")),
    ("architecture: icon pack name",
     lambda: edited("architecture", "services", 0, icon="logos:aws-lambda")),
    ("architecture: an unknown icon",
     lambda: edited("architecture", "services", 0, icon="not-an-icon")),
    ("architecture: service in an undeclared group",
     lambda: fielded("architecture", "services", 0, {"group": "nowhere"})),
    ("architecture: nested group whose parent comes later",
     lambda: edited("architecture", "groups", 0, parent="data")),
    ("architecture: connection to an undeclared service",
     lambda: edited("architecture", "edges", 0, target="ghost")),
    ("architecture: connection with no ends",
     lambda: edited("architecture", "edges", 0, source="", target="")),
    ("architecture: a group named as an end",
     lambda: edited("architecture", "edges", 0, source="api")),
    ("architecture: every side in turn",
     lambda: edited("architecture", "edges", 0, source_side="T", target_side="B")),
    ("architecture: the group marker on a service in a group",
     lambda: edited("architecture", "edges", 2, source_group=True, target_group=True)),
    ("architecture: the group marker on a service outside one",
     lambda: edited("architecture", "edges", 0, source_group=True)),
    ("architecture: alignment of one member",
     lambda: edited("architecture", "aligns", 0, members="db")),
    ("architecture: alignment naming unknown members",
     lambda: edited("architecture", "aligns", 0, members="db ghost")),
    ("architecture: duplicate service id",
     lambda: added("architecture", "services", id="db", title="Twice", icon="server")),
    ("architecture: junction with no group",
     lambda: fielded("architecture", "junctions", 0, {"group": ""})),
    # -- layers -------------------------------------------------------------- #
    ("layers: html in a bullet",
     lambda: edited("layers", "columns", 3, items="<b>bold</b> bullet\nplain")),
    ("layers: quotes and colons in a bullet",
     lambda: edited("layers", "columns", 3, items='Says: "hi"\nsecond')),
    ("layers: bullets that are already list items",
     lambda: edited("layers", "columns", 3, items="- dash item\n* star item\n• dot item")),
    ("layers: ampersand and angle brackets",
     lambda: edited("layers", "columns", 3, items="R&D <100 ms\nx > y")),
    ("layers: a column in an undeclared layer",
     lambda: edited("layers", "columns", 0, layer="Nowhere")),
    ("layers: a layer with no columns",
     lambda: added("layers", "layers", title="Empty layer")),
    ("layers: a column with a heading and no bullets",
     lambda: edited("layers", "columns", 3, items="")),
    ("layers: a column with nothing at all",
     lambda: edited("layers", "columns", 3, title="", items="")),
    ("layers: a repeated layer title",
     lambda: added("layers", "layers", title="Data Services")),
    ("layers: a hostile layer title",
     lambda: edited("layers", "layers", 0, title='Portal "v2" [beta]')),
    ("layers: a hostile column heading",
     lambda: edited("layers", "columns", 1, title="Compute & <storage>")),
    ("layers: unicode bullets",
     lambda: edited("layers", "columns", 3, items="\u30b5\u30fc\u30d3\u30b9\n\u30ab\u30bf\u30ab\u30ca")),
    ("layers: a stack that runs left to right",
     lambda: with_options("layers", direction="LR")),
    ("layers: a label width of zero",
     lambda: with_options("layers", width=0)),
    # a heading wraps the layers that carry it, one after another, in a panel
    ("layers: two layers sharing a heading",
     lambda: group_of("layers", "Platform", 1, 2)),
    ("layers: a heading on one layer alone",
     lambda: group_of("layers", "Platform", 1)),
    ("layers: a heading that comes back further down",
     lambda: group_of("layers", "Platform", 1, 3)),
    ("layers: a grouped layer that is split into columns",
     lambda: group_of("layers", "Platform", 1, 2, 3)),
    ("layers: a heading with quotes and brackets",
     lambda: group_of("layers", 'Ops "night" [core]', 1, 2)),
    ("layers: a heading over a stack that runs left to right",
     lambda: group_of("layers", "Platform", 1, 2, 3, direction="LR")),
    ("layers: a heading on every layer",
     lambda: group_of("layers", "Platform", 0, 1, 2, 3, 4)),
]


def collect() -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for name, build in CASES:
        result = generate(build())
        items.append(
            {
                "name": name,
                "code": result.code,
                "warnings": [str(w) for w in result.warnings],
            }
        )
    return items


def main() -> None:
    items = collect()
    out = ROOT / "build" / "edge_check.html"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(PAGE.format(cdn=CDN, payload=json.dumps(items, ensure_ascii=False)),
                   encoding="utf-8")
    print(f"wrote {out}\n{len(items)} cases\n")
    for item in items:
        flag = "!" if item["warnings"] else " "
        print(f" {flag} {item['name']}")


if __name__ == "__main__":
    main()
