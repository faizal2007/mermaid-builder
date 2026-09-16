"""Outline icons for the mermaid node shapes.

The Shape dropdowns list names, and a name says very little about what a node
will look like, so each entry carries a drawing of the outline mermaid draws for
it.  The outlines are painted from primitives rather than shipped as image
files: they have to follow the palette, and painted this way there is no second
copy to keep in step with the templates in :mod:`~diagram_maker.generators`.

Every shape is described in one nominal box and scaled to whatever size the
widget asks for, the way ``packaging/make_icon.py`` draws the app icon.  The box
is wider than it is tall, because mermaid's nodes are.
"""

from __future__ import annotations

import functools
from collections.abc import Callable

from PyQt6.QtCore import QPointF, QRectF, Qt
from PyQt6.QtGui import (
    QColor,
    QGuiApplication,
    QIcon,
    QPainter,
    QPainterPath,
    QPalette,
    QPen,
    QPixmap,
    QPolygonF,
)

#: the box every outline is described in, and painted from
BOX = 100.0

#: the band inside the box a node fills - wider than tall, like a real node
LEFT, RIGHT = 4.0, 96.0
TOP, BOTTOM = 22.0, 78.0
MID = (TOP + BOTTOM) / 2

#: the size a combo box asks for, in logical pixels
SIZE = 16

#: painted at this multiple and tagged with it, so the outline stays crisp on a
#: high density display
SCALE = 2

#: stroke weight, in box units, so the line is the same weight at every size
PEN = 7.0


# ----------------------------------------------------------------- outlines #


def _rect(x: float, y: float, width: float, height: float, radius: float = 0.0) -> QPainterPath:
    path = QPainterPath()
    if radius:
        path.addRoundedRect(QRectF(x, y, width, height), radius, radius)
    else:
        path.addRect(QRectF(x, y, width, height))
    return path


def _polygon(*points: tuple[float, float]) -> QPainterPath:
    path = QPainterPath()
    path.addPolygon(QPolygonF([QPointF(x, y) for x, y in points]))
    path.closeSubpath()
    return path


def _rectangle() -> QPainterPath:
    return _rect(LEFT, TOP, RIGHT - LEFT, BOTTOM - TOP)


def _square() -> QPainterPath:
    # the mindmap square: the same shape, drawn tight around the label
    return _rect(22.0, TOP, 56.0, BOTTOM - TOP)


def _rounded() -> QPainterPath:
    return _rect(LEFT, TOP, RIGHT - LEFT, BOTTOM - TOP, radius=10.0)


def _stadium() -> QPainterPath:
    # corners as round as the ends can be, which is what makes it a stadium
    return _rect(LEFT, TOP, RIGHT - LEFT, BOTTOM - TOP, radius=(BOTTOM - TOP) / 2)


def _subroutine() -> QPainterPath:
    # mermaid frames a subroutine: a rectangle with a bar down each side
    path = _rectangle()
    for x in (LEFT + 12.0, RIGHT - 12.0):
        path.moveTo(x, TOP)
        path.lineTo(x, BOTTOM)
    return path


def _cylinder() -> QPainterPath:
    ry = 9.0
    path = QPainterPath()
    # the mouth of the cylinder is a whole ellipse, so both of its curves show
    path.addEllipse(QRectF(LEFT, TOP, RIGHT - LEFT, 2 * ry))
    path.moveTo(LEFT, TOP + ry)
    path.lineTo(LEFT, BOTTOM - ry)
    path.quadTo((LEFT + RIGHT) / 2, BOTTOM + ry, RIGHT, BOTTOM - ry)
    path.lineTo(RIGHT, TOP + ry)
    path.quadTo((LEFT + RIGHT) / 2, TOP + 2 * ry, LEFT, TOP + ry)
    path.closeSubpath()
    return path


def _ellipse() -> QPainterPath:
    path = QPainterPath()
    path.addEllipse(QRectF(LEFT, TOP, RIGHT - LEFT, BOTTOM - TOP))
    return path


def _circle() -> QPainterPath:
    path = QPainterPath()
    path.addEllipse(QRectF(22.0, TOP, 56.0, BOTTOM - TOP))
    return path


def _double_circle() -> QPainterPath:
    path = _circle()
    path.addEllipse(QRectF(30.0, TOP + 8.0, 40.0, BOTTOM - TOP - 16.0))
    return path


def _rhombus() -> QPainterPath:
    return _polygon(
        ((LEFT + RIGHT) / 2, TOP), (RIGHT, MID), ((LEFT + RIGHT) / 2, BOTTOM), (LEFT, MID)
    )


def _hexagon() -> QPainterPath:
    # flat top and bottom, with a point at either end
    return _polygon(
        (LEFT + 14.0, TOP),
        (RIGHT - 14.0, TOP),
        (RIGHT, MID),
        (RIGHT - 14.0, BOTTOM),
        (LEFT + 14.0, BOTTOM),
        (LEFT, MID),
    )


def _parallelogram() -> QPainterPath:
    return _polygon(
        (LEFT + 18.0, TOP), (RIGHT, TOP), (RIGHT - 18.0, BOTTOM), (LEFT, BOTTOM)
    )


def _trapezoid() -> QPainterPath:
    # the long base at the bottom, which is the way round mermaid draws it
    return _polygon(
        (LEFT + 20.0, TOP), (RIGHT - 20.0, TOP), (RIGHT, BOTTOM), (LEFT, BOTTOM)
    )


def _asymmetric() -> QPainterPath:
    # a rectangle with its left edge notched inwards, as ``>label]`` is drawn
    return _polygon((LEFT, TOP), (LEFT + 14.0, MID), (LEFT, BOTTOM), (RIGHT, BOTTOM), (RIGHT, TOP))


def _plain() -> QPainterPath:
    # the bare-label mindmap node: a rounded box with a rule under the text
    path = _rect(LEFT, TOP - 2.0, RIGHT - LEFT, 50.0, radius=6.0)
    path.moveTo(LEFT, BOTTOM + 4.0)
    path.lineTo(RIGHT, BOTTOM + 4.0)
    return path


def _bang() -> QPainterPath:
    # mermaid's bang: a box with every side bowed outwards and the corners
    # rounded off, so the whole outline looks about to burst
    path = QPainterPath()
    path.moveTo(10.0, 30.0)
    path.quadTo(4.0, TOP, 20.0, TOP)
    path.quadTo(50.0, TOP - 6.0, 80.0, TOP)
    path.quadTo(96.0, TOP, 90.0, 30.0)
    path.quadTo(96.0, MID, 90.0, 70.0)
    path.quadTo(96.0, BOTTOM, 80.0, BOTTOM)
    path.quadTo(50.0, BOTTOM + 6.0, 20.0, BOTTOM)
    path.quadTo(4.0, BOTTOM, 10.0, 70.0)
    path.quadTo(4.0, MID, 10.0, 30.0)
    path.closeSubpath()
    return path


def _cloud() -> QPainterPath:
    path = QPainterPath()
    path.moveTo(10.0, BOTTOM - 2.0)
    path.cubicTo(2.0, 56.0, 8.0, 44.0, 22.0, 46.0)
    path.cubicTo(18.0, 28.0, 40.0, TOP - 2.0, 52.0, 32.0)
    path.cubicTo(62.0, 20.0, 84.0, 26.0, 82.0, 44.0)
    path.cubicTo(96.0, 46.0, 98.0, 66.0, 86.0, BOTTOM - 2.0)
    path.closeSubpath()
    return path


#: shape name -> outline, keyed by the very strings the specs offer as choices,
#: so a name that loses its outline is caught by the smoke test rather than
#: showing up as a blank entry
_OUTLINES: dict[str, Callable[[], QPainterPath]] = {
    # flowchart
    "Rectangle": _rectangle,
    "Rounded": _rounded,
    "Stadium": _stadium,
    "Subroutine": _subroutine,
    "Cylinder": _cylinder,
    "Circle": _circle,
    "Double circle": _double_circle,
    "Rhombus": _rhombus,
    "Hexagon": _hexagon,
    "Parallelogram": _parallelogram,
    "Trapezoid": _trapezoid,
    "Asymmetric": _asymmetric,
    # use case
    "Ellipse": _ellipse,
    # mindmap
    "Plain": _plain,
    "Square": _square,
    "Bang": _bang,
    "Cloud": _cloud,
}


# ------------------------------------------------------------------ painted #


def icon(name: str, size: int = SIZE) -> QIcon:
    """An outline of the shape called ``name``, or an empty icon if unknown.

    Returning an empty icon rather than raising keeps callers simple: a combo
    box can add every choice with whatever comes back, including the value of a
    document written before this shape existed.
    """
    if name not in _OUTLINES:
        return QIcon()
    application = QGuiApplication.instance()
    if application is None:
        return QIcon()
    colour = application.palette().color(QPalette.ColorRole.WindowText)
    return _painted(name, size, colour.name())


@functools.lru_cache(maxsize=None)
def _painted(name: str, size: int, colour: str) -> QIcon:
    """The drawing itself, cached per shape, size and colour.

    Worth caching: the property form is rebuilt on every selection, and the
    result only changes when the palette does.
    """
    pixels = size * SCALE
    pixmap = QPixmap(pixels, pixels)
    pixmap.fill(Qt.GlobalColor.transparent)

    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    painter.scale(pixels / BOX, pixels / BOX)
    pen = QPen(QColor(colour))
    pen.setWidthF(PEN)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    painter.setPen(pen)
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.drawPath(_OUTLINES[name]())
    painter.end()

    pixmap.setDevicePixelRatio(SCALE)
    return QIcon(pixmap)
