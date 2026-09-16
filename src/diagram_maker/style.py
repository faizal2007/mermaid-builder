"""The mermaid ``style`` statement, read and written as a list of properties.

``style A fill:#f9f,stroke:#333`` is a comma-separated list, and the property
editor offers a colour picker for some of those properties rather than making
everyone type hex codes.  Reading and writing the list lives here so the window
holds no mermaid syntax, and so that a property without a picker of its own
survives an edit to one that has.
"""

from __future__ import annotations

from collections.abc import Mapping

#: mermaid wants a comma inside a value written as ``\,``, such as the
#: ``stroke-dasharray:9\\,5`` in its own documentation, so only a bare comma
#: separates one property from the next
ESCAPE = "\\"


def read(text: str) -> dict[str, str]:
    """The properties in ``text``, in the order they were written."""
    properties: dict[str, str] = {}
    for chunk in _chunks(text):
        name, separator, value = chunk.partition(":")
        name = name.strip()
        if separator and name:
            properties[name] = value.strip()
    return properties


def write(properties: Mapping[str, str]) -> str:
    """``properties`` joined the way a ``style`` statement wants them."""
    return ",".join(f"{name}:{value}" for name, value in properties.items())


def update(text: str, name: str, value: str | None) -> str:
    """``text`` with ``name`` set to ``value``, or dropped when it is ``None``."""
    properties = read(text)
    if value is None:
        properties.pop(name, None)
    else:
        properties[name] = value
    return write(properties)


def _chunks(text: str) -> list[str]:
    """Split on the commas that separate properties, and no others."""
    chunks: list[str] = []
    current = ""
    for index, character in enumerate(text):
        if character == "," and (index == 0 or text[index - 1] != ESCAPE):
            chunks.append(current)
            current = ""
        else:
            current += character
    chunks.append(current)
    return chunks
