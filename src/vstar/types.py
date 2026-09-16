# SPDX-License-Identifier: MIT

"""The V* in-memory data model and the wire-string enums.

``Property``, ``Param``, ``Component``, ``Calendar`` and ``Card``, plus
the enums every later layer builds on. Wire values are normative: a port
that changes a spelling is broken.

Order is part of the model. Properties, parameters and sub-components
are lists, and the codecs preserve wire order on parse — canonical form
is the only layer that sorts.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import TypeVar

from .date import VALUE_DATE, VALUE_PARAM, VDate, format_date, parse_date

__all__ = [
    "CLASS_CONFIDENTIAL",
    "CLASS_PRIVATE",
    "CLASS_PUBLIC",
    "COMP_ALARM",
    "COMP_CALENDAR",
    "COMP_EVENT",
    "COMP_FREE_BUSY",
    "COMP_JOURNAL",
    "COMP_TIMEZONE",
    "COMP_TODO",
    "DEFAULT_REL_TYPE",
    "EVENT_CANCELLED",
    "EVENT_CONFIRMED",
    "EVENT_TENTATIVE",
    "JOURNAL_CANCELLED",
    "JOURNAL_DRAFT",
    "JOURNAL_FINAL",
    "KIND_GROUP",
    "KIND_INDIVIDUAL",
    "KIND_ORG",
    "REL_CHILD",
    "REL_CONCEPT",
    "REL_DEPENDS_ON",
    "REL_FINISH_TO_FINISH",
    "REL_FINISH_TO_START",
    "REL_FIRST",
    "REL_NEXT",
    "REL_PARENT",
    "REL_REF_ID",
    "REL_SIBLING",
    "REL_START_TO_FINISH",
    "REL_START_TO_START",
    "TODO_CANCELLED",
    "TODO_COMPLETED",
    "TODO_IN_PROCESS",
    "TODO_NEEDS_ACTION",
    "TRANSP_OPAQUE",
    "TRANSP_TRANSPARENT",
    "Calendar",
    "Card",
    "CompType",
    "Component",
    "EventStatus",
    "JournalStatus",
    "Kind",
    "Param",
    "Property",
    "RelType",
    "TodoStatus",
    "Transp",
    "VClass",
    "equal_fold",
    "parse_rel_type",
    "property_equal",
]


_OpenEnumT = TypeVar("_OpenEnumT", bound=StrEnum)


def _open_member(cls: type[_OpenEnumT], value: object) -> _OpenEnumT | None:
    """Build a pseudo-member of ``cls`` carrying ``value`` verbatim.

    The V* wire-string enums that RFC registries leave open —
    :class:`CompType`, :class:`Kind` — mirror Go's ``type X string``:
    the constants name a vocabulary, they do not bound it. Rejecting an
    unregistered value at the model layer would make the parser lossy
    where the spec asks it to be strict only about structure, and it
    would turn a document a validator should merely *report* on into one
    a codec cannot read at all.
    """
    if not isinstance(value, str):
        return None
    member = str.__new__(cls, value)
    member._name_ = value
    member._value_ = value
    return member


class CompType(StrEnum):
    """The wire-string component type of a :class:`Component`.

    Mirrors the RFC 5545 §3.4 + §3.6 component identifiers exactly.
    ``VCARD`` is deliberately absent — vCards are :class:`Card` values,
    not components.

    The type is **open**, mirroring Go's ``type CompType string``: the
    constants name the vocabulary V* models, they do not bound it. A
    document nests ``STANDARD`` and ``DAYLIGHT`` inside a ``VTIMEZONE``
    and may carry ``X-``-prefixed extensions, and a parser that refused
    them would be lossy where the spec asks it to be strict only about
    structure. An unregistered wire string becomes a member carrying
    that string verbatim; reporting it is the validation layer's job.
    """

    CALENDAR = "VCALENDAR"
    TODO = "VTODO"
    JOURNAL = "VJOURNAL"
    EVENT = "VEVENT"
    FREE_BUSY = "VFREEBUSY"
    TIMEZONE = "VTIMEZONE"
    ALARM = "VALARM"

    @classmethod
    def _missing_(cls, value: object) -> CompType | None:
        """Admit an unregistered wire string as a pseudo-member."""
        return _open_member(cls, value)


COMP_CALENDAR = CompType.CALENDAR
COMP_TODO = CompType.TODO
COMP_JOURNAL = CompType.JOURNAL
COMP_EVENT = CompType.EVENT
COMP_FREE_BUSY = CompType.FREE_BUSY
COMP_TIMEZONE = CompType.TIMEZONE
COMP_ALARM = CompType.ALARM


class Kind(StrEnum):
    """The wire-string ``KIND`` value for a :class:`Card`.

    RFC 6350 §6.1.4; values are lowercase per the RFC's IANA registry.
    The empty member means the property is absent.

    Open for the same reason as :class:`CompType`: the RFC also lists
    ``location`` and permits ``X-``-prefixed extensions, so an
    unregistered wire string is kept verbatim rather than rejected.
    """

    NONE = ""
    INDIVIDUAL = "individual"
    ORG = "org"
    GROUP = "group"

    @classmethod
    def _missing_(cls, value: object) -> Kind | None:
        """Admit an unregistered wire string as a pseudo-member."""
        return _open_member(cls, value)


KIND_INDIVIDUAL = Kind.INDIVIDUAL
KIND_ORG = Kind.ORG
KIND_GROUP = Kind.GROUP


class TodoStatus(StrEnum):
    """The wire-string ``STATUS`` value for a VTODO (RFC 5545 §3.8.1.11).

    :class:`TodoStatus`, :class:`EventStatus` and :class:`JournalStatus`
    are deliberately distinct types even though the cancellation value
    is spelled identically in all three: the RFC scopes each vocabulary
    to one component type, and separate types make a cross-type
    assignment a type error rather than a wire-level conformance bug.
    """

    NEEDS_ACTION = "NEEDS-ACTION"
    IN_PROCESS = "IN-PROCESS"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


TODO_NEEDS_ACTION = TodoStatus.NEEDS_ACTION
TODO_IN_PROCESS = TodoStatus.IN_PROCESS
TODO_COMPLETED = TodoStatus.COMPLETED
TODO_CANCELLED = TodoStatus.CANCELLED


class EventStatus(StrEnum):
    """The wire-string ``STATUS`` value for a VEVENT (RFC 5545 §3.8.1.11)."""

    TENTATIVE = "TENTATIVE"
    CONFIRMED = "CONFIRMED"
    CANCELLED = "CANCELLED"


EVENT_TENTATIVE = EventStatus.TENTATIVE
EVENT_CONFIRMED = EventStatus.CONFIRMED
EVENT_CANCELLED = EventStatus.CANCELLED


class JournalStatus(StrEnum):
    """The wire-string ``STATUS`` value for a VJOURNAL (RFC 5545 §3.8.1.11)."""

    DRAFT = "DRAFT"
    FINAL = "FINAL"
    CANCELLED = "CANCELLED"


JOURNAL_DRAFT = JournalStatus.DRAFT
JOURNAL_FINAL = JournalStatus.FINAL
JOURNAL_CANCELLED = JournalStatus.CANCELLED


class VClass(StrEnum):
    """The wire-string ``CLASS`` value per RFC 5545 §3.8.1.3.

    Named ``VClass`` rather than ``Class`` because ``class`` is a
    reserved word. The RFC assigns ``PUBLIC`` when the property is
    absent; that default is applied by the ``or_default`` helper, never
    by a plain getter.
    """

    PUBLIC = "PUBLIC"
    PRIVATE = "PRIVATE"
    CONFIDENTIAL = "CONFIDENTIAL"


CLASS_PUBLIC = VClass.PUBLIC
CLASS_PRIVATE = VClass.PRIVATE
CLASS_CONFIDENTIAL = VClass.CONFIDENTIAL


class Transp(StrEnum):
    """The wire-string ``TRANSP`` value per RFC 5545 §3.8.2.7."""

    OPAQUE = "OPAQUE"
    TRANSPARENT = "TRANSPARENT"


TRANSP_OPAQUE = Transp.OPAQUE
TRANSP_TRANSPARENT = Transp.TRANSPARENT

#: The wire-string ``RELTYPE`` parameter value on a ``RELATED-TO``.
#:
#: RFC 5545 §3.2.15, extended by RFC 9253 §4 and §5. The type is
#: deliberately **open**: IANA may register further values and RFC 5545
#: permits ``X-``-prefixed extensions, so any string is a valid
#: ``RelType``. The constants below name the registered vocabulary; they
#: do not bound it.
RelType = str

# RFC 5545 §3.2.15 hierarchical relationship types.
REL_PARENT: RelType = "PARENT"
REL_CHILD: RelType = "CHILD"
REL_SIBLING: RelType = "SIBLING"

# RFC 9253 §4 temporal relationship types.
REL_FINISH_TO_START: RelType = "FINISHTOSTART"
REL_FINISH_TO_FINISH: RelType = "FINISHTOFINISH"
REL_START_TO_FINISH: RelType = "STARTTOFINISH"
REL_START_TO_START: RelType = "STARTTOSTART"

# RFC 9253 §5 relationship types.
REL_DEPENDS_ON: RelType = "DEPENDS-ON"
REL_FIRST: RelType = "FIRST"
REL_NEXT: RelType = "NEXT"
REL_CONCEPT: RelType = "CONCEPT"
REL_REF_ID: RelType = "REFID"

#: The value RFC 5545 §3.2.15 assigns when ``RELTYPE`` is omitted.
DEFAULT_REL_TYPE: RelType = REL_PARENT

#: The registered ``RELTYPE`` vocabulary (RFC 9253 §11.4), keyed by
#: canonical wire string for :func:`parse_rel_type`'s folded lookup.
_REL_TYPES: dict[str, RelType] = {
    v: v
    for v in (
        REL_PARENT,
        REL_CHILD,
        REL_SIBLING,
        REL_FINISH_TO_START,
        REL_FINISH_TO_FINISH,
        REL_START_TO_FINISH,
        REL_START_TO_START,
        REL_DEPENDS_ON,
        REL_FIRST,
        REL_NEXT,
        REL_CONCEPT,
        REL_REF_ID,
    )
}


def parse_rel_type(s: str) -> tuple[RelType, bool]:
    """Fold a wire ``RELTYPE`` onto a registered constant.

    Case-insensitive per RFC 5545 §3.2. Reports whether ``s`` named a
    registered value.

    This is the one place in the API where the second return is **not**
    an optional: the first element is meaningful in both cases. An empty
    input yields ``PARENT`` with ``True`` (RFC 5545 §3.2.15: an omitted
    ``RELTYPE`` means ``PARENT``); an unregistered input is returned
    verbatim with ``False``, so a caller accepting extensions keeps the
    original spelling.
    """
    if s == "":
        return DEFAULT_REL_TYPE, True
    found = _REL_TYPES.get(s.upper())
    if found is not None:
        return found, True
    return s, False


def equal_fold(r: RelType, s: str) -> bool:
    """Whether ``r`` and ``s`` name the same ``RELTYPE``, case-insensitively."""
    return r.upper() == s.upper()


@dataclass(slots=True)
class Param:
    """A single property parameter (e.g. ``CN=Jad`` on ``ATTENDEE``).

    Name comparisons are case-insensitive per RFC 5545 §3.2 /
    RFC 6350 §5; value comparisons are case-sensitive at this layer.
    """

    name: str
    value: str


@dataclass(slots=True)
class Property:
    """One iCalendar/vCard content line in struct form.

    A name, zero or more parameters, and a value. The wire format is the
    codec's business — this layer is pure data.
    """

    name: str
    params: list[Param] = field(default_factory=list)
    value: str = ""


def _sorted_params(params: list[Param]) -> list[Param]:
    """A copy of ``params`` sorted by uppercased name; input unmutated."""
    return sorted(params, key=lambda p: p.name.upper())


def property_equal(a: Property, b: Property) -> bool:
    """Whether two properties are semantically equal.

    Case-insensitive name and parameter-name comparisons, case-sensitive
    value comparisons, and parameter order normalized alphabetically
    before comparing. Inputs are not mutated.

    Named ``property_equal`` rather than ``equal``: in Go the package
    qualifier (``vstar.Equal``) carries the meaning, and a bare ``equal``
    exported from a package root does not.
    """
    if a.name.upper() != b.name.upper():
        return False
    if a.value != b.value:
        return False
    if len(a.params) != len(b.params):
        return False
    for x, y in zip(_sorted_params(a.params), _sorted_params(b.params), strict=True):
        if x.name.upper() != y.name.upper() or x.value != y.value:
            return False
    return True


def _find(props: list[Property], name: str) -> Property | None:
    wanted = name.upper()
    for p in props:
        if p.name.upper() == wanted:
            return p
    return None


def _find_all(props: list[Property], name: str) -> list[Property]:
    wanted = name.upper()
    return [p for p in props if p.name.upper() == wanted]


def _replace(props: list[Property], p: Property) -> list[Property]:
    """Replace every same-named property with one copy of ``p``.

    The replacement lands in the first match's position; when nothing
    matches, ``p`` is appended.
    """
    wanted = p.name.upper()
    out: list[Property] = []
    replaced = False
    for existing in props:
        if existing.name.upper() == wanted:
            if not replaced:
                out.append(p)
                replaced = True
            continue
        out.append(existing)
    if not replaced:
        out.append(p)
    return out


def _without(props: list[Property], name: str) -> list[Property]:
    wanted = name.upper()
    return [p for p in props if p.name.upper() != wanted]


def _param_value(p: Property, name: str) -> str | None:
    wanted = name.upper()
    for param in p.params:
        if param.name.upper() == wanted:
            return param.value
    return None


def _has_value_date(p: Property) -> bool:
    """Whether ``p`` carries ``VALUE=DATE``.

    Both halves compare case-insensitively: parameter names are
    case-insensitive per RFC 5545 §3.2, and the ``VALUE`` argument is a
    registered value-type token (§3.2.20), likewise case-insensitive.
    """
    v = _param_value(p, VALUE_PARAM)
    return v is not None and v.upper() == VALUE_DATE


@dataclass(slots=True)
class Component:
    """One iCalendar component: a typed identifier, properties, children.

    VEVENT, VTODO, VCALENDAR and friends. Sub-components nest
    (VTIMEZONE inside VCALENDAR; VALARM inside VEVENT).
    """

    type: CompType
    props: list[Property] = field(default_factory=list)
    sub: list[Component] = field(default_factory=list)

    def get(self, name: str) -> Property | None:
        """The first property matching ``name`` (case-insensitive)."""
        return _find(self.props, name)

    def get_all(self, name: str) -> list[Property]:
        """Every property matching ``name``, in wire order."""
        return _find_all(self.props, name)

    def set(self, p: Property) -> None:
        """Replace every property named ``p.name`` with one copy of ``p``."""
        self.props = _replace(self.props, p)

    def add(self, p: Property) -> None:
        """Append ``p``, leaving same-named properties untouched."""
        self.props.append(p)

    def remove(self, name: str) -> None:
        """Delete every property matching ``name``. A no-op when none do."""
        self.props = _without(self.props, name)

    def uid(self) -> str:
        """The ``UID`` property value, or ``""`` when absent."""
        p = self.get("UID")
        return p.value if p is not None else ""

    def dtstamp_raw(self) -> str:
        """The ``DTSTAMP`` value as the raw wire string, or ``""``."""
        p = self.get("DTSTAMP")
        return p.value if p is not None else ""

    def is_date_only(self, name: str) -> bool:
        """Whether the named property is present and carries ``VALUE=DATE``.

        This is the branch point for callers that do not know the wire
        form up front::

            if c.is_date_only("DUE"):
                d = c.due_date()
            else:
                t = c.due(cal)

        ``False`` for an absent property.
        """
        p = self.get(name)
        return p is not None and _has_value_date(p)

    def _date_prop(self, name: str) -> VDate | None:
        """Parse a date-bearing property's value.

        ``None`` for a missing property, one that does not declare
        ``VALUE=DATE``, or a malformed DATE value.

        The ``VALUE=DATE`` requirement is deliberate, not merely
        defensive: an untagged ``20260515`` declares itself DATE-TIME by
        default and is simply torn data. Promoting it to a ``VDate``
        would be the silent coercion the parsers exist to prevent.
        """
        p = self.get(name)
        if p is None or not _has_value_date(p):
            return None
        return parse_date(p.value)

    def dtstart_date(self) -> VDate | None:
        """``DTSTART`` as a calendar date, when it carries ``VALUE=DATE``.

        A midnight DATE-TIME does not surface here — see :class:`VDate`
        for why the two are not interchangeable.
        """
        return self._date_prop("DTSTART")

    def dtend_date(self) -> VDate | None:
        """``DTEND`` as a calendar date.

        Note RFC 5545 §3.6.1: for an all-day event ``DTEND`` is
        EXCLUSIVE — a one-day event on the 15th has
        ``DTEND;VALUE=DATE:20260516``. This reports the wire value as
        written and does not adjust it.
        """
        return self._date_prop("DTEND")

    def due_date(self) -> VDate | None:
        """``DUE`` as a calendar date — the all-day-task reader."""
        return self._date_prop("DUE")

    def completed_date(self) -> VDate | None:
        """``COMPLETED`` as a calendar date.

        RFC 5545 §3.8.2.1 defines ``COMPLETED`` as DATE-TIME only, so a
        ``VALUE=DATE`` ``COMPLETED`` is non-conforming input. The
        accessor exists for symmetry and to let readers recover such a
        value rather than lose it.
        """
        return self._date_prop("COMPLETED")

    def _set_or_clear_date(self, name: str, d: VDate) -> None:
        """Write a date-only value, or remove it for the zero date.

        The written property carries exactly one parameter,
        ``VALUE=DATE``, and nothing else. Dropping pre-existing
        parameters is required here, not merely tidy: a stale ``TZID``
        from a prior local-time form would be meaningless on a DATE
        (RFC 5545 §3.2.19 scopes ``TZID`` to DATE-TIME and TIME values),
        and a stale parameter set would make the canonical bytes depend
        on the property's edit history.
        """
        if d.is_zero():
            self.remove(name)
            return
        self.set(
            Property(
                name=name,
                params=[Param(VALUE_PARAM, VALUE_DATE)],
                value=format_date(d),
            )
        )

    def set_dtstart_date(self, d: VDate) -> None:
        """Write an all-day ``DTSTART``; the zero date removes it."""
        self._set_or_clear_date("DTSTART", d)

    def set_dtend_date(self, d: VDate) -> None:
        """Write an all-day ``DTEND``.

        Per RFC 5545 §3.6.1 the all-day ``DTEND`` is EXCLUSIVE: to
        express a one-day event on the 15th, pass the 16th. This writes
        what it is given and does not adjust.
        """
        self._set_or_clear_date("DTEND", d)

    def set_due_date(self, d: VDate) -> None:
        """Write an all-day ``DUE`` — the all-day-task writer."""
        self._set_or_clear_date("DUE", d)

    def set_completed_date(self, d: VDate) -> None:
        """Write a date-only ``COMPLETED``.

        RFC 5545 §3.8.2.1 mandates DATE-TIME for ``COMPLETED``, so this
        emits non-conforming output. It exists for symmetry.
        """
        self._set_or_clear_date("COMPLETED", d)

    def _time_prop(self, name: str, cal: Calendar) -> datetime | None:
        """Parse a time-bearing property, consulting ``cal`` for a ``TZID``.

        ``None`` for a missing property, a malformed value, or an
        unresolvable ``TZID``.

        A property declaring ``VALUE=DATE`` is refused outright: it holds
        a calendar date, not an instant, and the two are not
        interchangeable. Returning its midnight would make an all-day
        value indistinguishable from one due at 00:00:00Z. Read such
        properties through the date-typed accessors, or branch on
        :meth:`is_date_only`.

        Every accessor below funnels through here, so the strict,
        non-inferring semantics are encoded exactly once.
        """
        from .time import parse_time, parse_time_with_tzid

        p = self.get(name)
        if p is None or _has_value_date(p):
            return None
        tzid = _param_value(p, "TZID")
        if tzid is not None:
            return parse_time_with_tzid(p.value, tzid, cal)
        return parse_time(p.value)

    def dtstart(self, cal: Calendar) -> datetime | None:
        """``DTSTART`` as an instant, resolving a ``TZID`` against ``cal``.

        The calendar argument is not optional plumbing: the VTIMEZONE
        registry lives on the :class:`Calendar`, not on the
        :class:`Component`, so a component alone has nothing to resolve
        a local time against. A plain UTC value never touches ``cal``.
        """
        return self._time_prop("DTSTART", cal)

    def dtend(self, cal: Calendar) -> datetime | None:
        """``DTEND`` as an instant; semantics match :meth:`dtstart`."""
        return self._time_prop("DTEND", cal)

    def due(self, cal: Calendar) -> datetime | None:
        """``DUE`` as an instant; semantics match :meth:`dtstart`."""
        return self._time_prop("DUE", cal)

    def completed(self, cal: Calendar) -> datetime | None:
        """``COMPLETED`` as an instant.

        RFC 5545 §3.8.2.1 requires this property to be UTC. The ``cal``
        argument is accepted for signature uniformity; a form #1 value
        with a ``TZID`` would resolve, but a conforming producer never
        writes one.
        """
        return self._time_prop("COMPLETED", cal)

    def dtstamp(self) -> datetime | None:
        """``DTSTAMP`` as an instant.

        No calendar argument: RFC 5545 §3.8.7.2 requires ``DTSTAMP`` to
        be UTC, so there is never a zone to resolve — and a ``TZID`` on
        it is a producer bug, rejected here rather than resolved.

        This is the ergonomic accessor; :meth:`dtstamp_raw` returns the
        wire string for codec-level callers.
        """
        from .time import parse_time

        p = self.get("DTSTAMP")
        if p is None or _has_value_date(p):
            return None
        if _param_value(p, "TZID") is not None:
            return None
        return parse_time(p.value)

    def _set_or_clear_time(self, name: str, t: datetime | None) -> None:
        """Write a UTC form #2 value, or remove the property for ``None``.

        The written property carries **no** parameters. Dropping any it
        had is required, not merely tidy: a stale ``TZID`` would
        contradict a value now spelled in UTC, a stale ``VALUE=DATE``
        would claim a DATE while carrying a DATE-TIME, and either would
        make the canonical bytes depend on the property's edit history.
        """
        from .time import format_time

        value = format_time(t)
        if value == "":
            self.remove(name)
            return
        self.set(Property(name=name, value=value))

    def set_dtstart(self, t: datetime | None) -> None:
        """Write a UTC form #2 ``DTSTART``; ``None`` removes the property.

        For an all-day ``DTSTART`` use :meth:`set_dtstart_date`.
        """
        self._set_or_clear_time("DTSTART", t)

    def set_dtend(self, t: datetime | None) -> None:
        """Write a UTC form #2 ``DTEND``; semantics match :meth:`set_dtstart`."""
        self._set_or_clear_time("DTEND", t)

    def set_due(self, t: datetime | None) -> None:
        """Write a UTC form #2 ``DUE``; semantics match :meth:`set_dtstart`."""
        self._set_or_clear_time("DUE", t)

    def set_completed(self, t: datetime | None) -> None:
        """Write a UTC form #2 ``COMPLETED``, which RFC 5545 §3.8.2.1 mandates."""
        self._set_or_clear_time("COMPLETED", t)


@dataclass(slots=True)
class Calendar:
    """The top-level VCALENDAR container per RFC 5545 §3.4.

    The ``PRODID`` of the producing system plus its contained
    components. Deliberately small at this layer; canonicalization,
    validation and supersession live in their own modules.
    """

    prod_id: str = ""
    components: list[Component] = field(default_factory=list)

    def find(self, uid: str) -> Component | None:
        """The first component whose ``UID`` matches, or ``None``.

        UID comparison is case-sensitive per RFC 5545 §3.8.4.7 — UIDs
        are opaque identifiers, not user-facing text.
        """
        for comp in self.components:
            if comp.uid() == uid:
                return comp
        return None

    def append(self, comp: Component) -> None:
        """Add ``comp`` to the component list."""
        self.components.append(comp)

    def filter(self, t: CompType) -> list[Component]:
        """Every component of the requested type, in order."""
        return [c for c in self.components if c.type == t]


@dataclass(slots=True)
class Card:
    """A top-level VCARD per RFC 6350.

    Structurally analogous to :class:`Component` but distinct: vCards do
    not nest sub-components and carry no :class:`CompType`.
    """

    uid: str = ""
    kind: Kind = Kind.NONE
    props: list[Property] = field(default_factory=list)

    def get(self, name: str) -> Property | None:
        """The first property matching ``name`` (case-insensitive)."""
        return _find(self.props, name)

    def get_all(self, name: str) -> list[Property]:
        """Every property matching ``name``, in wire order."""
        return _find_all(self.props, name)

    def set(self, p: Property) -> None:
        """Replace every property named ``p.name`` with one copy of ``p``."""
        self.props = _replace(self.props, p)

    def add(self, p: Property) -> None:
        """Append ``p``, leaving same-named properties untouched."""
        self.props.append(p)

    def remove(self, name: str) -> None:
        """Delete every property matching ``name``. A no-op when none do."""
        self.props = _without(self.props, name)
