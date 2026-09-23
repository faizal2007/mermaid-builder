"""Declarative description of every mermaid diagram type the app can build.

A :class:`DiagramSpec` is the single source of truth for a diagram type: it lists
the diagram-level options, the element sections (nodes, edges, ...), and the
fields each element has.  ``generators.py`` turns that data into mermaid source,
and ``window.py`` turns it into widgets.  Adding a diagram type therefore means
adding one entry here plus one function in ``generators.py``.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any, Sequence

# --------------------------------------------------------------------------- #
# field kinds
# --------------------------------------------------------------------------- #

TEXT = "text"
LINES = "lines"
CHOICE = "choice"
COLOUR = "colour"
INT = "int"
FLOAT = "float"
BOOL = "bool"

#: value shown for an unset choice
UNSET = "(default)"

DIRECTIONS = ("TD", "TB", "BT", "LR", "RL")

THEMES = (
    "default",
    "redux-color",
    "redux-dark-color",
    "neutral",
    "dark",
    "forest",
    "base",
    "neo",
    "neo-dark",
)

LOOKS = ("classic", "neo", "handDrawn")


@dataclass(frozen=True)
class Field:
    """One editable property of an element (or of the diagram itself)."""

    name: str
    label: str
    kind: str = TEXT
    default: Any = ""
    choices: tuple[str, ...] = ()
    #: the choices name mermaid node shapes, so each is worth drawing; see
    #: :mod:`~diagram_maker.shapes`
    shape_icons: bool = False
    #: for a COLOUR field, the style properties the pickers edit, named the way
    #: mermaid names them; anything else in the text is left alone
    colours: tuple[str, ...] = ()
    minimum: float = 0
    maximum: float = 100
    step: float = 1
    decimals: int = 2
    placeholder: str = ""
    tip: str = ""

    def coerce(self, value: Any) -> Any:
        """Return ``value`` converted to the Python type this field stores."""
        try:
            if self.kind == INT:
                return int(value)
            if self.kind == FLOAT:
                return round(float(value), self.decimals)
            if self.kind == BOOL:
                return bool(value)
        except (TypeError, ValueError):
            return self.default
        return "" if value is None else str(value)


def _f(name: str, label: str, kind: str = TEXT, default: Any = "", **kw: Any) -> Field:
    return Field(name=name, label=label, kind=kind, default=default, **kw)


# --------------------------------------------------------------------------- #
# element sections
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class ItemSpec:
    """A repeatable element collection, e.g. the nodes of a flowchart."""

    key: str
    label: str
    singular: str
    fields: tuple[Field, ...]
    summary: tuple[str, ...] = ()
    tip: str = ""
    #: the field whose value the preview draws for this element, and the field
    #: mermaid builds the element's id from.  Together they are how a double
    #: click on a label finds the row it belongs to; empty means it cannot.
    text_field: str = ""
    id_field: str = ""
    #: for a box that mermaid draws one line of a multi-line field per row - the
    #: members of a class, the columns of an entity: the class it puts on that
    #: row's labels -> the field the row comes from.  A click names one of these
    #: and its position among them, which is what says which line it is.
    line_fields: tuple[tuple[str, str], ...] = ()

    def blank(self) -> dict[str, Any]:
        return {f.name: f.default for f in self.fields}

    def summarize(self, item: dict[str, Any]) -> str:
        parts = [
            " ".join(str(item.get(name, "")).split())
            for name in (self.summary or (self.fields[0].name,))
        ]
        parts = [p for p in parts if p]
        return " — ".join(parts) if parts else f"(new {self.singular.lower()})"


@dataclass(frozen=True)
class DiagramSpec:
    key: str
    name: str
    options: tuple[Field, ...]
    sections: tuple[ItemSpec, ...]
    blurb: str = ""

    def option(self, name: str) -> Field | None:
        for f in self.options:
            if f.name == name:
                return f
        return None

    def section(self, key: str) -> ItemSpec | None:
        for s in self.sections:
            if s.key == key:
                return s
        return None


# --------------------------------------------------------------------------- #
# common options
# --------------------------------------------------------------------------- #

COMMON_OPTIONS: tuple[Field, ...] = (
    _f("title", "Title", TEXT, "", placeholder="optional diagram title"),
    _f("theme", "Theme", CHOICE, "", choices=THEMES),
    _f("look", "Look", CHOICE, "", choices=LOOKS),
)


def _with_common(spec: DiagramSpec) -> DiagramSpec:
    """Put the shared options first, keeping any type specific field of the same
    name last so it would win."""
    extra = tuple(f for f in spec.options if f.name not in {c.name for c in COMMON_OPTIONS})
    return replace(spec, options=COMMON_OPTIONS + extra)


# --------------------------------------------------------------------------- #
# shallow helpers for the per-type definitions
# --------------------------------------------------------------------------- #

_ARROW_STYLES = (
    "Arrow  -->",
    "Open  ---",
    "Dotted  -.->",
    "Dotted open  -.-",
    "Thick  ==>",
    "Thick open  ===",
    "Circle  --o",
    "Cross  --x",
    "Bidirectional  <-->",
)

#: the sides of a box an architecture edge can leave or arrive at
_SIDES = ("L", "R", "T", "B")

#: architecture edges carry an arrowhead on either side, or neither
_ARCH_ARROWS = (
    "None  --",
    "Into the target  -->",
    "Into the source  <--",
    "Both ways  <-->",
)

#: the icons mermaid draws itself; iconify packs can be named "pack:icon" too
_ARCH_ICONS = ("cloud", "database", "disk", "internet", "server")


# --------------------------------------------------------------------------- #
# the registry
# --------------------------------------------------------------------------- #

_RAW_SPECS: Sequence[DiagramSpec] = (
    # ---------------------------------------------------------------- flowchart
    DiagramSpec(
        key="flowchart",
        name="Flowchart",
        blurb="Boxes and arrows: processes, decisions, systems.",
        options=(
            _f("direction", "Direction", CHOICE, "TD", choices=DIRECTIONS),
        ),
        sections=(
            ItemSpec(
                key="nodes",
                label="Nodes",
                singular="Node",
                summary=("id", "label"),
                text_field="label",
                id_field="id",
                tip="Ids must be unique. Letters, digits and underscore only.",
                fields=(
                    _f("id", "Id", TEXT, "", placeholder="A"),
                    _f("label", "Label", TEXT, "", placeholder="Start"),
                    _f(
                        "shape",
                        "Shape",
                        CHOICE,
                        "Rectangle",
                        choices=(
                            "Rectangle",
                            "Rounded",
                            "Stadium",
                            "Subroutine",
                            "Cylinder",
                            "Circle",
                            "Double circle",
                            "Rhombus",
                            "Hexagon",
                            "Parallelogram",
                            "Trapezoid",
                            "Asymmetric",
                        ),
                        shape_icons=True,
                    ),
                    _f("container", "Subgraph", TEXT, "", placeholder="optional group name"),
                    _f(
                        "style",
                        "Style",
                        COLOUR,
                        "",
                        colours=("fill", "stroke", "color"),
                        tip="Click a swatch to pick a colour, right-click to clear it.",
                    ),
                ),
            ),
            ItemSpec(
                key="edges",
                label="Edges",
                singular="Edge",
                summary=("source", "label", "target"),
                text_field="label",
                tip="Reference node ids declared above.",
                fields=(
                    _f("source", "From", TEXT, "", placeholder="A"),
                    _f("target", "To", TEXT, "", placeholder="B"),
                    _f("label", "Label", TEXT, ""),
                    _f("style", "Line", CHOICE, _ARROW_STYLES[0], choices=_ARROW_STYLES),
                    _f("length", "Extra length", INT, 0, minimum=0, maximum=4),
                ),
            ),
        ),
    ),
    # ---------------------------------------------------------------- sequence
    DiagramSpec(
        key="sequence",
        name="Sequence",
        blurb="Messages exchanged between participants over time.",
        options=(
            _f("autonumber", "Auto number messages", BOOL, False),
        ),
        sections=(
            ItemSpec(
                key="participants",
                label="Participants",
                singular="Participant",
                text_field="label",
                id_field="alias",
                summary=("alias", "label"),
                fields=(
                    _f("alias", "Id", TEXT, "", placeholder="A"),
                    _f("label", "Display name", TEXT, "", placeholder="Alice"),
                    _f("kind", "Kind", CHOICE, "participant", choices=("participant", "actor")),
                ),
            ),
            ItemSpec(
                key="messages",
                text_field="text",
                label="Messages",
                singular="Message",
                summary=("sender", "text", "receiver"),
                fields=(
                    _f("sender", "From", TEXT, "", placeholder="A"),
                    _f("receiver", "To", TEXT, "", placeholder="B"),
                    _f("text", "Text", TEXT, ""),
                    _f(
                        "style",
                        "Line",
                        CHOICE,
                        "Solid arrow  ->>",
                        choices=(
                            "Solid arrow  ->>",
                            "Dashed arrow  -->>",
                            "Solid line  ->",
                            "Dashed line  -->",
                            "Solid cross  -x",
                            "Dashed cross  --x",
                            "Solid async  -)",
                            "Dashed async  --)",
                        ),
                    ),
                ),
            ),
            ItemSpec(
                key="notes",
                label="Notes",
                singular="Note",
                summary=("text",),
                text_field="text",
                fields=(
                    _f("text", "Text", TEXT, ""),
                    _f(
                        "placement",
                        "Placement",
                        CHOICE,
                        "over",
                        choices=("over", "left of", "right of"),
                    ),
                    _f("first", "First participant", TEXT, "", placeholder="A"),
                    _f("second", "Second participant", TEXT, "", placeholder="optional for 'over'"),
                ),
            ),
        ),
    ),
    # ---------------------------------------------------------------- class
    DiagramSpec(
        key="class",
        name="Class",
        blurb="UML classes, interfaces, attributes, methods and relations.",
        options=(
            _f("direction", "Direction", CHOICE, "", choices=DIRECTIONS),
        ),
        sections=(
            ItemSpec(
                key="classes",
                label="Classes",
                singular="Class",
                summary=("name",),
                text_field="name",
                id_field="name",
                # mermaid draws the members and the methods as rows of their own
                line_fields=(("members-group", "attributes"), ("methods-group", "methods")),
                tip="One attribute or method per line, e.g. '+name : String'.",
                fields=(
                    _f("name", "Name", TEXT, "", placeholder="Animal"),
                    _f(
                        "stereotype",
                        "Stereotype",
                        CHOICE,
                        UNSET,
                        choices=(UNSET, "interface", "abstract", "enumeration", "service"),
                    ),
                    _f("attributes", "Attributes", LINES, ""),
                    _f("methods", "Methods", LINES, ""),
                ),
            ),
            ItemSpec(
                key="relations",
                label="Relations",
                text_field="label",
                singular="Relation",
                summary=("source", "kind", "target"),
                fields=(
                    _f("source", "From", TEXT, "", placeholder="Animal"),
                    _f("target", "To", TEXT, "", placeholder="Dog"),
                    _f(
                        "kind",
                        "Kind",
                        CHOICE,
                        "Inheritance  <|--",
                        choices=(
                            "Inheritance  <|--",
                            "Realization  ..|>",
                            "Composition  *--",
                            "Aggregation  o--",
                            "Association  -->",
                            "Dependency  ..>",
                            "Link  --",
                        ),
                    ),
                    _f("label", "Label", TEXT, ""),
                    _f("source_card", "From multiplicity", TEXT, "", placeholder="1"),
                    _f("target_card", "To multiplicity", TEXT, "", placeholder="0..*"),
                ),
            ),
        ),
    ),
    # ---------------------------------------------------------------- ER
    DiagramSpec(
        key="er",
        name="Entity relationship",
        blurb="Database entities, their columns and cardinality.",
        options=(),
        sections=(
            ItemSpec(
                key="entities",
                label="Entities",
                singular="Entity",
                summary=("name",),
                text_field="name",
                id_field="name",
                # mermaid draws a column as four cells, and every one of them
                # belongs to the same line of the field
                line_fields=(
                    ("attribute-name", "attributes"),
                    ("attribute-type", "attributes"),
                    ("attribute-keys", "attributes"),
                    ("attribute-comment", "attributes"),
                ),
                tip="One column per line: 'string name PK \"comment\"'.",
                fields=(
                    _f("name", "Name", TEXT, "", placeholder="CUSTOMER"),
                    _f("attributes", "Columns", LINES, ""),
                ),
            ),
            ItemSpec(
                key="relations",
                text_field="label",
                label="Relationships",
                singular="Relationship",
                summary=("left", "cardinality", "right"),
                fields=(
                    _f("left", "Left entity", TEXT, "", placeholder="CUSTOMER"),
                    _f("right", "Right entity", TEXT, "", placeholder="ORDER"),
                    _f(
                        "cardinality",
                        "Cardinality",
                        CHOICE,
                        "one to zero-or-more  ||--o{",
                        choices=(
                            "exactly one to exactly one  ||--||",
                            "one to zero-or-one  ||--o|",
                            "one to zero-or-more  ||--o{",
                            "one to one-or-more  ||--|{",
                            "zero-or-one to zero-or-more  |o--o{",
                            "zero-or-more to zero-or-more  }o--o{",
                            "zero-or-more to one  }o--||",
                            "one-or-more to one-or-more  }|--|{",
                        ),
                    ),
                    _f("label", "Label", TEXT, "", placeholder="places"),
                    _f("identifying", "Identifying", BOOL, False),
                ),
            ),
        ),
    ),

    # ---------------------------------------------------------------- usecase
    DiagramSpec(
        key="usecase",
        name="Use case",
        blurb="Actors, use cases and system boundaries (mermaid 12).",
        options=(
            _f("direction", "Direction", CHOICE, "LR", choices=DIRECTIONS),
            _f("acc_title", "Accessible title", TEXT, ""),
            _f("acc_descr", "Accessible description", LINES, ""),
        ),
        sections=(
            ItemSpec(
                key="boundaries",
                label="System boundaries",
                singular="Boundary",
                summary=("title",),
                text_field="title",
                id_field="id",
                fields=(
                    _f("id", "Id", TEXT, "", placeholder="ordering"),
                    _f("title", "Title", TEXT, "", placeholder="Ordering system"),
                    _f("type", "Type", CHOICE, "rectangle", choices=("rectangle", "package")),
                ),
            ),
            ItemSpec(
                key="actors",
                label="Actors",
                singular="Actor",
                summary=("id", "label"),
                text_field="label",
                id_field="id",
                fields=(
                    _f("id", "Id", TEXT, "", placeholder="Customer"),
                    _f("label", "Display name", TEXT, "", placeholder="Customer"),
                    _f(
                        "variant",
                        "Variant",
                        CHOICE,
                        "normal",
                        choices=("normal", "hollow", "awesome"),
                    ),
                    _f("business", "Business actor", BOOL, False),
                    _f("stereotype", "Stereotype", TEXT, "", placeholder="Employee"),
                    _f("boundary", "Inside boundary", TEXT, "", placeholder="boundary id"),
                ),
            ),
            ItemSpec(
                key="usecases",
                label="Use cases",
                singular="Use case",
                summary=("id", "label"),
                text_field="label",
                id_field="id",
                fields=(
                    _f("id", "Id", TEXT, "", placeholder="Checkout"),
                    _f("label", "Display name", TEXT, "", placeholder="Checkout"),
                    _f(
                        "shape",
                        "Shape",
                        CHOICE,
                        "Ellipse",
                        choices=("Ellipse", "Rectangle"),
                        shape_icons=True,
                    ),
                    _f("business", "Business use case", BOOL, False),
                    _f("stereotype", "Stereotype", TEXT, "", placeholder="Core"),
                    _f("boundary", "Inside boundary", TEXT, "", placeholder="boundary id"),
                ),
            ),
            ItemSpec(
                key="relations",
                label="Relationships",
                singular="Relationship",
                summary=("source", "kind", "target"),
                text_field="label",
                tip="Include/extend need use case endpoints; generalization two of a kind.",
                fields=(
                    _f("source", "From", TEXT, ""),
                    _f("target", "To", TEXT, ""),
                    _f(
                        "kind",
                        "Kind",
                        CHOICE,
                        "Association  -->",
                        choices=(
                            "Association  -->",
                            "Association, reversed  <--",
                            "Association, no arrow  --",
                            "Association with circle  --o",
                            "Association with cross  --x",
                            "Include  ..> : include",
                            "Extend  ..> : extend",
                            "Generalization  --|>",
                        ),
                    ),
                    _f("label", "Label", TEXT, ""),
                ),
            ),
            ItemSpec(
                key="notes",
                text_field="text",
                label="Notes",
                singular="Note",
                summary=("target", "text"),
                fields=(
                    _f("target", "Attached to", TEXT, "", placeholder="actor or use case id"),
                    _f("text", "Text", LINES, ""),
                ),
            ),
        ),
    ),
    # ---------------------------------------------------------------- mindmap
    DiagramSpec(
        key="mindmap",
        name="Mindmap",
        blurb="Indented tree of a central idea and its branches.",
        options=(),
        sections=(
            ItemSpec(
                key="nodes",
                label="Branches",
                singular="Branch",
                summary=("label",),
                text_field="label",
                tip="Level 1 is the root, level 2 the first ring, and so on.",
                fields=(
                    _f("level", "Level", INT, 1, minimum=1, maximum=8),
                    _f("label", "Label", TEXT, "", placeholder="Idea"),
                    _f(
                        "shape",
                        "Shape",
                        CHOICE,
                        "Plain",
                        choices=(
                            "Plain",
                            "Square",
                            "Rounded",
                            "Circle",
                            "Bang",
                            "Cloud",
                            "Hexagon",
                        ),
                        shape_icons=True,
                    ),
                ),
            ),
        ),
    ),

    # ----------------------------------------------------------------- layers
    DiagramSpec(
        key="layers",
        name="Layer stack",
        blurb="Panels of bullet points, one layer above the next.",
        options=(
            _f("direction", "Direction", CHOICE, "TD", choices=DIRECTIONS),
            _f(
                "width",
                "Label width",
                INT,
                400,
                minimum=300,
                maximum=1500,
                step=50,
                tip="How wide a bullet line gets before mermaid wraps it. Narrow "
                "widths make mermaid's layout crawl, so the floor is well above "
                "its own default of 200.",
            ),
        ),
        sections=(
            ItemSpec(
                key="layers",
                label="Layers",
                singular="Layer",
                summary=("heading", "title"),
                text_field="title",
                tip="One panel per layer, stacked in the order they are listed.",
                fields=(
                    _f(
                        "heading",
                        "Heading",
                        TEXT,
                        "",
                        placeholder="optional group",
                        tip="Layers with the same heading, one after another, are "
                        "drawn inside one panel named by it.",
                    ),
                    _f("title", "Title", TEXT, "", placeholder="Data Services"),
                ),
            ),
            ItemSpec(
                key="columns",
                label="Columns",
                singular="Column",
                summary=("layer", "title"),
                text_field="title",
                tip="A layer with one column is a single box; give it two or more "
                "and it becomes a panel with the columns side by side.",
                fields=(
                    _f(
                        "layer",
                        "In layer",
                        TEXT,
                        "",
                        placeholder="Data Services",
                        tip="The title of a layer listed above, so renaming that "
                        "layer means renaming it here too.",
                    ),
                    _f("title", "Title", TEXT, "", placeholder="optional"),
                    _f("items", "Bullets", LINES, "", placeholder="one per line"),
                ),
            ),
        ),
    ),

    # ---------------------------------------------------------------- gantt
    DiagramSpec(
        key="gantt",
        name="Gantt",
        blurb="Project schedule with sections, tasks and milestones.",
        options=(
            _f("date_format", "Date format", TEXT, "YYYY-MM-DD"),
            _f("axis_format", "Axis format", TEXT, "%Y-%m-%d"),
            _f("excludes", "Exclude", TEXT, "", placeholder="weekends"),
        ),
        sections=(
            ItemSpec(
                key="tasks",
                label="Tasks",
                singular="Task",
                summary=("name", "start", "duration"),
                text_field="name",
                id_field="id",
                tip="Start is a date in the chosen format, or 'after <task id>'.",
                fields=(
                    _f("section", "Section", TEXT, "", placeholder="optional group"),
                    _f("name", "Task", TEXT, "", placeholder="Design"),
                    _f("id", "Id", TEXT, "", placeholder="optional"),
                    _f("start", "Start", TEXT, "", placeholder="2026-01-06"),
                    _f("duration", "Duration", TEXT, "", placeholder="10d"),
                    _f(
                        "status",
                        "Status",
                        CHOICE,
                        UNSET,
                        choices=(UNSET, "done", "active", "crit", "milestone"),
                    ),
                ),
            ),
        ),
    ),
    # ---------------------------------------------------------------- timeline
    DiagramSpec(
        key="timeline",
        name="Timeline",
        blurb="Chronological events grouped into sections.",
        options=(),
        sections=(
            ItemSpec(
                key="events",
                label="Events",
                singular="Event",
                summary=("period", "text"),
                text_field="text",
                tip="Events with the same section are grouped together.",
                fields=(
                    _f("section", "Section", TEXT, "", placeholder="optional group"),
                    _f("period", "Period", TEXT, "", placeholder="2026"),
                    _f("text", "Event", TEXT, ""),
                    _f("extra", "Extra detail", TEXT, ""),
                ),
            ),
        ),
    ),
    # ---------------------------------------------------------------- pie
    DiagramSpec(
        key="pie",
        name="Pie chart",
        blurb="Share of a whole, one slice per row.",
        options=(
            _f("show_data", "Show values on chart", BOOL, True),
        ),
        sections=(
            ItemSpec(
                key="slices",
                label="Slices",
                singular="Slice",
                summary=("label", "value"),
                text_field="label",
                fields=(
                    _f("label", "Label", TEXT, ""),
                    _f("value", "Value", FLOAT, 1, minimum=0, maximum=1_000_000, step=1),
                ),
            ),
        ),
    ),
    # ---------------------------------------------------------------- quadrant
    DiagramSpec(
        key="quadrant",
        name="Quadrant chart",
        blurb="Points plotted on two axes split into four quadrants.",
        options=(
            _f("x_low", "X axis (low)", TEXT, "Low"),
            _f("x_high", "X axis (high)", TEXT, "High"),
            _f("y_low", "Y axis (low)", TEXT, "Low"),
            _f("y_high", "Y axis (high)", TEXT, "High"),
            _f("q1", "Quadrant 1", TEXT, "Expand"),
            _f("q2", "Quadrant 2", TEXT, "Promote"),
            _f("q3", "Quadrant 3", TEXT, "Re-evaluate"),
            _f("q4", "Quadrant 4", TEXT, "Improve"),
        ),
        sections=(
            ItemSpec(
                key="points",
                label="Points",
                singular="Point",
                text_field="name",
                summary=("name",),
                tip="X and Y are normalised: 0 = low end of the axis, 1 = high end.",
                fields=(
                    _f("name", "Name", TEXT, ""),
                    _f("x", "X", FLOAT, 0.5, minimum=0, maximum=1, step=0.05, decimals=2),
                    _f("y", "Y", FLOAT, 0.5, minimum=0, maximum=1, step=0.05, decimals=2),
                ),
            ),
        ),
    ),
    # ---------------------------------------------------------------- xychart
    DiagramSpec(
        key="xychart",
        name="XY chart",
        blurb="Bar and line series over a shared category axis.",
        options=(
            _f("categories", "Categories", TEXT, "", placeholder="jan, feb, mar"),
            _f("y_title", "Y axis title", TEXT, ""),
            _f("y_min", "Y axis min", FLOAT, 0, minimum=-1_000_000, maximum=1_000_000, step=1),
            _f("y_max", "Y axis max", FLOAT, 100, minimum=-1_000_000, maximum=1_000_000, step=1),
        ),
        sections=(
            ItemSpec(
                key="series",
                label="Series",
                text_field="name",
                singular="Series",
                summary=("name", "kind"),
                tip="Provide one value per category, separated by commas.",
                fields=(
                    _f("name", "Name", TEXT, "", placeholder="optional"),
                    _f("kind", "Kind", CHOICE, "bar", choices=("bar", "line")),
                    _f("values", "Values", TEXT, "", placeholder="10, 20, 30"),
                ),
            ),
        ),
    ),
    # --------------------------------------------------------- architecture
    DiagramSpec(
        key="architecture",
        name="Architecture",
        blurb="Services grouped into systems, wired port to port.",
        options=(),
        sections=(
            ItemSpec(
                key="groups",
                label="Groups",
                singular="Group",
                text_field="title",
                id_field="id",
                summary=("id", "title"),
                tip="Groups hold services. Ids must be declared before they are used.",
                fields=(
                    _f("id", "Id", TEXT, "", placeholder="api"),
                    _f("title", "Title", TEXT, "", placeholder="Public API"),
                    _f("icon", "Icon", CHOICE, _ARCH_ICONS[0], choices=_ARCH_ICONS),
                    _f("parent", "Inside group", TEXT, "", placeholder="optional group id"),
                ),
            ),
            ItemSpec(
                key="services",
                label="Services",
                singular="Service",
                text_field="title",
                id_field="id",
                summary=("id", "title"),
                tip="A service may sit in a group, or stand on its own.",
                fields=(
                    _f("id", "Id", TEXT, "", placeholder="db"),
                    _f("title", "Title", TEXT, "", placeholder="Orders DB"),
                    _f("icon", "Icon", CHOICE, _ARCH_ICONS[1], choices=_ARCH_ICONS),
                    _f("group", "Inside group", TEXT, "", placeholder="optional group id"),
                ),
            ),
            ItemSpec(
                key="junctions",
                label="Junctions",
                singular="Junction",
                text_field="id",
                id_field="id",
                summary=("id",),
                tip="A junction splits one edge into several without drawing a box.",
                fields=(
                    _f("id", "Id", TEXT, "", placeholder="hub"),
                    _f("group", "Inside group", TEXT, "", placeholder="optional group id"),
                ),
            ),
            ItemSpec(
                key="edges",
                label="Connections",
                singular="Connection",
                summary=("source", "target"),
                tip="Sides are the edge of the box the line leaves or arrives at.",
                fields=(
                    _f("source", "From", TEXT, "", placeholder="db"),
                    _f("source_side", "From side", CHOICE, "R", choices=_SIDES),
                    _f("arrow", "Arrow", CHOICE, _ARCH_ARROWS[0], choices=_ARCH_ARROWS),
                    _f("target_side", "To side", CHOICE, "L", choices=_SIDES),
                    _f("target", "To", TEXT, "", placeholder="server"),
                    _f(
                        "source_group",
                        "From parent group",
                        BOOL,
                        False,
                        tip="Leave from the group the service is in, not the service.",
                    ),
                    _f(
                        "target_group",
                        "Into parent group",
                        BOOL,
                        False,
                        tip="Arrive at the group the service is in, not the service.",
                    ),
                ),
            ),
            ItemSpec(
                key="aligns",
                label="Alignments",
                singular="Alignment",
                summary=("axis", "members"),
                tip="Lines up services that share a port, when the layout stacks them.",
                fields=(
                    _f("axis", "Axis", CHOICE, "row", choices=("row", "column")),
                    _f("members", "Members", TEXT, "", placeholder="db1 db2 db3"),
                ),
            ),
        ),
    ),
)

#: every supported diagram type, keyed by its identifier
def _build_registry() -> dict[str, DiagramSpec]:
    registry: dict[str, DiagramSpec] = {}
    for spec in _RAW_SPECS:
        registry[spec.key] = _with_common(spec)
    return registry


SPECS = _build_registry()

#: display order of the diagram type picker
SPEC_ORDER: tuple[str, ...] = tuple(spec.key for spec in _RAW_SPECS)


def get_spec(key: str) -> DiagramSpec:
    return SPECS[key]
