"""Render every sample diagram with mermaid in a real browser and report errors.

Usage::

    uv run python scripts/render_check.py          # writes build/render_check.html

Open the generated file in a browser (or use the VS Code browser tools) and read
the ``#results`` element: it lists one entry per diagram type with ``ok`` or the
mermaid parse error.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from diagram_maker.document import sample_all  # noqa: E402
from diagram_maker.generators import generate  # noqa: E402

MERMAID_VERSION = "12.0.0"
CDN = f"https://cdn.jsdelivr.net/npm/mermaid@{MERMAID_VERSION}/dist/mermaid.min.js"

HTML = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>mermaid render check</title>
<style>
  body {{ font: 14px/1.4 system-ui, sans-serif; margin: 0; padding: 16px; }}
  pre#results {{ background: #101418; color: #d7e0ea; padding: 12px; overflow: auto; }}
  pre#results.ok {{ background: #12351f; }}
  .diagram {{ border: 1px solid #d0d7de; border-radius: 6px; margin: 12px 0; padding: 8px; }}
  .diagram h2 {{ font-size: 13px; margin: 0 0 6px; color: #555; }}
  .diagram.error {{ border-color: #d1242f; background: #fff5f5; }}
  .error-text {{ color: #d1242f; white-space: pre-wrap; font-family: monospace; }}
</style>
</head>
<body>
<script src="{cdn}"></script>
<script>
const diagrams = {payload};

mermaid.initialize({{ startOnLoad: false }});

(async () => {{
  const results = [];
  const host = document.createElement('div');
  document.body.appendChild(host);

  for (let i = 0; i < diagrams.length; i++) {{
    const d = diagrams[i];
    const box = document.createElement('div');
    box.className = 'diagram';
    const heading = document.createElement('h2');
    heading.textContent = d.kind + ' (' + d.lines + ' lines)';
    box.appendChild(heading);
    host.appendChild(box);
    try {{
      const {{ svg }} = await mermaid.render('graph-' + i, d.code);
      const body = document.createElement('div');
      body.innerHTML = svg;
      box.appendChild(body);
      results.push({{ kind: d.kind, ok: true }});
    }} catch (err) {{
      const message = (err && err.message) ? err.message : String(err);
      box.className = 'diagram error';
      const pre = document.createElement('div');
      pre.className = 'error-text';
      pre.textContent = message;
      box.appendChild(pre);
      results.push({{ kind: d.kind, ok: false, error: message }});
    }}
  }}

  window.__results = results;
  const summary = document.createElement('pre');
  summary.id = 'results';
  summary.textContent = JSON.stringify(results, null, 1);
  if (results.every(r => r.ok)) summary.className = 'ok';
  document.body.insertBefore(summary, host);
  document.title = results.every(r => r.ok) ? 'ALL OK' : 'FAILURES';
}})();
</script>
</body>
</html>
"""


def collect() -> list[dict[str, object]]:
    payload: list[dict[str, object]] = []
    for kind, doc in sample_all():
        result = generate(doc)
        payload.append(
            {
                "kind": kind,
                "code": result.code,
                "lines": result.code.count("\n"),
                "warnings": [str(w) for w in result.warnings],
            }
        )
    return payload


def main() -> None:
    payload = collect()
    out = ROOT / "build" / "render_check.html"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        HTML.format(cdn=CDN, payload=json.dumps(payload, ensure_ascii=False)),
        encoding="utf-8",
    )

    print(f"wrote {out}")
    print(f"{len(payload)} diagrams\n")
    for item in payload:
        warnings = item["warnings"]
        flag = "!" if warnings else " "
        print(f" {flag} {item['kind']:<10} {item['lines']:>3} lines")
        for warning in warnings:  # type: ignore[union-attr]
            print(f"       {warning}")
    print("\n--- mermaid source ---")
    for item in payload:
        print(f"\n=== {item['kind']} ===")
        print(item["code"], end="")


if __name__ == "__main__":
    main()
