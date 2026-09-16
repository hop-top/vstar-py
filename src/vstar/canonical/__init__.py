# SPDX-License-Identifier: MIT

"""The deterministic canonical byte form of V* objects, per spec rules 1-12.

Two V* documents containing the same logical content MUST produce
identical canonical bytes. That invariant is what the whole
specification exists to hold, and it is what makes an ``X-VSTAR-HASH``
comparable across implementations.

Every function here returns raw ``bytes``, not ``str``. The distinction
is load-bearing: the canonical form is a byte sequence, its final CRLF
is part of the value, and comparing it as re-decoded text is how a port
passes its own tests while emitting the wrong bytes.

The transforms are applied to one component in this order, which is the
order the spec fixes:

1. **Select** — drop ``X-VSTAR-HASH`` (rule 7); reduce ``ATTACH`` to URI
   form by stripping ``VALUE=BINARY`` and ``ENCODING=BASE64`` (rule 10).
2. **Resolve datetimes** on the rule-5 allow-list against the calendar's
   VTIMEZONE registry, re-emitting as UTC form #2 and dropping the
   ``TZID`` where resolution succeeds. A ``VALUE=DATE`` property is
   governed by rule 11 and is never resolved; ``RRULE`` (rule 8) and
   ``DURATION`` (rule 12) values pass through verbatim.
3. **Normalize to NFC** — each property value and each parameter value,
   individually. Not names (rule 9).
4. **Sort** — properties by name, each property's parameters by name
   (rule 2); top-level components by ``UID``, or ``TZID`` for a
   VTIMEZONE, byte-wise on UTF-8, stable, key-less last (rule 6).
   Sub-components keep input order.
5. **Assemble** each content line with escaping and parameter quoting
   (rule 4).
6. **Fold** each assembled line at 75 octets (rule 3).
7. **Terminate** every physical line with CRLF (rule 1).

Steps 5-7 belong to the RFC 5545 encoder, which owns folding, CRLF and
TEXT escaping so there is exactly one implementation of each.

NFC therefore sits **after** datetime resolution and **before** sorting
and folding. Before folding matters: normalization changes a string's
UTF-8 length — ``e`` + U+0301 is three octets, ``é`` is two — so folding
a pre-normalization string puts the break at the wrong octet, and the
damage surfaces as a canonical-byte mismatch nowhere near the bug.

Rule 3's fold counts **octets**, and a multi-byte sequence straddling
the boundary is split across the fold. An individual physical line is
therefore not necessarily valid UTF-8 on its own; unfolding rejoins it.
Retreating the cut to a character boundary would change where every
later fold lands, and therefore change the canonical bytes and the hash.
The encoder folds on ``bytes`` for exactly that reason.

Nothing here mutates its input.
"""

from __future__ import annotations

import unicodedata
from typing import TypeVar

from .._hash_names import X_VSTAR_HASH_PROPERTY
from ..codec.rfc5545 import encode, encode_component
from ..time import format_time, parse_time_with_tzid
from ..types import Calendar, Card, Component, CompType, Param, Property

__all__ = ["calendar", "card", "component", "component_in_context"]

#: Anything carrying a ``name`` the rule-2 sort can key on: a property
#: or one of its parameters.
_Named = TypeVar("_Named", Property, Param)

#: The empty calendar the context-free entry points resolve against.
#:
#: Built fresh per call rather than shared: the dataclass carries a
#: mutable component list, and a module-level singleton is a place for a
#: caller's stray append to become everyone's problem.


def _no_context() -> Calendar:
    """An empty calendar — the registry a context-free component has."""
    return Calendar()


#: The rule-5 allow-list: property names whose values are RFC 5545
#: §3.3.5 DATE-TIME and may carry a ``TZID`` the canonical form resolves.
#:
#: ``DTSTAMP`` is here even though RFC 5545 §3.8.7.2 requires it to be
#: UTC: resolving defensively catches a non-conforming producer rather
#: than emitting a TZID-tagged ``DTSTAMP`` unchanged.
_DATETIME_PROPERTIES = frozenset(
    {
        "DTSTAMP",
        "DTSTART",
        "DTEND",
        "DUE",
        "COMPLETED",
        "RECURRENCE-ID",
        "CREATED",
        "LAST-MODIFIED",
    }
)


def component(c: Component) -> bytes:
    """The canonical byte form of one component, emitting datetimes verbatim.

    This form is for components carrying no ``TZID``-tagged datetimes.
    The VTIMEZONE registry lives on the :class:`~vstar.Calendar`, not on
    the :class:`~vstar.Component`, so this entry point cannot resolve a
    ``TZID`` reference and emits the value with its parameter retained —
    output is therefore non-canonical for such a component. Use
    :func:`component_in_context` to thread the parent calendar.

    The asymmetry is real behaviour, not an overload: a component
    without a parent calendar genuinely has no registry to consult.
    """
    return component_in_context(c, _no_context())


def component_in_context(c: Component, cal: Calendar) -> bytes:
    """The canonical byte form of one component, resolving ``TZID`` against ``cal``.

    For each property on the rule-5 allow-list carrying a ``TZID``: on
    successful resolution the value is re-emitted as UTC form #2 and the
    parameter is dropped. On failure — no matching VTIMEZONE, or one
    outside the v0.1 subset — the value AND the ``TZID`` pass through
    verbatim. Canonical bytes are not deterministic across calendars
    carrying different VTIMEZONE definitions in that branch; a producer
    is expected to ship coverage inside the subset.

    A value already in UTC form #2, and one with no ``TZID`` at all, pass
    through unchanged — there is nothing to resolve.

    ``STANDARD`` and ``DAYLIGHT`` children inside a VTIMEZONE carry a
    wall-clock ``DTSTART`` that defines the transition rule itself. Those
    are deliberately not ``TZID``-tagged and pass through by design.
    """
    return encode_component(_prepare_component(c, cal))


def calendar(c: Calendar) -> bytes:
    """The canonical byte form of a full VCALENDAR.

    Top-level components are sorted per rule 6 and each is prepared
    against the calendar's own VTIMEZONE registry, so a ``TZID``-bearing
    datetime in any child resolves against a VTIMEZONE in the same
    document.

    The ``PRODID`` value is NFC-normalized here; the encoder owns its
    TEXT escaping, so no pre-escaping happens at this layer.
    """
    return encode(
        Calendar(
            prod_id=_nfc(c.prod_id),
            components=[
                _prepare_component(sub, c) for sub in _sorted_components(c.components)
            ],
        )
    )


def card(c: Card) -> bytes:
    """The canonical byte form of one VCARD::

        BEGIN:VCARD
        VERSION:4.0
        <properties sorted by name; UID is one of them>
        END:VCARD

    ``VERSION`` is promoted ahead of alphabetical order, because
    RFC 6350 §3.3 requires it immediately after ``BEGIN:VCARD``.
    ``card.uid`` and ``card.kind`` are emitted as properties, or absorbed
    when ``card.props`` already carries one of the same name.

    A vCard shares the iCalendar content-line grammar, so this routes
    through the same encoder rather than duplicating fold and escape
    logic — which also means a ``group.NAME`` identifier is uppercased
    as one unit, group prefix included.

    A vCard has no datetime or ``TZID`` concerns, so there is no context
    form.
    """
    props: list[Property] = [Property("VERSION", [], "4.0")]
    if c.uid != "" and not _has_prop(c.props, "UID"):
        props.append(Property("UID", [], c.uid))
    if c.kind != "" and not _has_prop(c.props, "KIND"):
        props.append(Property("KIND", [], str(c.kind)))
    props.extend(c.props)

    # A wire-string component type, so the encoder emits BEGIN:VCARD and
    # END:VCARD. CompType is open, which is what admits it.
    synth = Component(type=CompType("VCARD"), props=props)
    prepared = _prepare_component(synth, _no_context())

    version = next(
        (p for p in prepared.props if p.name.upper() == "VERSION"),
        None,
    )
    if version is not None:
        prepared.props = [version, *(p for p in prepared.props if p is not version)]
    return encode_component(prepared)


def _prepare_component(c: Component, cal: Calendar) -> Component:
    """A copy of ``c`` with every transform applied except assembly and folding.

    Sub-components are prepared recursively and are NOT sorted: they have
    no natural sort key, so rule 6 preserves their input order.
    """
    props = [
        _prepare_property(p, cal)
        for p in c.props
        if p.name.upper() != X_VSTAR_HASH_PROPERTY
    ]
    return Component(
        type=c.type,
        props=_sorted_by_upper_name(props),
        sub=[_prepare_component(s, cal) for s in c.sub],
    )


def _prepare_property(p: Property, cal: Calendar) -> Property:
    """A copy of ``p`` with the value and parameter transforms applied.

    TEXT escaping is deliberately absent: the RFC 5545 encoder owns the
    single authoritative escape pass on emit, using its own allow-list of
    TEXT-typed property names. Escaping here would double it.
    """
    value = _nfc(p.value)

    # Rule 11: a DATE value has no time to convert and no zone to
    # resolve, so it is emitted verbatim and the resolution registry is
    # never consulted. VALUE=DATE is RETAINED — unlike a resolved TZID it
    # is load-bearing, since the default value type for these properties
    # is DATE-TIME and an untagged eight-octet value is a malformed
    # DATE-TIME, not a DATE.
    date_only = _is_datetime_property(p.name) and _is_value_date(p.params)

    # Rule 5: a datetime property carrying a TZID resolves to UTC form #2
    # where the calendar's registry allows, and the TZID is then dropped.
    strip_tzid = date_only
    if not date_only and _is_datetime_property(p.name):
        tzid = _param_value(p.params, "TZID")
        if tzid:
            at = parse_time_with_tzid(p.value, tzid, cal)
            if at is not None:
                value = format_time(at)
                strip_tzid = True

    is_attach = p.name.upper() == "ATTACH"
    params: list[Param] = []
    for prm in p.params:
        name = prm.name.upper()
        # Rule 10: ATTACH is reference-only on emit. The value itself is
        # untouched — canonical form is best-effort for a malformed URI.
        if is_attach and name == "VALUE" and prm.value.upper() == "BINARY":
            continue
        if is_attach and name == "ENCODING" and prm.value.upper() == "BASE64":
            continue
        # A TZID on a DATE is a producer bug (RFC 5545 §3.2.19 scopes
        # TZID to DATE-TIME and TIME) and must not leak into the bytes.
        if strip_tzid and name == "TZID":
            continue
        pv = _nfc(prm.value)
        # Rule 11 upper-cases the VALUE argument so `VALUE=date` and
        # `VALUE=DATE` converge. General case-folding of other VALUE
        # tokens is deferred to v0.2, so this is scoped to that branch.
        if date_only and name == "VALUE":
            pv = pv.upper()
        params.append(Param(name=prm.name, value=pv))

    return Property(name=p.name, params=_sorted_by_upper_name(params), value=value)


def _sorted_by_upper_name(items: list[_Named]) -> list[_Named]:
    """A stable copy of ``items`` sorted by uppercased name.

    The comparison is on the uppercased ASCII name, so the code-point
    versus UTF-8 question that governs the component sort does not arise:
    property and parameter names are ASCII by RFC 5545 §3.1 /
    RFC 6350 §3.3. Python's ``sorted`` is stable, which rule 2 requires —
    two same-named properties keep their relative input order.
    """
    return sorted(items, key=lambda item: item.name.upper())


def _sorted_components(components: list[Component]) -> list[Component]:
    """A copy of ``components`` sorted per rule 6.

    By ``UID``, or by ``TZID`` for a VTIMEZONE; components with neither
    key sort last; the sort is stable, so equal keys — a producer bug —
    keep their relative input order.

    The key comparison is a plain ``str`` comparison, which in Python is
    by code point. Code-point order and UTF-8 byte order agree, so this
    *is* the byte-wise comparison rule 6 specifies and no custom
    comparator is needed. (UTF-16 code-unit order does not agree, which
    is why the TypeScript port carries one: a surrogate pair sorts at
    0xD800-0xDBFF there, below every BMP character from U+E000 up.)
    """

    def key(c: Component) -> tuple[bool, str]:
        k = _component_sort_key(c)
        # The leading flag sorts keyless components after keyed ones;
        # ``False < True``. The placeholder string is never compared
        # against a real key, because the flags differ first.
        return (k is None, k if k is not None else "")

    return sorted(components, key=key)


def _component_sort_key(c: Component) -> str | None:
    """The rule-6 sort key.

    ``TZID`` for a VTIMEZONE, which has no UID; otherwise ``UID``, then
    ``TZID`` as a last resort. ``None`` for a component carrying neither,
    which is a producer bug and sorts to the end.
    """
    if c.type == CompType.TIMEZONE:
        tz = c.get("TZID")
        if tz is not None:
            return tz.value
    uid = c.uid()
    if uid != "":
        return uid
    tz = c.get("TZID")
    return tz.value if tz is not None else None


def _param_value(params: list[Param], name: str) -> str | None:
    """The value of the first parameter named ``name``, case-insensitively."""
    wanted = name.upper()
    for prm in params:
        if prm.name.upper() == wanted:
            return prm.value
    return None


def _has_prop(props: list[Property], name: str) -> bool:
    """Whether ``props`` already carries a property named ``name``."""
    wanted = name.upper()
    return any(p.name.upper() == wanted for p in props)


def _is_datetime_property(name: str) -> bool:
    """Whether ``name`` is on the rule-5 allow-list."""
    return name.upper() in _DATETIME_PROPERTIES


def _is_value_date(params: list[Param]) -> bool:
    """Whether ``params`` declares ``VALUE=DATE``.

    Both the parameter name and its registered-token argument compare
    case-insensitively per RFC 5545 §3.2 / §3.2.20.
    """
    v = _param_value(params, "VALUE")
    return v is not None and v.upper() == "DATE"


def _nfc(s: str) -> str:
    """The NFC form of ``s``, per rule 9.

    The fast path matters and the Go reference has the same one:
    :func:`unicodedata.normalize` allocates unconditionally, and the
    overwhelming majority of values are already normalized, so the cheap
    :func:`unicodedata.is_normalized` check skips the allocation.
    """
    if unicodedata.is_normalized("NFC", s):
        return s
    return unicodedata.normalize("NFC", s)
