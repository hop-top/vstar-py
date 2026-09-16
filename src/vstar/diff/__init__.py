# SPDX-License-Identifier: MIT

"""Semantic equality and structural diff for V* values.

"Semantic" means *via canonical form*: two values yielding identical
canonical bytes are equal regardless of property order, parameter
order, datetime form or whitespace. The equality family therefore
inherits canonicalization's rules — notably the spec/03 rule 7
exclusion of ``X-VSTAR-HASH``, so a restamped hash never reads as a
content change.

The diff family reports property-level structural changes. Its output
is **deliberately not sorted after the fact**: pairing order and the
case-insensitive property order that :func:`of_component` emits *are*
the contract, and a port that re-sorts the result will fail the
``spec/behavior/diff`` gate.

Pairing limitations, documented rather than hidden:

- Sub-components pair by ``(type, uid)`` when both carry a UID.
  Those without one pair positionally by index within their type
  bucket, so reordering UID-less sub-components surfaces as an
  add plus a remove rather than a change.
- Repeated properties of one name pair in order: the i-th on the a
  side against the i-th on the b side, surplus becoming adds or
  removes.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from .. import canonical
from ..types import Calendar, Card, Component, Property, property_equal

__all__ = [
    "ComponentDiff",
    "DiffOp",
    "PropertyDiff",
    "calendar_equal",
    "card_equal",
    "component_equal",
    "of_calendar",
    "of_card",
    "of_component",
]

#: The spec/03 rule 7 sentinel, excluded from diff input on both
#: sides so hash drift never reports as a content change.
_X_VSTAR_HASH = "X-VSTAR-HASH"

_CALENDAR_ROOT = "VCALENDAR"


class DiffOp(Enum):
    """The kind of change one :class:`PropertyDiff` records.

    Numbering starts at 1 so no member is a default-constructible
    zero: an unset op is a bug, never silently "added".
    """

    #: Present in ``b`` but missing from ``a``.
    ADDED = 1
    #: Present in ``a`` but missing from ``b``.
    REMOVED = 2
    #: Present in both, with a differing value or parameters.
    CHANGED = 3

    def __str__(self) -> str:
        """The reference's short display token."""
        return _OP_DISPLAY.get(self, "Unknown")


#: Display spellings, mirroring Go's ``DiffOp.String()``. Display
#: text only — the behavior fixtures record lowercase tokens.
_OP_DISPLAY: dict[DiffOp, str] = {
    DiffOp.ADDED: "Added",
    DiffOp.REMOVED: "Removed",
    DiffOp.CHANGED: "Changed",
}


def _empty_property() -> Property:
    """The stand-in for "no property on this side".

    A named factory rather than ``Property("")`` inline: the empty name
    is what :func:`of_calendar`'s projection keys on to decide which
    side a removal's name lives on, and spelling it once keeps that
    agreement in one place.
    """
    return Property(name="")


@dataclass(frozen=True, slots=True)
class PropertyDiff:
    """One property-level change between two V* values.

    For :data:`DiffOp.ADDED` and :data:`DiffOp.REMOVED`, ``property``
    is the surviving side and ``old`` is the empty default. For
    :data:`DiffOp.CHANGED`, ``property`` is the new (b-side) value and
    ``old`` the original (a-side) one.
    """

    op: DiffOp
    property: Property = field(default_factory=_empty_property)
    old: Property = field(default_factory=_empty_property)


@dataclass(slots=True)
class ComponentDiff:
    """The structural changes between two components, cards or entries.

    ``path`` locates the diff site for display: empty for a top-level
    component or card, ``VCALENDAR.VEVENT[uid=…]`` for a calendar
    entry, and ``<parent>.<TYPE>[uid=…]`` or ``<parent>.<TYPE>[#n]``
    for a nested sub-diff.
    """

    path: str = ""
    properties: list[PropertyDiff] = field(default_factory=list)
    sub_diffs: list[ComponentDiff] = field(default_factory=list)

    def is_empty(self) -> bool:
        """Whether this level and every nested level record no change."""
        if self.properties:
            return False
        return all(s.is_empty() for s in self.sub_diffs)

    def __str__(self) -> str:
        """Render as a unified-diff-ish text block.

        The shape::

            --- <path>
            + NAME[;PARAM=VAL...]:VALUE
            - NAME[;PARAM=VAL...]:VALUE
            ~ NAME: <old> -> <new>

        Sub-component diffs indent two spaces per level, each opening
        with its own ``--- <path>`` header. An empty diff renders as
        the empty string.

        This output is informational — for humans and debug CLIs. It
        is not a wire format and carries no cross-implementation
        parity guarantee.
        """
        if self.is_empty():
            return ""
        out: list[str] = []
        self._write_to(out, 0)
        return "".join(out)

    def _write_to(self, out: list[str], depth: int) -> None:
        """Append this diff's lines to ``out`` at ``depth`` levels in."""
        indent = "  " * depth
        out.append(f"{indent}--- {self.path}\n")
        for pd in self.properties:
            out.append(f"{indent}{_render_property_diff(pd)}\n")
        for sd in self.sub_diffs:
            if sd.is_empty():
                continue
            sd._write_to(out, depth + 1)


def of_component(a: Component, b: Component) -> ComponentDiff:
    """The property-level difference between two components.

    Both sides are stripped of ``X-VSTAR-HASH`` first. Properties pair
    by name, case-insensitively, and the result is ordered by
    upper-cased name; sub-components pair by ``(type, uid)`` or, for
    those without a UID, positionally.
    """
    return _component_diff_at("", a, b)


def of_card(a: Card, b: Card) -> ComponentDiff:
    """The property-level difference between two cards.

    Cards have no sub-components, so ``sub_diffs`` is always empty and
    ``path`` is empty — the result is usable directly as a rendering
    root.
    """
    return ComponentDiff(
        properties=_diff_properties(
            _filter_hash_props(a.props), _filter_hash_props(b.props)
        )
    )


def of_calendar(a: Calendar, b: Calendar) -> list[ComponentDiff]:
    """The per-component difference between two calendars.

    Components pair by ``(type, uid)``, the same rule nested
    sub-components use; those present on one side only become
    all-added or all-removed entries. Unchanged pairs do not appear at
    all, so two equal calendars yield an empty list rather than a list
    of empty diffs.

    ``PRODID`` is deliberately not diffed — a calendar's identity here
    is its component set. Use :func:`calendar_equal` when ``PRODID``
    matters.
    """
    out: list[ComponentDiff] = []
    for pair in _pair_subs(a.components, b.components):
        path = _sub_path(_CALENDAR_ROOT, pair.label)
        if pair.a is None and pair.b is not None:
            out.append(_all_added_diff(path, pair.b))
        elif pair.a is not None and pair.b is None:
            out.append(_all_removed_diff(path, pair.a))
        elif pair.a is not None and pair.b is not None:
            cd = _component_diff_at(path, pair.a, pair.b)
            if not cd.is_empty():
                out.append(cd)
    return out


def component_equal(a: Component, b: Component) -> bool:
    """Whether two components are semantically equal.

    Routes through a full canonical-byte comparison, so property and
    parameter order are irrelevant and ``X-VSTAR-HASH`` is excluded.
    A component carrying TZID-tagged datetimes that need a sibling
    VTIMEZONE compares better through :func:`calendar_equal`, which
    supplies that registry.

    Named with the ``_equal`` suffix rather than a bare ``component``:
    without Go's package qualifier supplying the verb, a bare
    ``component(a, b)`` returning a boolean is unreadable, and it
    would collide with ``canonical.component``.
    """
    return canonical.component(a) == canonical.component(b)


def card_equal(a: Card, b: Card) -> bool:
    """Whether two cards are semantically equal, via canonical bytes."""
    return canonical.card(a) == canonical.card(b)


def calendar_equal(a: Calendar, b: Calendar) -> bool:
    """Whether two calendars are semantically equal, via canonical bytes.

    Handles top-level component reordering (canonicalization sorts by
    UID or TZID per spec/03 rule 6) and resolves TZID-tagged datetimes
    against the calendar's own VTIMEZONE registry.
    """
    return canonical.calendar(a) == canonical.calendar(b)


def _component_diff_at(path: str, a: Component, b: Component) -> ComponentDiff:
    """The recursive worker; ``path`` prefixes this level."""
    return ComponentDiff(
        path=path,
        properties=_diff_properties(
            _filter_hash_props(a.props), _filter_hash_props(b.props)
        ),
        sub_diffs=_diff_subs(path, a, b),
    )


def _filter_hash_props(props: list[Property]) -> list[Property]:
    """``props`` without any ``X-VSTAR-HASH`` entry."""
    return [p for p in props if p.name.upper() != _X_VSTAR_HASH]


def _diff_properties(a: list[Property], b: list[Property]) -> list[PropertyDiff]:
    """Pair properties by name and emit diffs ordered by that name.

    Grouping by upper-cased name keeps multi-valued properties (several
    ``ATTENDEE``, say) intact rather than collapsing them, and the
    sorted key walk is what produces the fixture's property order.
    """
    ga = _group_by_name(a)
    gb = _group_by_name(b)
    out: list[PropertyDiff] = []
    for key in sorted(set(ga) | set(gb)):
        out.extend(_diff_property_group(ga.get(key, []), gb.get(key, [])))
    return out


def _group_by_name(props: list[Property]) -> dict[str, list[Property]]:
    """``props`` bucketed by upper-cased name, input order preserved."""
    out: dict[str, list[Property]] = {}
    for p in props:
        out.setdefault(p.name.upper(), []).append(p)
    return out


def _diff_property_group(a: list[Property], b: list[Property]) -> list[PropertyDiff]:
    """Diff one property name across both sides.

    Instances match in order — the i-th from ``a`` against the i-th
    from ``b`` — and surplus on either side becomes an add or a
    remove.
    """
    out: list[PropertyDiff] = []
    for i in range(max(len(a), len(b))):
        if i >= len(a):
            out.append(PropertyDiff(op=DiffOp.ADDED, property=b[i]))
        elif i >= len(b):
            out.append(PropertyDiff(op=DiffOp.REMOVED, property=a[i]))
        elif not property_equal(a[i], b[i]):
            out.append(PropertyDiff(op=DiffOp.CHANGED, property=b[i], old=a[i]))
    return out


def _diff_subs(parent_path: str, a: Component, b: Component) -> list[ComponentDiff]:
    """Pair sub-components and recurse, keeping only real changes."""
    out: list[ComponentDiff] = []
    for pair in _pair_subs(a.sub, b.sub):
        path = _sub_path(parent_path, pair.label)
        if pair.a is None and pair.b is not None:
            out.append(_all_added_diff(path, pair.b))
        elif pair.a is not None and pair.b is None:
            out.append(_all_removed_diff(path, pair.a))
        elif pair.a is not None and pair.b is not None:
            cd = _component_diff_at(path, pair.a, pair.b)
            if not cd.is_empty():
                out.append(cd)
    return out


@dataclass(frozen=True, slots=True)
class _SubPair:
    """A paired set of sub-components plus its rendered path segment.

    Either side may be ``None``, marking an addition or a removal.
    """

    a: Component | None
    b: Component | None
    label: str


def _pair_subs(a_sub: list[Component], b_sub: list[Component]) -> list[_SubPair]:
    """Match sub-components by ``(type, uid)``, then positionally.

    The returned order is the contract the behavior fixtures pin:

    1. ``(type, uid)`` pairs, sorted by type then UID.
    2. UID-less buckets in type order, paired by index.
    """
    a_by_key, a_by_type = _index_subs(a_sub)
    b_by_key, b_by_type = _index_subs(b_sub)

    out: list[_SubPair] = []
    for typ, uid in sorted(set(a_by_key) | set(b_by_key)):
        out.append(
            _SubPair(
                a=a_by_key.get((typ, uid)),
                b=b_by_key.get((typ, uid)),
                label=f"{typ}[uid={uid}]",
            )
        )

    for typ in sorted(set(a_by_type) | set(b_by_type)):
        items_a = a_by_type.get(typ, [])
        items_b = b_by_type.get(typ, [])
        for i in range(max(len(items_a), len(items_b))):
            out.append(
                _SubPair(
                    a=items_a[i] if i < len(items_a) else None,
                    b=items_b[i] if i < len(items_b) else None,
                    label=f"{typ}[#{i}]",
                )
            )
    return out


def _index_subs(
    subs: list[Component],
) -> tuple[dict[tuple[str, str], Component], dict[str, list[Component]]]:
    """Split ``subs`` into UID-keyed and UID-less-by-type indexes."""
    by_key: dict[tuple[str, str], Component] = {}
    by_type: dict[str, list[Component]] = {}
    for s in subs:
        uid = s.uid()
        typ = str(s.type)
        if uid == "":
            by_type.setdefault(typ, []).append(s)
        else:
            by_key[(typ, uid)] = s
    return by_key, by_type


def _sub_path(parent: str, label: str) -> str:
    """Join a parent path with a sub-component label."""
    return label if parent == "" else f"{parent}.{label}"


def _all_added_diff(path: str, c: Component) -> ComponentDiff:
    """Render a whole component as added, recursing into its children."""
    return _all_one_sided_diff(path, c, DiffOp.ADDED)


def _all_removed_diff(path: str, c: Component) -> ComponentDiff:
    """Render a whole component as removed, recursing into its children."""
    return _all_one_sided_diff(path, c, DiffOp.REMOVED)


def _all_one_sided_diff(path: str, c: Component, op: DiffOp) -> ComponentDiff:
    """Every property of ``c`` under one op, children included.

    The property list is sorted here by upper-cased name because
    nothing else does it on this path: :func:`_diff_properties` emits
    sorted output only for the paired case.
    """
    props = [PropertyDiff(op=op, property=p) for p in _filter_hash_props(c.props)]
    props.sort(key=lambda pd: pd.property.name.upper())
    return ComponentDiff(
        path=path,
        properties=props,
        sub_diffs=[
            _all_one_sided_diff(_sub_path(path, _sub_label(s)), s, op) for s in c.sub
        ],
    )


def _sub_label(c: Component) -> str:
    """The label segment for an unpaired sub-component."""
    uid = c.uid()
    if uid == "":
        return f"{c.type}[#0]"
    return f"{c.type}[uid={uid}]"


def _render_property_diff(pd: PropertyDiff) -> str:
    """One line for one property change, without a trailing newline."""
    if pd.op is DiffOp.ADDED:
        return "+ " + _render_property(pd.property)
    if pd.op is DiffOp.REMOVED:
        return "- " + _render_property(pd.property)
    if pd.op is DiffOp.CHANGED:
        return f"~ {pd.property.name}: {pd.old.value} -> {pd.property.value}"
    return "? " + _render_property(pd.property)


def _render_property(p: Property) -> str:
    """A ``NAME[;PARAM=VAL...]:VALUE`` wire-style line for display.

    No folding and no CRLF — this is human output, not codec output.
    Parameters sort by upper-cased name so the rendering is
    deterministic whatever order they were authored in.
    """
    out = [p.name]
    for pr in sorted(p.params, key=lambda x: x.name.upper()):
        out.append(f";{pr.name}={pr.value}")
    out.append(f":{p.value}")
    return "".join(out)
