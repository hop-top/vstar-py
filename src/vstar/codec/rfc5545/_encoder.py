# SPDX-License-Identifier: MIT

"""The RFC 5545 writer: CRLF-terminated, 75-octet-folded output."""

from __future__ import annotations

from ..._contentline import encode_param_value, escape_text, fold_line
from ...types import Calendar, Component, Property
from ._text import SUPPORTED_VERSION, is_text_property

__all__ = ["encode", "encode_component", "encode_content_line"]


def encode(cal: Calendar) -> bytes:
    """Encode ``cal`` in RFC 5545 wire format and return the bytes.

    Output is always CRLF-terminated; physical lines are folded at 75
    octets per §3.1 using SP as the continuation lead octet. Property
    and component order are preserved from ``cal`` verbatim.

    The outer VCALENDAR wrapper is always emitted with ``VERSION:2.0``
    and a ``PRODID`` derived from ``cal.prod_id``; any VERSION/PRODID
    inside ``cal.components`` is ignored at this layer. ``PRODID`` goes
    through :func:`encode_content_line` so RFC 5545 §3.3.11 TEXT
    escaping applies — it is a TEXT-typed property.
    """
    chunks = [
        fold_line("BEGIN:VCALENDAR"),
        fold_line(f"VERSION:{SUPPORTED_VERSION}"),
        fold_line(encode_content_line(Property("PRODID", [], cal.prod_id))),
    ]
    for c in cal.components:
        chunks.extend(_component_chunks(c))
    chunks.append(fold_line("END:VCALENDAR"))
    return b"".join(chunks)


def encode_component(c: Component) -> bytes:
    """Encode one component — wrapper, properties, sub-components.

    No VCALENDAR wrapper and no VERSION/PRODID are injected. This is the
    building block canonicalization shares with the calendar encoder, so
    fold and CRLF logic stay in one place.
    """
    return b"".join(_component_chunks(c))


def _component_chunks(c: Component) -> list[bytes]:
    """The folded byte chunks of one component, depth-first."""
    tname = str(c.type).upper()
    chunks = [fold_line(f"BEGIN:{tname}")]
    chunks.extend(fold_line(encode_content_line(p)) for p in c.props)
    for s in c.sub:
        chunks.extend(_component_chunks(s))
    chunks.append(fold_line(f"END:{tname}"))
    return chunks


def encode_content_line(p: Property) -> str:
    """Render a property as a single **unfolded** wire content line.

    ``NAME[;PARAM=val...]:value``. Folding happens afterwards, on the
    assembled line — see :func:`vstar._contentline.fold_line` for why
    the order matters.

    Parameter values containing ``,`` ``;`` ``:`` or ``"`` are
    DQUOTE-wrapped per §3.2. TEXT-typed values (per the allow-list) are
    escaped per §3.3.11; every other value type emits verbatim.
    """
    parts = [p.name.upper()]
    for par in p.params:
        parts.append(f";{par.name.upper()}={encode_param_value(par.value)}")
    parts.append(":")
    parts.append(escape_text(p.value) if is_text_property(p.name) else p.value)
    return "".join(parts)
