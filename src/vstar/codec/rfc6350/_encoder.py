# SPDX-License-Identifier: MIT

"""The RFC 6350 writer: one self-contained VCARD block per call."""

from __future__ import annotations

from ..._contentline import encode_param_value, escape_text, fold_line
from ...errors import MissingUid
from ...types import Card, Property
from ._parser import SUPPORTED_VERSION

__all__ = ["encode", "format_property"]


def encode(card: Card) -> bytes:
    """Encode exactly **one** card as a ``BEGIN:VCARD...END:VCARD`` block.

    The asymmetry with :func:`~vstar.codec.rfc6350.parse` is deliberate:
    parse returns a list, encode takes a single card. Encoding a list
    means calling this once per card and concatenating — which is what a
    stream encoder does.

    ``UID`` is required here, and only here. An empty ``card.uid``
    raises :class:`~vstar.MissingUid`. The parser accepts a UID-less
    VCARD, so this is the **only** place in the codec that sentinel can
    fire, and the ``malformed/missing_uid.vcf`` fixture is exercised by
    parsing the document successfully and then asking the encoder to
    refuse the result. A port implementing only the parse side passes
    that fixture silently and is wrong.

    Emission order is fixed so output is byte-stable: ``UID``, then
    ``KIND`` when set, then ``card.props`` in input order. Property
    names (the segment after any ``group.`` prefix) are uppercased per
    RFC 6350 §3.3; group prefixes keep their original case for
    round-trip fidelity.
    """
    if card.uid == "":
        raise MissingUid("encode: card has no UID")

    chunks = [
        fold_line("BEGIN:VCARD"),
        fold_line(f"VERSION:{SUPPORTED_VERSION}"),
        fold_line(f"UID:{escape_text(card.uid)}"),
    ]
    if card.kind != "":
        chunks.append(fold_line(f"KIND:{str(card.kind).lower()}"))
    chunks.extend(fold_line(format_property(p)) for p in card.props)
    chunks.append(fold_line("END:VCARD"))
    return b"".join(chunks)


def format_property(p: Property) -> str:
    """Serialize one property to its unfolded wire form.

    A group prefix survives verbatim; the bare name is uppercased;
    parameter values are DQUOTE-wrapped when they contain ``,`` ``:``
    or ``;``.
    """
    group, name = _split_group(p.name)
    parts = [f"{group}." if group else "", name.upper()]
    for par in p.params:
        parts.append(f";{par.name.upper()}={encode_param_value(par.value)}")
    parts.append(":")
    parts.append(escape_text(p.value))
    return "".join(parts)


def _split_group(s: str) -> tuple[str, str]:
    """Separate a ``group.NAME`` identifier into its group and bare name.

    With no ``.``, the group is ``""`` and the name is the whole input.
    """
    i = s.find(".")
    return (s[:i], s[i + 1 :]) if i >= 0 else ("", s)
