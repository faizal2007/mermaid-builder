"""Turn a :class:`~diagram_maker.document.DiagramDocument` into mermaid source.

Every generator returns the diagram body only; :func:`generate` prepends the
optional YAML frontmatter that carries the title, theme and look.

Generators never raise on incomplete input.  Instead they record a
:class:`Warning` for the offending row and skip it, so the preview always shows
something and the user learns exactly which row needs attention.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Callable, Sequence

from .document import DiagramDocument
from .specs import UNSET

# --------------------------------------------------------------------------- #
# result type
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class Warning:
    """A row that could not be rendered, and why."""

    section: str
    index: int
    message: str

    def __str__(self) -> str:
        return f"{self.section} #{self.index + 1}: {self.message}"


@dataclass
class Result:
    code: str
    warnings: list[Warning] = field(default_factory=list)


# --------------------------------------------------------------------------- #
# primitives
# --------------------------------------------------------------------------- #

_IDENT = re.compile(r"[^0-9A-Za-z_]")
_SAFE_WORD = re.compile(r"^[A-Za-z_][0-9A-Za-z_]*$")
_RESERVED_IN_MINDMAP = re.compile(r"[\[\](){}]")


def clean(value: Any) -> str:
    """Collapse all whitespace runs (including newlines) into single spaces."""
    return " ".join(str(value or "").split())


def lines(value: Any) -> list[str]:
    """Split a multi-line field into non-blank, right-stripped lines."""
    return [line.strip() for line in str(value or "").splitlines() if line.strip()]


def csv_values(value: Any) -> list[str]:
    """Split a comma or newline separated field into trimmed parts."""
    return [part.strip() for part in re.split(r"[,\n]", str(value or "")) if part.strip()]


def ident(value: Any, fallback: str) -> str:
    """Coerce text into a mermaid-safe identifier, or ``fallback`` if empty."""
    text = _IDENT.sub("_", clean(value)).strip("_")
    if not text:
        return fallback
    if text[0].isdigit():
        text = "n" + text
    return text


def quoted(value: Any) -> str:
    """A mermaid double-quoted string, safe against entity-code confusion.

    ``#`` starts an entity code inside mermaid strings and ``"`` would end the
    string, so both are replaced with their documented entity codes.
    """
    text = clean(value).replace("#", "#35;").replace('"', "#quot;")
    return f'"{text}"'


def number(value: Any, fallback: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return fallback


def without_colons(value: Any) -> str:
    """Drop colons from text that will sit in a colon-delimited grammar slot.

    Mermaid splits ``task :meta``, ``Class : member`` and ``A --> B : label`` on
    the first colon, so a colon in the user's text ends the statement early and
    breaks the parse.
    """
    return clean(value).replace(":", "")


def _yaml(value: str) -> str:
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _normalised(mapping: dict[str, Any]) -> dict[str, Any]:
    """Key a lookup table by :func:`clean`-ed keys.

    Several spec choices are padded with a second space so that the dropdown
    lines up (``"Arrow  -->"``), but user input is always passed through
    :func:`clean` first, which collapses those runs.  Normalising the tables
    keeps the two in step.
    """
    return {clean(key): value for key, value in mapping.items()}


_NATIVE_TITLE = {"gantt", "pie", "quadrant", "xychart", "timeline"}
"""Diagram types that render a ``title`` statement themselves."""

_QUOTED_TITLE = {"xychart"}
"""Of those, the ones whose title statement must be a quoted string."""


def _frontmatter(doc: DiagramDocument, include_title: bool) -> str:
    body: list[str] = []
    title = clean(doc.option("title"))
    if title and include_title:
        body.append(f"title: {_yaml(title)}")

    config: list[str] = []
    if theme := clean(doc.option("theme")):
        config.append(f"  theme: {theme}")
    if look := clean(doc.option("look")):
        config.append(f"  look: {look}")
    if config:
        body.append("config:")
        body.extend(config)

    return "---\n" + "\n".join(body) + "\n---\n" if body else ""


def _title_line(doc: DiagramDocument) -> list[str]:
    title = clean(doc.option("title"))
    if not title:
        return []
    if doc.kind in _QUOTED_TITLE:
        title = quoted(title)
    return [f"    title {title}"]


# --------------------------------------------------------------------------- #
# flowchart
# --------------------------------------------------------------------------- #

_FLOW_SHAPES: dict[str, str] = {
    "Rectangle": "[{}]",
    "Rounded": "({})",
    "Stadium": "([{}])",
    "Subroutine": "[[{}]]",
    "Cylinder": "[({})]",
    "Circle": "(({}))",
    "Double circle": "((({})))",
    "Rhombus": "{{{}}}",
    "Hexagon": "{{{{{}}}}}",
    "Parallelogram": "[/{}/]",
    "Trapezoid": r"[/{}\]",
    "Asymmetric": ">{}]",
}

_FLOW_ARROWS: dict[str, tuple[str, str]] = _normalised({
    # style -> (plain form, labelled form).
    # ``{n}`` is replaced by the extra dashes that request a longer edge, and
    # mermaid wants those on the far side of the label.
    "Arrow  -->": ("--{n}>", "--{n} {label} -->"),
    "Open  ---": ("--{n}-", "--{n} {label} ---"),
    "Dotted  -.->": ("-.{n}->", "-.{n} {label} .->"),
    "Dotted open  -.-": ("-.{n}-", "-.{n} {label} .-"),
    "Thick  ==>": ("=={n}>", "=={n} {label} ==>"),
    "Thick open  ===": ("=={n}=", "=={n} {label} ==="),
    "Circle  --o": ("--{n}o", "--{n} {label} --o"),
    "Cross  --x": ("--{n}x", "--{n} {label} --x"),
    "Bidirectional  <-->": ("<--{n}>", "<--{n} {label} -->"),
})

#: used when an edge carries an unknown or empty line style
_FLOW_ARROW_DEFAULT = ("--{n}>", "--{n} {label} -->")


def _flowchart(doc: DiagramDocument, warn: Callable[[str, int, str], None]) -> str:
    direction = clean(doc.option("direction")) or "TD"
    out = [f"flowchart {direction}"]

    nodes = doc.rows("nodes")
    declared: set[str] = set()
    statements: list[str] = []

    for index, node in enumerate(nodes):
        raw_id = clean(node.get("id"))
        if not raw_id:
            warn("nodes", index, "skipped, no id")
            continue
        node_id = ident(raw_id, f"n{index + 1}")
        if node_id in declared:
            warn("nodes", index, f"skipped, duplicate id '{node_id}'")
            continue
        declared.add(node_id)

        label = clean(node.get("label")) or raw_id
        template = _FLOW_SHAPES.get(clean(node.get("shape")), "{}")
        shape = template.format(quoted(label))
        container = clean(node.get("container"))
        statements.append((container, node_id, shape))

        style = clean(node.get("style"))
        if style:
            out.append(f"    style {node_id} {style}")

    # group the declarations, keeping first-seen order of each subgraph
    order: list[str] = []
    grouped: dict[str, list[tuple[str, str]]] = {}
    loose: list[tuple[str, str]] = []
    for container, node_id, shape in statements:
        if not container:
            loose.append((node_id, shape))
        else:
            if container not in grouped:
                grouped[container] = []
                order.append(container)
            grouped[container].append((node_id, shape))

    for container in order:
        out.append(f"    subgraph sg_{ident(container, 'group')}[{quoted(container)}]")
        out.extend(f"        {node_id}{shape}" for node_id, shape in grouped[container])
        out.append("    end")
    out.extend(f"    {node_id}{shape}" for node_id, shape in loose)

    for index, edge in enumerate(doc.rows("edges")):
        source = ident(edge.get("source"), "")
        target = ident(edge.get("target"), "")
        if not source or not target:
            warn("edges", index, "skipped, both ends must be given")
            continue
        if source not in declared or target not in declared:
            missing = source if source not in declared else target
            warn("edges", index, f"skipped, node '{missing}' is not declared")
            continue

        style = clean(edge.get("style"))
        plain, labelled = _FLOW_ARROWS.get(style, _FLOW_ARROW_DEFAULT)
        dashes = "-" * max(0, min(4, int(number(edge.get("length"), 0))))

        label = clean(edge.get("label"))
        if label:
            operator = labelled.format(n=dashes, label=quoted(label))
        else:
            operator = plain.format(n=dashes)
        out.append(f"    {source} {operator} {target}")

    return "\n".join(out)


# --------------------------------------------------------------------------- #
# sequence
# --------------------------------------------------------------------------- #

_SEQ_ARROWS = _normalised({
    "Solid arrow  ->>": "->>",
    "Dashed arrow  -->>": "-->>",
    "Solid line  ->": "->",
    "Dashed line  -->": "-->",
    "Solid cross  -x": "-x",
    "Dashed cross  --x": "--x",
    "Solid async  -)": "-)",
    "Dashed async  --)": "--)",
})


def _sequence(doc: DiagramDocument, warn: Callable[[str, int, str], None]) -> str:
    out = ["sequenceDiagram"]
    if doc.option("autonumber"):
        out.append("    autonumber")

    known: set[str] = set()
    for index, participant in enumerate(doc.rows("participants")):
        alias = ident(participant.get("alias"), "")
        if not alias:
            warn("participants", index, "skipped, no id")
            continue
        known.add(alias)
        kind = clean(participant.get("kind")) or "participant"
        label = clean(participant.get("label"))
        out.append(f"    {kind} {alias} as {label}" if label else f"    {kind} {alias}")

    def endpoint(value: Any, section: str, index: int, role: str) -> str | None:
        alias = ident(value, "")
        if not alias:
            warn(section, index, f"skipped, no {role}")
            return None
        return alias

    for index, message in enumerate(doc.rows("messages")):
        sender = endpoint(message.get("sender"), "messages", index, "sender")
        receiver = endpoint(message.get("receiver"), "messages", index, "receiver")
        if sender is None or receiver is None:
            continue
        operator = _SEQ_ARROWS.get(clean(message.get("style")), "->>")
        text = clean(message.get("text"))
        statement = f"    {sender}{operator}{receiver}"
        out.append(f"{statement}: {text}" if text else statement)

    for index, note in enumerate(doc.rows("notes")):
        text = clean(note.get("text"))
        if not text:
            warn("notes", index, "skipped, empty note")
            continue
        first = endpoint(note.get("first"), "notes", index, "first participant")
        if first is None:
            continue
        second = endpoint(note.get("second"), "notes", index, "second participant")
        placement = clean(note.get("placement")) or "over"
        if placement == "over" and second:
            out.append(f"    Note over {first},{second}: {text}")
        elif placement == "over":
            out.append(f"    Note over {first}: {text}")
        else:
            out.append(f"    Note {placement} {first}: {text}")

    return "\n".join(out)


# --------------------------------------------------------------------------- #
# class
# --------------------------------------------------------------------------- #

_CLASS_RELATIONS = _normalised({
    "Inheritance  <|--": "<|--",
    "Realization  ..|>": "..|>",
    "Composition  *--": "*--",
    "Aggregation  o--": "o--",
    "Association  -->": "-->",
    "Dependency  ..>": "..>",
    "Link  --": "--",
})

_CLASS_STEREOTYPES = _normalised({
    "interface": "<<interface>>",
    "abstract": "<<abstract>>",
    "enumeration": "<<enumeration>>",
    "service": "<<service>>",
})


def _class_name(name: str) -> tuple[str, str]:
    """Split a typed class name into ``(identifier, label)``.

    Mermaid reads ``<`` as a relation, so ``List<Int>`` only parses when it is
    carried as a display label.  A name that is already a plain identifier is
    returned unchanged with no label.
    """
    if _SAFE_WORD.match(name):
        return name, ""
    return ident(name, "Class"), name


def _class(doc: DiagramDocument, warn: Callable[[str, int, str], None]) -> str:
    out = ["classDiagram"]
    if direction := clean(doc.option("direction")):
        out.append(f"    direction {direction}")

    # both the typed name and the identifier resolve to the identifier, so a
    # relation may reference a class either way
    known: dict[str, str] = {}
    used: set[str] = set()

    for index, klass in enumerate(doc.rows("classes")):
        name = clean(klass.get("name"))
        if not name:
            warn("classes", index, "skipped, no name")
            continue
        identifier, label = _class_name(name)
        if identifier in used:
            warn("classes", index, f"skipped, duplicate class '{identifier}'")
            continue
        used.add(identifier)
        known[name] = identifier
        known[identifier] = identifier

        body: list[str] = []
        stereotype = clean(klass.get("stereotype"))
        if stereotype and stereotype != UNSET:
            body.append(_CLASS_STEREOTYPES.get(stereotype, f"<<{stereotype}>>"))
        body.extend(lines(klass.get("attributes")))
        body.extend(lines(klass.get("methods")))

        if body:
            # a display label goes in brackets before the braced body
            header = f"{identifier}[{quoted(label)}]" if label else identifier
            out.append(f"    class {header} {{")
            out.extend(f"        {line}" for line in body)
            out.append("    }")
        elif label:
            out.append(f"    class {identifier}[{quoted(label)}]")
        else:
            out.append(f"    class {identifier}")

    for index, relation in enumerate(doc.rows("relations")):
        raw_source = clean(relation.get("source"))
        raw_target = clean(relation.get("target"))
        if not raw_source or not raw_target:
            warn("relations", index, "skipped, both ends must be given")
            continue
        source = known.get(raw_source)
        target = known.get(raw_target)
        if source is None or target is None:
            missing = raw_source if source is None else raw_target
            warn("relations", index, f"skipped, class '{missing}' is not declared")
            continue
        operator = _CLASS_RELATIONS.get(clean(relation.get("kind")), "-->")
        left_card = clean(relation.get("source_card"))
        right_card = clean(relation.get("target_card"))
        left = quoted(left_card) + " " if left_card else ""
        right = " " + quoted(right_card) if right_card else ""
        statement = f"    {source} {left}{operator}{right} {target}"
        label = clean(relation.get("label"))
        out.append(f"{statement} : {without_colons(label)}" if label else statement)

    return "\n".join(out)


# --------------------------------------------------------------------------- #
# entity relationship
# --------------------------------------------------------------------------- #

_ER_CARDINALITY = _normalised({
    "exactly one to exactly one  ||--||": "||--||",
    "one to zero-or-one  ||--o|": "||--o|",
    "one to zero-or-more  ||--o{": "||--o{",
    "one to one-or-more  ||--|{": "||--|{",
    "zero-or-one to zero-or-more  |o--o{": "|o--o{",
    "zero-or-more to zero-or-more  }o--o{": "}o--o{",
    "zero-or-more to one  }o--||": "}o--||",
    "one-or-more to one-or-more  }|--|{": "}|--|{",
})

_ER_NAME = re.compile(r"[^0-9A-Za-z_-]")

#: characters mermaid accepts inside one ER attribute word
_ER_WORD = re.compile(r"^[0-9A-Za-z_.\-\[\]]+$")
_ER_KEY = {"PK", "FK", "UK"}


def _er_attribute(line: str) -> str | None:
    """Validate one ER column line, or return ``None`` if it cannot be drawn.

    An entity body only accepts ``type name [PK|FK|UK] ["comment"]``.  Punctuation
    such as ``{``, ``(``, ``:`` or a third bare word ends the block early, and
    silently rewriting the text would invent a column the user did not ask for,
    so an unusable line is reported instead.
    """
    text = line
    comment = ""
    if (quote_at := text.find('"')) >= 0:
        comment, text = text[quote_at:], text[:quote_at]
        quotes = comment.count('"')
        if quotes == 1:
            comment += '"'  # closed an unterminated comment
        elif quotes > 2:
            first, last = comment.find('"'), comment.rfind('"')
            comment = (
                comment[: first + 1] + comment[first + 1 : last].replace('"', "#quot;") + comment[last:]
            )

    tokens = text.split()
    if len(tokens) < 2 or len(tokens) > 3:
        return None
    if not all(_ER_WORD.match(token) for token in tokens):
        return None
    if len(tokens) == 3 and tokens[2].upper() not in _ER_KEY:
        return None
    return " ".join(tokens) + (f" {comment}" if comment else "")


def _er(doc: DiagramDocument, warn: Callable[[str, int, str], None]) -> str:
    out = ["erDiagram"]
    known: set[str] = set()

    for index, entity in enumerate(doc.rows("entities")):
        raw = clean(entity.get("name"))
        if not raw:
            warn("entities", index, "skipped, no name")
            continue
        name = _ER_NAME.sub("_", raw)
        if name in known:
            warn("entities", index, f"skipped, duplicate entity '{name}'")
            continue
        known.add(name)
        columns: list[str] = []
        for line in lines(entity.get("attributes")):
            checked = _er_attribute(line)
            if checked is None:
                warn(
                    "entities",
                    index,
                    f"{name}: column {line!r} skipped, expected "
                    "'type name [PK|FK|UK] \"comment\"'",
                )
            else:
                columns.append(checked)
        if columns:
            out.append(f"    {name} {{")
            out.extend(f"        {line}" for line in columns)
            out.append("    }")
        else:
            out.append(f"    {name}")

    for index, relation in enumerate(doc.rows("relations")):
        left = _ER_NAME.sub("_", clean(relation.get("left")))
        right = _ER_NAME.sub("_", clean(relation.get("right")))
        if not left or not right:
            warn("relations", index, "skipped, both entities must be given")
            continue
        missing = [n for n in (left, right) if n not in known]
        if missing:
            warn("relations", index, f"skipped, entity '{missing[0]}' is not declared")
            continue
        operator = _ER_CARDINALITY.get(clean(relation.get("cardinality")), "||--o{")
        if not relation.get("identifying"):
            # a non-identifying relationship is drawn with a dashed line
            operator = operator.replace("--", "..")
        label = clean(relation.get("label")) or "relates to"
        out.append(f"    {left} {operator} {right} : {label}")

    return "\n".join(out)


# --------------------------------------------------------------------------- #
# use case
# --------------------------------------------------------------------------- #

_USECASE_ASSOC = _normalised({
    "Association  -->": ("-->", "--", "-->"),
    "Association, no arrow  --": ("--", "--", "--"),
    "Association with circle  --o": ("--o", "--", "--o"),
    "Association with cross  --x": ("--x", "--", "--x"),
})

#: used when a use case relationship carries an unknown kind
_USECASE_ASSOC_DEFAULT = ("-->", "--", "-->")


def _usecase(doc: DiagramDocument, warn: Callable[[str, int, str], None]) -> str:
    out = ["usecase-beta"]
    if direction := clean(doc.option("direction")):
        out.append(f"direction {direction}")
    if acc_title := clean(doc.option("acc_title")):
        out.append(f"accTitle: {acc_title}")
    description = lines(doc.option("acc_descr"))
    if len(description) == 1:
        out.append(f"accDescr: {description[0]}")
    elif description:
        out.append("accDescr {")
        out.extend(f"    {line}" for line in description)
        out.append("}")

    # (key, title, metadata) for each system boundary, in declaration order
    boundaries: list[tuple[str, str, str]] = []
    for index, boundary in enumerate(doc.rows("boundaries")):
        title = clean(boundary.get("title"))
        if not (title or clean(boundary.get("id"))):
            warn("boundaries", index, "skipped, no title")
            continue
        key = ident(boundary.get("id") or title, f"boundary{index + 1}")
        if any(key == existing for existing, _, _ in boundaries):
            warn("boundaries", index, f"skipped, duplicate boundary id '{key}'")
            continue
        metadata = "@{ type: package }" if clean(boundary.get("type")) == "package" else ""
        boundaries.append((key, title or key, metadata))

    membership: dict[str, list[str]] = {key: [] for key, _, _ in boundaries}
    free: list[str] = []
    declared: set[str] = set()

    def actor_statement(index: int, actor: dict[str, Any]) -> str | None:
        if not (actor_id := ident(actor.get("id"), "")):
            warn("actors", index, "skipped, no id")
            return None
        label = clean(actor.get("label"))
        head = f'actor {actor_id}({quoted(label)})' if label else f"actor {actor_id}"
        metadata: list[str] = []
        variant = clean(actor.get("variant"))
        if variant and variant != "normal":
            metadata.append(f"type: {variant}")
        if actor.get("business"):
            metadata.append("business: true")
        if metadata:
            head += "@{ " + ", ".join(metadata) + " }"
        if stereotype := clean(actor.get("stereotype")):
            head += f" <<{stereotype}>>"
        return head

    def usecase_statement(index: int, use_case: dict[str, Any]) -> str | None:
        if not (case_id := ident(use_case.get("id"), "")):
            warn("usecases", index, "skipped, no id")
            return None
        label = clean(use_case.get("label"))
        if clean(use_case.get("shape")) == "Rectangle":
            head = f"{case_id}[{label}]" if label else f"{case_id}[{case_id}]"
        else:
            head = f"{case_id}({quoted(label)})" if label else case_id
        if use_case.get("business"):
            head += "@{ business: true }"
        if stereotype := clean(use_case.get("stereotype")):
            head += f" <<{stereotype}>>"
        return head

    def place(index: int, item: dict[str, Any], section: str, statement: str | None) -> None:
        if statement is None:
            return
        owner = clean(item.get("boundary"))
        if owner:
            key = ident(owner, "")
            if key in membership:
                membership[key].append(statement)
                return
            warn(section, index, f"boundary '{owner}' does not exist, kept outside")
        free.append(statement)

    for index, actor in enumerate(doc.rows("actors")):
        statement = actor_statement(index, actor)
        if statement:
            declared.add(ident(actor.get("id"), ""))
        place(index, actor, "actors", statement)

    for index, use_case in enumerate(doc.rows("usecases")):
        statement = usecase_statement(index, use_case)
        if statement:
            declared.add(ident(use_case.get("id"), ""))
        place(index, use_case, "usecases", statement)

    for key, title, metadata in boundaries:
        out.append(f"systemBoundary {key}[{quoted(title)}]{metadata}")
        out.extend(f"    {statement}" for statement in membership[key])
        out.append("end")
    out.extend(free)

    for index, relation in enumerate(doc.rows("relations")):
        source = ident(relation.get("source"), "")
        target = ident(relation.get("target"), "")
        if not source or not target:
            warn("relations", index, "skipped, both ends must be given")
            continue
        if source not in declared or target not in declared:
            missing = source if source not in declared else target
            warn("relations", index, f"skipped, '{missing}' is not declared")
            continue
        kind = clean(relation.get("kind"))
        label = clean(relation.get("label"))
        if kind.startswith("Include"):
            out.append(f"{source} ..> : include {target}")
        elif kind.startswith("Extend"):
            out.append(f"{source} ..> : extend {target}")
        elif kind.startswith("Generalization"):
            out.append(f"{source} --|> {target}")
        else:
            plain, prefix, suffix = _USECASE_ASSOC.get(kind, _USECASE_ASSOC_DEFAULT)
            if label:
                out.append(f"{source} {prefix} {quoted(label)} {suffix} {target}")
            else:
                out.append(f"{source} {plain} {target}")

    for index, note in enumerate(doc.rows("notes")):
        target = ident(note.get("target"), "")
        text = clean(" ".join(lines(note.get("text"))))
        if not target or not text:
            warn("notes", index, "skipped, needs a target and text")
            continue
        if target not in declared:
            warn("notes", index, f"skipped, '{target}' is not declared")
            continue
        out.append(f"note for {target} {quoted(text)}")

    return "\n".join(out)


# --------------------------------------------------------------------------- #
# mindmap
# --------------------------------------------------------------------------- #

_MINDMAP_SHAPES = {
    "Plain": "{}",
    "Square": "[{}]",
    "Rounded": "({})",
    "Circle": "(({}))",
    "Bang": ")){}((",
    "Cloud": "){}(",
    "Hexagon": "{{{{{}}}}}",
}


def _mindmap(doc: DiagramDocument, warn: Callable[[str, int, str], None]) -> str:
    out = ["mindmap"]
    for index, node in enumerate(doc.rows("nodes")):
        label = clean(node.get("label"))
        if not label:
            warn("nodes", index, "skipped, no label")
            continue
        level = max(1, int(number(node.get("level"), 1)))
        template = _MINDMAP_SHAPES.get(clean(node.get("shape")), "{}")
        if template == "{}":
            # a bare label cannot be quoted in a mindmap, so text holding shape
            # delimiters moves into the square shape instead
            text = f"[{quoted(label)}]" if _RESERVED_IN_MINDMAP.search(label) else label
        else:
            text = template.format(quoted(label) if _RESERVED_IN_MINDMAP.search(label) else label)
        out.append("  " * level + text)
    return "\n".join(out)


# --------------------------------------------------------------------------- #
# gantt
# --------------------------------------------------------------------------- #

_GANTT_TAGS = {"done", "active", "crit", "milestone"}


def _gantt(doc: DiagramDocument, warn: Callable[[str, int, str], None]) -> str:
    out = ["gantt"]
    out.extend(_title_line(doc))
    out.append(f"    dateFormat {clean(doc.option('date_format')) or 'YYYY-MM-DD'}")
    out.append(f"    axisFormat {clean(doc.option('axis_format')) or '%Y-%m-%d'}")
    if excludes := clean(doc.option("excludes")):
        out.append(f"    excludes {excludes}")

    current_section: str | None = None
    for index, task in enumerate(doc.rows("tasks")):
        # a colon in the name would end the ``name :meta`` statement early
        name = without_colons(task.get("name"))
        if not name:
            warn("tasks", index, "skipped, no task name")
            continue
        start = clean(task.get("start"))
        duration = clean(task.get("duration"))
        if not start or not duration:
            warn("tasks", index, f"'{name}' skipped, a start and a duration are required")
            continue

        section = clean(task.get("section"))
        if section and section != current_section:
            out.append(f"    section {section}")
            current_section = section

        # task syntax is: name :[tags,] [id,] start, duration
        status = clean(task.get("status"))
        parts: list[str] = []
        if status and status != UNSET and status in _GANTT_TAGS:
            parts.append(status)
        if task_id := ident(task.get("id"), ""):
            parts.append(task_id)
        parts.extend([start, duration])
        prefix = ", ".join(parts)
        out.append(f"        {name} :{prefix}")

    return "\n".join(out)


# --------------------------------------------------------------------------- #
# timeline
# --------------------------------------------------------------------------- #


def _timeline(doc: DiagramDocument, warn: Callable[[str, int, str], None]) -> str:
    out = ["timeline"]
    out.extend(_title_line(doc))
    current_section: str | None = None
    for index, event in enumerate(doc.rows("events")):
        period = clean(event.get("period"))
        text = clean(event.get("text"))
        if not period or not text:
            warn("events", index, "skipped, a period and an event are required")
            continue
        section = clean(event.get("section"))
        if section and section != current_section:
            out.append(f"    section {section}")
            current_section = section
        extra = clean(event.get("extra"))
        row = f"        {period} : {text}"
        out.append(f"{row} : {extra}" if extra else row)
    return "\n".join(out)


# --------------------------------------------------------------------------- #
# pie
# --------------------------------------------------------------------------- #


def _pie(doc: DiagramDocument, warn: Callable[[str, int, str], None]) -> str:
    out = ["pie showData"] if doc.option("show_data") else ["pie"]
    out.extend(_title_line(doc))
    for index, slice_ in enumerate(doc.rows("slices")):
        label = clean(slice_.get("label"))
        if not label:
            warn("slices", index, "skipped, no label")
            continue
        value = number(slice_.get("value"), 0.0)
        if value <= 0:
            warn("slices", index, f"'{label}' skipped, value must be greater than zero")
            continue
        shown = int(value) if float(value).is_integer() else round(value, 2)
        out.append(f"    {quoted(label)} : {shown}")
    return "\n".join(out)


# --------------------------------------------------------------------------- #
# quadrant
# --------------------------------------------------------------------------- #


def _quadrant(doc: DiagramDocument, warn: Callable[[str, int, str], None]) -> str:
    out = ["quadrantChart"]
    out.extend(_title_line(doc))
    if x_low := clean(doc.option("x_low")):
        out.append(f"    x-axis {x_low} --> {clean(doc.option('x_high'))}")
    if y_low := clean(doc.option("y_low")):
        out.append(f"    y-axis {y_low} --> {clean(doc.option('y_high'))}")
    for position in range(1, 5):
        label = clean(doc.option(f"q{position}"))
        if label:
            out.append(f"    quadrant-{position} {label}")

    for index, point in enumerate(doc.rows("points")):
        name = clean(point.get("name"))
        if not name:
            warn("points", index, "skipped, no name")
            continue
        x = min(1.0, max(0.0, number(point.get("x"), 0.5)))
        y = min(1.0, max(0.0, number(point.get("y"), 0.5)))
        out.append(f"    {name.replace(':', '')}: [{x:.2f}, {y:.2f}]")
    return "\n".join(out)


# --------------------------------------------------------------------------- #
# xy chart
# --------------------------------------------------------------------------- #


def _category(value: str) -> str:
    return value if _SAFE_WORD.match(value) else quoted(value)


def _xychart(doc: DiagramDocument, warn: Callable[[str, int, str], None]) -> str:
    out = ["xychart-beta"]
    out.extend(_title_line(doc))

    categories = csv_values(doc.option("categories"))
    if categories:
        out.append("    x-axis [" + ", ".join(_category(c) for c in categories) + "]")

    low = number(doc.option("y_min"), 0.0)
    high = number(doc.option("y_max"), 0.0)
    if high <= low:
        warn("options", 0, "y axis maximum must be greater than the minimum")
        high = low + 1
    y_title = clean(doc.option("y_title"))
    prefix = f"{quoted(y_title)} " if y_title else ""
    out.append(f"    y-axis {prefix}{low:g} --> {high:g}")

    for index, series in enumerate(doc.rows("series")):
        values = [number(v, 0.0) for v in csv_values(series.get("values"))]
        if not values:
            warn("series", index, "skipped, no values")
            continue
        if categories and len(values) != len(categories):
            warn(
                "series",
                index,
                f"{len(values)} values for {len(categories)} categories",
            )
        kind = clean(series.get("kind")) or "bar"
        numbers = ", ".join(f"{v:g}" for v in values)
        name = clean(series.get("name"))
        out.append(f"    {kind} {quoted(name)} [{numbers}]" if name else f"    {kind} [{numbers}]")

    return "\n".join(out)


# --------------------------------------------------------------------------- #
# dispatch
# --------------------------------------------------------------------------- #

_GENERATORS: dict[str, Callable[[DiagramDocument, Callable[[str, int, str], None]], str]] = {
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


def generate(doc: DiagramDocument) -> Result:
    """Render ``doc`` to mermaid source, collecting any skipped rows."""
    generator = _GENERATORS.get(doc.kind)
    if generator is None:
        raise ValueError(f"no generator for diagram type {doc.kind!r}")

    warnings: list[Warning] = []

    def warn(section: str, index: int, message: str) -> None:
        warnings.append(Warning(section, index, message))

    body = generator(doc, warn)
    prefix = _frontmatter(doc, include_title=doc.kind not in _NATIVE_TITLE)
    return Result(code=prefix + body + "\n", warnings=warnings)


def supported_types() -> Sequence[str]:
    return tuple(_GENERATORS)
