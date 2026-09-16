"""The editable document behind one diagram.

A document is deliberately plain data (``dict`` / ``list`` / scalars) so that it
maps onto JSON without any custom encoders, and so that both the UI and the
generators can consume it without importing Qt.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Iterator, Sequence

from .specs import LINES, SPECS, DiagramSpec, ItemSpec, get_spec

FILE_SUFFIX = ".diagram.json"

#: Bumped when the on-disk shape changes in a way that needs migration.
FORMAT_VERSION = 1


def _rows(*specs: tuple[Any, ...]) -> list[dict[str, Any]]:
    """Build a list of dicts from ``(key, value, key, value, ...)`` tuples."""
    items: list[dict[str, Any]] = []
    for spec in specs:
        items.append(dict(zip(spec[::2], spec[1::2])))
    return items


def _schema(item_spec: ItemSpec) -> tuple[str, ...]:
    """The field names of a section, used to decide whether rows can carry over."""
    return tuple(f.name for f in item_spec.fields)


def _collapsed(value: Any) -> str:
    """``value`` as the single line of text a diagram would draw for it."""
    return " ".join(str(value or "").split())


def _letters(value: str) -> str:
    """``value`` without the punctuation mermaid adds or drops when it draws."""
    return "".join(character for character in value if character.isalnum()).lower()


def _wordish(character: str) -> bool:
    return character.isalnum() or character == "_"


def _span_in(line: str, text: str) -> tuple[int, int] | None:
    """Where ``text`` sits in ``line`` as a word or phrase of its own.

    Bounded by characters that cannot be part of a word, so that clicking the
    ``id`` column of an entity does not land inside ``customerId``.
    """
    start = 0
    while (found := line.find(text, start)) >= 0:
        end = found + len(text)
        before = line[found - 1] if found else " "
        after = line[end] if end < len(line) else " "
        if not _wordish(before) and not _wordish(after):
            return found, end
        start = found + 1
    return None


@dataclass(frozen=True)
class TextTarget:
    """Where one piece of text drawn in the preview is kept.

    ``line`` is set when the diagram draws part of a multi-line field - a class
    member, an entity column - rather than the whole field, and ``span`` narrows
    that down to some characters of the line: an entity column is drawn as four
    cells, and clicking one of them edits that cell and not the column.
    """

    section: str
    index: int
    field: str
    line: int | None = None
    span: tuple[int, int] | None = None


@dataclass
class DiagramDocument:
    """Everything needed to regenerate one mermaid diagram."""

    kind: str
    options: dict[str, Any] = field(default_factory=dict)
    sections: dict[str, list[dict[str, Any]]] = field(default_factory=dict)

    # -- construction ------------------------------------------------------ #

    @classmethod
    def blank(cls, kind: str) -> DiagramDocument:
        spec = get_spec(kind)
        return cls(
            kind=kind,
            options={f.name: f.default for f in spec.options},
            sections={s.key: [] for s in spec.sections},
        )

    @classmethod
    def from_data(cls, data: dict[str, Any]) -> DiagramDocument:
        """Rebuild a document from untrusted JSON, coercing every value."""
        kind = str(data.get("kind") or "flowchart")
        if kind not in SPECS:
            kind = "flowchart"
        spec = get_spec(kind)
        doc = cls.blank(kind)

        for f in spec.options:
            if f.name in (data.get("options") or {}):
                doc.options[f.name] = f.coerce(data["options"][f.name])

        raw_sections = data.get("sections") or {}
        for item_spec in spec.sections:
            rows: list[dict[str, Any]] = []
            for raw in raw_sections.get(item_spec.key) or []:
                if not isinstance(raw, dict):
                    continue
                rows.append({f.name: f.coerce(raw.get(f.name, f.default)) for f in item_spec.fields})
            doc.sections[item_spec.key] = rows
        return doc

    # -- access ------------------------------------------------------------ #

    @property
    def spec(self) -> DiagramSpec:
        return get_spec(self.kind)

    def rows(self, key: str) -> list[dict[str, Any]]:
        return self.sections.setdefault(key, [])

    def option(self, name: str, default: Any = "") -> Any:
        return self.options.get(name, default)

    def items(self) -> Iterator[tuple[ItemSpec, int, dict[str, Any]]]:
        """Yield ``(section, index, row)`` for every element in the document."""
        for section in self.spec.sections:
            for index, row in enumerate(self.rows(section.key)):
                yield section, index, row

    def find_text(
        self,
        element_id: str,
        text: str,
        classes: Sequence[str] = (),
        order: int = 0,
    ) -> TextTarget | None:
        """Where the text a double click landed on is kept, or ``None``.

        Mermaid names what it draws after the ids it was handed, as
        ``diagram-0-flowchart-Ship-0``, so an id carrying a row's id is the
        strongest evidence - and the only thing that works when the drawn text
        has been reformatted.  Where mermaid offers no id at all (mindmaps,
        charts, gantt bars) the drawn text is matched against the field each
        section declares in :attr:`~diagram_maker.specs.ItemSpec.text_field`.

        Text that comes from one line of a multi-line field - a class member, an
        entity column - resolves to that line, and where the line is itself
        drawn in pieces (an entity column is four cells) to the piece that was
        clicked, which ``classes`` and ``order`` describe.
        """
        wanted = _collapsed(text)
        if not wanted:
            return None

        row = self._row_named_by(element_id) or self._row_drawing(wanted)
        if row is not None:
            section, index = row
            part = self._row_part(section, index, wanted, classes, order)
            if part is not None:
                return TextTarget(section, index, *part)
            return TextTarget(section, index, self.spec.section(section).text_field)

        # no row draws that text as a whole, but a line of one still might: a
        # note is drawn from a multi-line field under an id of mermaid's own
        for item_spec in self.spec.sections:
            for index in range(len(self.rows(item_spec.key))):
                part = self._row_part(item_spec.key, index, wanted, (), 0)
                if part is not None:
                    return TextTarget(item_spec.key, index, *part)
        return None

    def text_at(self, target: TextTarget) -> str:
        """The text ``target`` points at, or ``""`` once it has gone."""
        row = self._row(target.section, target.index)
        if row is None:
            return ""
        value = str(row.get(target.field, ""))
        if target.line is None:
            return value
        lines = value.splitlines()
        if not (0 <= target.line < len(lines)):
            return ""
        line = lines[target.line]
        if target.span is None:
            return line
        start, end = target.span
        return line[start:end]

    def set_text(self, target: TextTarget, text: str) -> bool:
        """Keep ``text`` at ``target``; returns whether anything changed."""
        row = self._row(target.section, target.index)
        if row is None:
            return False
        if target.line is None:
            if str(row.get(target.field, "")) == text:
                return False
            row[target.field] = text
            return True

        value = str(row.get(target.field, ""))
        # splitlines drops a trailing newline, which is not ours to drop
        trailing = "\n" if value.endswith("\n") else ""
        lines = value.splitlines()
        if not (0 <= target.line < len(lines)):
            return False
        line = lines[target.line]
        if target.span is None:
            if line == text:
                return False
            lines[target.line] = text
        else:
            start, end = target.span
            if line[start:end] == text:
                return False
            lines[target.line] = line[:start] + text + line[end:]
        row[target.field] = "\n".join(lines) + trailing
        return True

    def _row(self, section_key: str, index: int) -> dict[str, Any] | None:
        rows = self.rows(section_key)
        return rows[index] if 0 <= index < len(rows) else None

    def _row_named_by(self, element_id: str) -> tuple[str, int] | None:
        """The row whose id appears in ``element_id``, if there is one."""
        # the numbers are mermaid's own, and a row id that is a number would
        # otherwise match every element on the page
        parts = {
            part for part in (element_id or "").split("-") if part and not part.isdigit()
        }
        if not parts:
            return None
        for section in self.spec.sections:
            if not section.id_field:
                continue
            for index, row in enumerate(self.rows(section.key)):
                if str(row.get(section.id_field, "")) in parts:
                    return section.key, index
        return None

    def _row_drawing(self, text: str) -> tuple[str, int] | None:
        """The row whose declared text field draws exactly ``text``."""
        for section in self.spec.sections:
            if not section.text_field:
                continue
            for index, row in enumerate(self.rows(section.key)):
                if _collapsed(row.get(section.text_field, "")) == text:
                    return section.key, index
        return None

    def _row_part(
        self,
        section_key: str,
        index: int,
        text: str,
        classes: Sequence[str],
        order: int,
    ) -> tuple[str, int, tuple[int, int] | None] | None:
        """The line of a multi-line field that ``text`` is drawn from, and where.

        Returns ``(field, line, span)``, with ``span`` left out when the whole
        line was clicked rather than part of it.
        """
        row = self._row(section_key, index)
        if row is None:
            return None
        section = self.spec.section(section_key)
        drawn = {
            field.name: str(row.get(field.name, "")).splitlines()
            for field in section.fields
            if field.kind == LINES
        }

        # what mermaid classed the label says which field it belongs to, and its
        # place among the labels classed the same way says which line that is -
        # so this is the pass that knows clicking one cell of an entity column
        # means that cell and not the other three
        for token, name in section.line_fields:
            lines = drawn.get(name, [])
            if token in classes and 0 <= order < len(lines):
                line = lines[order]
                span = _span_in(line, text)
                # a span covering the line is just the line
                if span == (0, len(line)):
                    span = None
                return name, order, span

        # failing that, go by the text: the whole line first, then a word or
        # phrase of it, then ignoring the punctuation mermaid adds when it draws
        for match in (
            lambda line: _collapsed(line) == text,
            lambda line: _span_in(line, text) is not None,
            lambda line: _letters(line) == _letters(text),
        ):
            for name, lines in drawn.items():
                for number, line in enumerate(lines):
                    if match(line):
                        span = None if _collapsed(line) == text else _span_in(line, text)
                        return name, number, span
        return None

    def set_kind(self, kind: str) -> None:
        """Switch diagram type.

        Rows are kept only for sections the new type shares *and* whose fields
        match exactly: several types have a ``relations`` section, but a class
        relation and an ER relationship have nothing in common.  Options the new
        type also has (title, theme, look) are preserved.
        """
        fresh = DiagramDocument.blank(kind)
        previous = self.spec
        for item_spec in fresh.spec.sections:
            old = previous.section(item_spec.key)
            if old is not None and _schema(old) == _schema(item_spec):
                fresh.sections[item_spec.key] = self.sections.get(item_spec.key, [])
        for name, value in self.options.items():
            if name in fresh.options:
                fresh.options[name] = value
        self.kind = kind
        self.options = fresh.options
        self.sections = fresh.sections

    def is_empty(self) -> bool:
        return not any(self.sections.values())

    # -- serialisation ----------------------------------------------------- #

    def to_data(self) -> dict[str, Any]:
        """A canonical, fully populated document, ready for JSON.

        Every field of every row is written out, so loading the result gives
        exactly the same document back - including for rows that were built
        with only a few keys set.
        """
        spec = self.spec
        options = {
            f.name: f.coerce(self.options.get(f.name, f.default)) for f in spec.options
        }
        sections: dict[str, list[dict[str, Any]]] = {}
        for item_spec in spec.sections:
            sections[item_spec.key] = [
                {f.name: f.coerce(row.get(f.name, f.default)) for f in item_spec.fields}
                for row in self.rows(item_spec.key)
            ]
        return {
            "version": FORMAT_VERSION,
            "kind": self.kind,
            "options": options,
            "sections": sections,
        }

    def to_json(self) -> str:
        return json.dumps(self.to_data(), indent=2, ensure_ascii=False)

    @classmethod
    def load(cls, path: str | Path) -> DiagramDocument:
        return cls.from_data(json.loads(Path(path).read_text(encoding="utf-8")))

    def save(self, path: str | Path) -> None:
        Path(path).write_text(self.to_json() + "\n", encoding="utf-8")

    def duplicate(self) -> DiagramDocument:
        return DiagramDocument.from_data(self.to_data())


# --------------------------------------------------------------------------- #
# sample documents
# --------------------------------------------------------------------------- #


def _flowchart() -> DiagramDocument:
    doc = DiagramDocument.blank("flowchart")
    doc.options["title"] = "Order intake"
    doc.options["direction"] = "TD"
    doc.sections["nodes"] = _rows(
        ("id", "Start", "label", "Order received", "shape", "Stadium"),
        ("id", "Check", "label", "In stock?", "shape", "Rhombus"),
        ("id", "Ship", "label", "Ship order", "shape", "Rectangle", "container", "Fulfilment"),
        ("id", "Back", "label", "Backorder", "shape", "Rectangle", "container", "Fulfilment"),
        ("id", "Done", "label", "Done", "shape", "Double circle"),
    )
    doc.sections["edges"] = _rows(
        ("source", "Start", "target", "Check"),
        ("source", "Check", "target", "Ship", "label", "yes"),
        ("source", "Check", "target", "Back", "label", "no"),
        ("source", "Ship", "target", "Done"),
        ("source", "Back", "target", "Done", "style", "Dotted  -.->"),
    )
    return doc


def _sequence() -> DiagramDocument:
    doc = DiagramDocument.blank("sequence")
    doc.options["autonumber"] = False
    doc.sections["participants"] = _rows(
        ("alias", "C", "label", "Customer", "kind", "actor"),
        ("alias", "S", "label", "Storefront", "kind", "participant"),
        ("alias", "P", "label", "Payments", "kind", "participant"),
    )
    doc.sections["messages"] = _rows(
        ("sender", "C", "receiver", "S", "text", "Place order"),
        ("sender", "S", "receiver", "P", "text", "Authorise card", "style", "Dashed arrow  -->>"),
        ("sender", "P", "receiver", "S", "text", "Approved", "style", "Dashed arrow  -->>"),
        ("sender", "S", "receiver", "C", "text", "Order confirmed"),
    )
    doc.sections["notes"] = _rows(
        ("text", "Retries twice on timeout", "placement", "over", "first", "S", "second", "P"),
    )
    return doc


def _class() -> DiagramDocument:
    doc = DiagramDocument.blank("class")
    doc.sections["classes"] = _rows(
        (
            "name", "Animal",
            "stereotype", "abstract",
            "attributes", "+name : String\n+age : int",
            "methods", "+makeSound() void",
        ),
        (
            "name", "Dog",
            "attributes", "+breed : String",
            "methods", "+fetch() void",
        ),
        ("name", "Owner", "attributes", "+name : String"),
    )
    doc.sections["relations"] = _rows(
        ("source", "Animal", "target", "Dog", "kind", "Inheritance  <|--"),
        ("source", "Owner", "target", "Animal", "kind", "Association  -->", "label", "owns",
         "target_card", "0..*"),
    )
    return doc


def _er() -> DiagramDocument:
    doc = DiagramDocument.blank("er")
    doc.sections["entities"] = _rows(
        (
            "name", "CUSTOMER",
            "attributes", 'string id PK "primary key"\nstring name\nstring email',
        ),
        (
            "name", "ORDER",
            "attributes", "string id PK\nstring customerId FK\ndate placedAt",
        ),
    )
    doc.sections["relations"] = _rows(
        ("left", "CUSTOMER", "right", "ORDER", "label", "places",
         "cardinality", "one to zero-or-more  ||--o{"),
    )
    return doc


def _usecase() -> DiagramDocument:
    doc = DiagramDocument.blank("usecase")
    doc.options["direction"] = "LR"
    doc.options["acc_title"] = "Online ordering use cases"
    doc.sections["boundaries"] = _rows(
        ("id", "ordering", "title", "Ordering system", "type", "package"),
    )
    doc.sections["actors"] = _rows(
        ("id", "Customer", "label", "Customer"),
        ("id", "Staff", "label", "Order staff", "variant", "hollow", "business", True,
         "stereotype", "Employee"),
    )
    doc.sections["usecases"] = _rows(
        ("id", "Browse", "label", "Browse products", "boundary", "ordering"),
        ("id", "Checkout", "label", "Checkout", "boundary", "ordering", "stereotype", "Core"),
        ("id", "Payment", "label", "Process payment", "boundary", "ordering"),
        ("id", "Review", "label", "Review order", "shape", "Rectangle"),
    )
    doc.sections["relations"] = _rows(
        ("source", "Customer", "target", "Browse", "kind", "Association  -->"),
        ("source", "Customer", "target", "Checkout", "kind", "Association  -->",
         "label", "places order"),
        ("source", "Checkout", "target", "Payment", "kind", "Include  ..> : include"),
        ("source", "Staff", "target", "Review", "kind", "Association  -->"),
    )
    doc.sections["notes"] = _rows(
        ("target", "Checkout", "text", "Validates the cart before payment"),
    )
    return doc


def _mindmap() -> DiagramDocument:
    doc = DiagramDocument.blank("mindmap")
    doc.sections["nodes"] = _rows(
        ("level", 1, "label", "Diagram tool", "shape", "Circle"),
        ("level", 2, "label", "Input", "shape", "Square"),
        ("level", 3, "label", "Forms", "shape", "Plain"),
        ("level", 3, "label", "Samples", "shape", "Plain"),
        ("level", 2, "label", "Output", "shape", "Square"),
        ("level", 3, "label", "Mermaid source", "shape", "Plain"),
        ("level", 3, "label", "Screenshots", "shape", "Plain"),
    )
    return doc


def _gantt() -> DiagramDocument:
    doc = DiagramDocument.blank("gantt")
    doc.options["title"] = "Diagram maker roadmap"
    doc.sections["tasks"] = _rows(
        ("section", "Design", "name", "Wireframes", "id", "wf", "start", "2026-01-05",
         "duration", "10d", "status", "done"),
        ("section", "Design", "name", "Visual language", "start", "after wf", "duration", "1w"),
        ("section", "Build", "name", "Flowchart editor", "id", "fc", "start", "after wf",
         "duration", "3w", "status", "active"),
        ("section", "Build", "name", "Mermaid export", "start", "after fc", "duration", "2w"),
        ("section", "Build", "name", "Public beta", "start", "after fc", "duration", "0d",
         "status", "milestone"),
    )
    return doc


def _timeline() -> DiagramDocument:
    doc = DiagramDocument.blank("timeline")
    doc.options["title"] = "Mermaid milestones"
    doc.sections["events"] = _rows(
        ("section", "Early", "period", "2014", "text", "First release"),
        ("section", "Early", "period", "2018", "text", "Mindmaps"),
        ("section", "Recent", "period", "2023", "text", "Architecture diagrams"),
        ("section", "Recent", "period", "2026", "text", "Use case diagrams", "extra", "v12"),
    )
    return doc


def _pie() -> DiagramDocument:
    doc = DiagramDocument.blank("pie")
    doc.options["title"] = "Diagrams created by type"
    doc.options["show_data"] = True
    doc.sections["slices"] = _rows(
        ("label", "Flowchart", "value", 42),
        ("label", "Sequence", "value", 27),
        ("label", "Class", "value", 15),
        ("label", "Mindmap", "value", 9),
        ("label", "Other", "value", 7),
    )
    return doc


def _quadrant() -> DiagramDocument:
    doc = DiagramDocument.blank("quadrant")
    doc.options.update(
        {
            "title": "Reach and engagement",
            "x_low": "Low reach",
            "x_high": "High reach",
            "y_low": "Low engagement",
            "y_high": "High engagement",
            "q1": "Expand",
            "q2": "Promote",
            "q3": "Re-evaluate",
            "q4": "Improve",
        }
    )
    doc.sections["points"] = _rows(
        ("name", "Campaign A", "x", 0.30, "y", 0.60),
        ("name", "Campaign B", "x", 0.45, "y", 0.23),
        ("name", "Campaign C", "x", 0.57, "y", 0.69),
        ("name", "Campaign D", "x", 0.78, "y", 0.34),
    )
    return doc


def _xychart() -> DiagramDocument:
    doc = DiagramDocument.blank("xychart")
    doc.options.update(
        {
            "title": "Orders per month",
            "categories": "jan, feb, mar, apr, may, jun",
            "y_title": "Orders",
            "y_min": 0,
            "y_max": 4000,
        }
    )
    doc.sections["series"] = _rows(
        ("name", "Orders", "kind", "bar", "values", "1200, 1800, 1500, 2600, 3100, 2900"),
        ("name", "Refunds", "kind", "line", "values", "120, 190, 140, 210, 260, 240"),
    )
    return doc


_SAMPLES = {
    "flowchart": _flowchart,
    "sequence": _sequence,
    "class": _class,
    "er": _er,
    "usecase": _usecase,
    "mindmap": _mindmap,
    "gantt": _gantt,
    "timeline": _timeline,
    "pie": _pie,
    "quadrant": _quadrant,
    "xychart": _xychart,
}


def sample(kind: str) -> DiagramDocument:
    """A small, valid starter document for ``kind``."""
    factory = _SAMPLES.get(kind)
    return factory() if factory else DiagramDocument.blank(kind)


def sample_all() -> Iterable[tuple[str, DiagramDocument]]:
    for kind in _SAMPLES:
        yield kind, sample(kind)
