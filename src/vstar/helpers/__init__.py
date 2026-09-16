# SPDX-License-Identifier: MIT

"""Constructors and high-level mutators above the bare property API.

Every mutator here refreshes ``X-VSTAR-HASH`` **last**, so a caller
always receives a component whose stored hash matches its canonical
bytes. That ordering is the whole discipline: a hash computed before
the final write covers the wrong content, and nothing downstream would
notice.

Mutators that do not apply are silent no-ops rather than errors — a
``TRANSP`` set on a VTODO, a ``PRIORITY`` of 12, an unrecognized
status. Nothing is written and no hash is churned. The getters are the
symmetric half: each reports absence faithfully, and only the
``_or_default`` forms apply an RFC default.

``event_end``, ``alarm_trigger`` and ``alarm_repeat_cycle`` live in
:mod:`vstar.duration`, not here — they are duration arithmetic that
happens to take a component. :func:`alarm_fires_at` is the one alarm
helper on this side, because it composes both.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import TypeVar

from .. import hashing
from ..duration import Related, Trigger, VDuration, alarm_trigger
from ..errors import MissingUid
from ..time import format_time
from ..types import (
    COMP_ALARM,
    COMP_EVENT,
    COMP_FREE_BUSY,
    COMP_JOURNAL,
    COMP_TODO,
    Calendar,
    Card,
    Component,
    EventStatus,
    JournalStatus,
    Kind,
    Param,
    Property,
    RelType,
    TodoStatus,
    Transp,
    VClass,
    parse_rel_type,
)
from ..types import DEFAULT_REL_TYPE as _DEFAULT_REL_TYPE

__all__ = [
    "RelatedRef",
    "add_category",
    "add_related_to",
    "alarm_fires_at",
    "categories",
    "class_of",
    "class_or_default",
    "complete",
    "due",
    "event_status",
    "increment_sequence",
    "journal_status",
    "new_absolute_alarm",
    "new_alarm",
    "new_calendar",
    "new_card",
    "new_event",
    "new_free_busy",
    "new_journal",
    "new_relative_alarm",
    "new_todo",
    "percent_complete",
    "priority",
    "related_to",
    "remove_percent_complete",
    "remove_priority",
    "sequence",
    "set_categories",
    "set_class",
    "set_due",
    "set_event_status",
    "set_journal_status",
    "set_percent_complete",
    "set_priority",
    "set_sequence",
    "set_todo_status",
    "set_transp",
    "todo_status",
    "transp",
    "transp_or_default",
]

#: Every wire-string status vocabulary :func:`_enum_prop` reads. Bound
#: to :class:`~enum.StrEnum` rather than listed member by member so a
#: new vocabulary needs no change here.
_EnumT = TypeVar("_EnumT", bound=StrEnum)

#: The PRODID a calendar gets when the caller supplies none.
_DEFAULT_PROD_ID = "-//hop-top//vstar//EN"

_PROP_UID = "UID"
_PROP_DTSTAMP = "DTSTAMP"
_PROP_ACTION = "ACTION"
_PROP_TRIGGER = "TRIGGER"
_PROP_CATEGORIES = "CATEGORIES"
_PROP_CLASS = "CLASS"
_PROP_TRANSP = "TRANSP"
_PROP_RELATED_TO = "RELATED-TO"
_PROP_SEQUENCE = "SEQUENCE"
_PROP_PRIORITY = "PRIORITY"
_PROP_PERCENT = "PERCENT-COMPLETE"
_PROP_STATUS = "STATUS"
_PROP_VERSION = "VERSION"
_PROP_KIND = "KIND"

_PARAM_RELTYPE = "RELTYPE"

_CARD_VERSION = "4.0"

_PRIORITY_MIN, _PRIORITY_MAX = 0, 9
_PERCENT_MIN, _PERCENT_MAX = 0, 100

#: ``CLASS`` applies to these three component types (RFC 5545 §3.8.1.3).
_CLASS_TYPES = frozenset({COMP_EVENT, COMP_TODO, COMP_JOURNAL})
#: ``SEQUENCE`` applies to the same three (RFC 5545 §3.8.7.4).
_SEQUENCE_TYPES = _CLASS_TYPES
#: ``PRIORITY`` is scheduling-only — no VJOURNAL (RFC 5545 §3.8.1.9).
_PRIORITY_TYPES = frozenset({COMP_EVENT, COMP_TODO})


# --------------------------------------------------------------------
# Constructors
# --------------------------------------------------------------------


def new_calendar(prod_id: str) -> Calendar:
    """An empty calendar carrying ``prod_id``.

    Cannot fail, so it raises nothing. An empty ``prod_id`` takes the
    port's default rather than emitting a ``PRODID:`` with no value,
    which would be non-conforming.
    """
    return Calendar(prod_id=prod_id or _DEFAULT_PROD_ID)


def new_todo(uid: str, due_at: datetime) -> Component:
    """A VTODO with ``UID``, ``DTSTAMP``, ``DUE`` and a fresh hash.

    :raises MissingUid: on an empty ``uid``. V* requires a UID on every
        persisted component (spec/02), and a component that cannot be
        addressed cannot be superseded.
    """
    c = _stamp_uid(Component(type=COMP_TODO), uid, "new_todo")
    c.set_due(due_at)
    hashing.set_x_vstar(c)
    return c


def new_journal(uid: str, dtstart: datetime) -> Component:
    """A VJOURNAL with ``UID``, ``DTSTAMP``, ``DTSTART`` and a fresh hash.

    :raises MissingUid: on an empty ``uid``.
    """
    c = _stamp_uid(Component(type=COMP_JOURNAL), uid, "new_journal")
    c.set_dtstart(dtstart)
    hashing.set_x_vstar(c)
    return c


def new_event(uid: str, dtstart: datetime, dtend: datetime) -> Component:
    """A VEVENT with ``UID``, ``DTSTAMP``, both endpoints and a fresh hash.

    :raises MissingUid: on an empty ``uid``.
    """
    c = _stamp_uid(Component(type=COMP_EVENT), uid, "new_event")
    c.set_dtstart(dtstart)
    c.set_dtend(dtend)
    hashing.set_x_vstar(c)
    return c


def new_free_busy(uid: str, dtstart: datetime, dtend: datetime) -> Component:
    """A VFREEBUSY spanning ``dtstart`` to ``dtend``, with a fresh hash.

    :raises MissingUid: on an empty ``uid``.
    """
    c = _stamp_uid(Component(type=COMP_FREE_BUSY), uid, "new_free_busy")
    c.set_dtstart(dtstart)
    c.set_dtend(dtend)
    hashing.set_x_vstar(c)
    return c


def new_alarm(uid: str, action: str, trigger: str) -> Component:
    """A VALARM carrying ``action`` and a raw ``trigger`` value.

    ``trigger`` goes to the wire verbatim. For a checked trigger, build
    one through :func:`new_relative_alarm` or :func:`new_absolute_alarm`
    instead.

    :raises MissingUid: on an empty ``uid``. VALARM is the one RFC 5545
        type whose schema does not require a UID, but V* requires one on
        every persisted component regardless.
    """
    c = _stamp_uid(Component(type=COMP_ALARM), uid, "new_alarm")
    c.set(Property(name=_PROP_ACTION, value=action))
    c.set(Property(name=_PROP_TRIGGER, value=trigger))
    hashing.set_x_vstar(c)
    return c


def new_relative_alarm(
    uid: str, action: str, offset: VDuration, related: Related
) -> Component:
    """A VALARM firing ``offset`` from the parent's ``related`` end.

    A negative ``offset`` fires *before* the anchor, which is the usual
    case. ``RELATED=START`` is the RFC default and stays implicit on the
    wire; ``RELATED=END`` is written out.

    :raises MissingUid: on an empty ``uid``.
    """
    trigger = Trigger(relative=True, duration=offset, related=related)
    return _new_alarm_with_trigger(uid, action, trigger, "new_relative_alarm")


def new_absolute_alarm(uid: str, action: str, at: datetime) -> Component:
    """A VALARM firing at a fixed instant.

    The trigger carries ``VALUE=DATE-TIME`` explicitly, so no consumer
    has to infer which of the two forms it holds.

    :raises MissingUid: on an empty ``uid``.
    """
    trigger = Trigger(relative=False, absolute=at)
    return _new_alarm_with_trigger(uid, action, trigger, "new_absolute_alarm")


def new_card(uid: str, kind: Kind) -> Card:
    """A vCard with ``VERSION``, ``KIND`` and ``UID``.

    Cannot fail, so it raises nothing — not even on an empty ``uid``.
    The parser accepts a UID-less vCard and the *encoder* is where that
    becomes a refusal, so rejecting here would put strictness in a third
    place and contradict the codec's asymmetry.

    An empty ``kind`` becomes ``individual`` and is **written out**.
    RFC 6350 §6.1.4 treats an absent ``KIND`` as ``individual``
    implicitly, so a round-tripped card that never had one gains a
    property it did not start with. That is deliberate — the constructor
    states what it built — but it does mean a caller reproducing a
    KIND-less document must clear the property afterwards.
    """
    card = Card(uid=uid, kind=kind or Kind.INDIVIDUAL)
    card.set(Property(name=_PROP_VERSION, value=_CARD_VERSION))
    card.set(Property(name=_PROP_KIND, value=str(card.kind)))
    card.set(Property(name=_PROP_UID, value=uid))
    return card


def alarm_fires_at(alarm: Component, parent: Component, cal: Calendar) -> datetime:
    """When ``alarm`` fires, given its parent and the enclosing calendar.

    Composes :func:`~vstar.duration.alarm_trigger` with
    :meth:`~vstar.duration.Trigger.resolve`.

    :raises NoTrigger: when ``alarm`` carries no ``TRIGGER``.
    :raises NoAnchor: when a relative trigger has no anchor to measure
        from.
    :raises Malformed: when the ``TRIGGER`` value is unreadable.
    """
    return alarm_trigger(alarm).resolve(parent, cal)


# --------------------------------------------------------------------
# Categories
# --------------------------------------------------------------------


def categories(c: Component) -> list[str]:
    """``CATEGORIES`` split into tokens, trimmed, empties dropped.

    RFC 5545 §3.8.1.2 makes the value comma-delimited. A missing
    property and a property holding only separators both yield an empty
    list — "no categories" has one representation here.
    """
    p = c.get(_PROP_CATEGORIES)
    if p is None:
        return []
    return [t for t in (tok.strip() for tok in p.value.split(",")) if t]


def set_categories(c: Component, values: list[str]) -> None:
    """Replace ``CATEGORIES`` with ``values``, de-duplicated.

    Duplicates are dropped keeping first-seen order, comparison is
    case-sensitive, and each value is trimmed before both the comparison
    and the write. An empty result removes the property rather than
    writing an empty one.
    """
    deduped = _dedupe_preserve(values)
    if not deduped:
        c.remove(_PROP_CATEGORIES)
    else:
        c.set(Property(name=_PROP_CATEGORIES, value=",".join(deduped)))
    hashing.set_x_vstar(c)


def add_category(c: Component, value: str) -> None:
    """Append ``value`` to ``CATEGORIES`` unless already present.

    An empty ``value`` or one already on the list is a no-op, and no
    hash is refreshed — nothing changed, so restamping would churn the
    hash of an unaltered component.
    """
    if value == "":
        return
    current = categories(c)
    if value in current:
        return
    c.set(Property(name=_PROP_CATEGORIES, value=",".join([*current, value])))
    hashing.set_x_vstar(c)


# --------------------------------------------------------------------
# Classification and transparency
# --------------------------------------------------------------------


def class_of(c: Component) -> VClass | None:
    """``CLASS``, or ``None`` when absent or unrecognized.

    Reports absence faithfully; :func:`class_or_default` is where the
    RFC default is applied. Spelled ``class_of`` because ``class`` is a
    Python keyword.
    """
    return _enum_prop(c, _PROP_CLASS, VClass)


def class_or_default(c: Component) -> VClass:
    """``CLASS``, defaulting to ``PUBLIC`` per RFC 5545 §3.8.1.3."""
    return class_of(c) or VClass.PUBLIC


def set_class(c: Component, v: VClass) -> None:
    """Write ``CLASS``. A no-op off VEVENT, VTODO and VJOURNAL."""
    if c.type not in _CLASS_TYPES or not isinstance(v, VClass):
        return
    c.set(Property(name=_PROP_CLASS, value=str(v)))
    hashing.set_x_vstar(c)


def transp(c: Component) -> Transp | None:
    """``TRANSP``, or ``None`` when absent or unrecognized."""
    return _enum_prop(c, _PROP_TRANSP, Transp)


def transp_or_default(c: Component) -> Transp:
    """``TRANSP``, defaulting to ``OPAQUE`` per RFC 5545 §3.8.2.7."""
    return transp(c) or Transp.OPAQUE


def set_transp(c: Component, v: Transp) -> None:
    """Write ``TRANSP``. A no-op off VEVENT — only events block time."""
    if c.type != COMP_EVENT or not isinstance(v, Transp):
        return
    c.set(Property(name=_PROP_TRANSP, value=str(v)))
    hashing.set_x_vstar(c)


# --------------------------------------------------------------------
# Relations
# --------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class RelatedRef:
    """One ``RELATED-TO`` reference: the target UID and its relationship."""

    uid: str
    rel_type: RelType


def related_to(c: Component) -> list[RelatedRef]:
    """Every ``RELATED-TO`` on ``c``, in wire order.

    A reference with no ``RELTYPE`` parameter takes the RFC 5545
    §3.2.15 default, ``PARENT``. The parameter name is matched
    case-insensitively; its value goes through the open-enum parser, so
    an unregistered relationship survives rather than being discarded.
    """
    out: list[RelatedRef] = []
    for p in c.get_all(_PROP_RELATED_TO):
        rel = _DEFAULT_REL_TYPE
        for par in p.params:
            if par.name.upper() == _PARAM_RELTYPE and par.value != "":
                rel, _ = parse_rel_type(par.value)
                break
        out.append(RelatedRef(uid=p.value, rel_type=rel))
    return out


def add_related_to(c: Component, uid: str, rel_type: RelType) -> None:
    """Append a ``RELATED-TO`` naming ``uid``.

    Appends rather than replaces: a component may relate to many others,
    and each relationship is its own property. An empty ``rel_type``
    omits the parameter entirely, leaving a reader to apply the RFC
    default — which is what :func:`related_to` does.

    An empty ``uid`` is a no-op: a reference to nothing is not a
    relationship.
    """
    if uid == "":
        return
    params = [Param(_PARAM_RELTYPE, str(rel_type))] if rel_type else []
    c.add(Property(name=_PROP_RELATED_TO, params=params, value=uid))
    hashing.set_x_vstar(c)


# --------------------------------------------------------------------
# Integer-valued properties
# --------------------------------------------------------------------


def sequence(c: Component) -> int | None:
    """``SEQUENCE``, or ``None`` when absent or unparseable.

    RFC 5545 §3.7.4 defaults an absent ``SEQUENCE`` to 0, but that
    default is the caller's to apply: ``None`` and ``0`` are different
    facts, and collapsing them would hide a component that was never
    revised behind one that was revised back.
    """
    return _int_prop(c, _PROP_SEQUENCE)


def set_sequence(c: Component, n: int) -> None:
    """Write ``SEQUENCE``. A no-op for a negative ``n`` or a wrong type."""
    if c.type not in _SEQUENCE_TYPES or n < 0:
        return
    c.set(Property(name=_PROP_SEQUENCE, value=str(n)))
    hashing.set_x_vstar(c)


def increment_sequence(c: Component) -> None:
    """Bump ``SEQUENCE`` by one, treating absent or unreadable as 0.

    There is no remover to pair with this: ``SEQUENCE`` is required once
    present, and revising a component is the only way it moves.
    """
    if c.type not in _SEQUENCE_TYPES:
        return
    n = sequence(c)
    c.set(Property(name=_PROP_SEQUENCE, value=str((n or 0) + 1)))
    hashing.set_x_vstar(c)


def priority(c: Component) -> int | None:
    """``PRIORITY`` in 0-9, or ``None`` when absent or out of range.

    ``0`` is a real value meaning "undefined priority" (RFC 5545
    §3.8.1.9), distinct from the property being absent — which is why
    this returns an optional rather than defaulting.
    """
    return _int_prop(c, _PROP_PRIORITY, _PRIORITY_MIN, _PRIORITY_MAX)


def set_priority(c: Component, n: int) -> None:
    """Write ``PRIORITY``. Out-of-range values are a no-op, not clamped.

    Clamping would silently record a priority the caller did not ask
    for. Applies to VEVENT and VTODO only.
    """
    if c.type not in _PRIORITY_TYPES or not _PRIORITY_MIN <= n <= _PRIORITY_MAX:
        return
    c.set(Property(name=_PROP_PRIORITY, value=str(n)))
    hashing.set_x_vstar(c)


def remove_priority(c: Component) -> None:
    """Delete ``PRIORITY``. Safe on any component type."""
    c.remove(_PROP_PRIORITY)
    hashing.set_x_vstar(c)


def percent_complete(c: Component) -> int | None:
    """``PERCENT-COMPLETE`` in 0-100, or ``None`` when absent or invalid."""
    return _int_prop(c, _PROP_PERCENT, _PERCENT_MIN, _PERCENT_MAX)


def set_percent_complete(c: Component, n: int) -> None:
    """Write ``PERCENT-COMPLETE`` on a VTODO. Out-of-range is a no-op.

    Setting 100 here does **not** complete the task: ``STATUS`` and
    ``COMPLETED`` are untouched. Use :func:`complete` for that.
    """
    if c.type != COMP_TODO or not _PERCENT_MIN <= n <= _PERCENT_MAX:
        return
    c.set(Property(name=_PROP_PERCENT, value=str(n)))
    hashing.set_x_vstar(c)


def remove_percent_complete(c: Component) -> None:
    """Delete ``PERCENT-COMPLETE``. Safe on any component type."""
    c.remove(_PROP_PERCENT)
    hashing.set_x_vstar(c)


# --------------------------------------------------------------------
# Status
# --------------------------------------------------------------------


def todo_status(c: Component) -> TodoStatus | None:
    """``STATUS`` read under the VTODO vocabulary, or ``None``.

    Spelled ``todo_status`` rather than ``status`` so all three pairs
    read symmetrically and no caller reaches for a bare ``status``
    expecting it to work on a VEVENT.
    """
    return _enum_prop(c, _PROP_STATUS, TodoStatus)


def set_todo_status(c: Component, s: TodoStatus) -> None:
    """Write a VTODO ``STATUS``. A no-op off VTODO."""
    if c.type != COMP_TODO or not isinstance(s, TodoStatus):
        return
    c.set(Property(name=_PROP_STATUS, value=str(s)))
    hashing.set_x_vstar(c)


def event_status(c: Component) -> EventStatus | None:
    """``STATUS`` read under the VEVENT vocabulary, or ``None``."""
    return _enum_prop(c, _PROP_STATUS, EventStatus)


def set_event_status(c: Component, s: EventStatus) -> None:
    """Write a VEVENT ``STATUS``. A no-op off VEVENT."""
    if c.type != COMP_EVENT or not isinstance(s, EventStatus):
        return
    c.set(Property(name=_PROP_STATUS, value=str(s)))
    hashing.set_x_vstar(c)


def journal_status(c: Component) -> JournalStatus | None:
    """``STATUS`` read under the VJOURNAL vocabulary, or ``None``."""
    return _enum_prop(c, _PROP_STATUS, JournalStatus)


def set_journal_status(c: Component, s: JournalStatus) -> None:
    """Write a VJOURNAL ``STATUS``. A no-op off VJOURNAL."""
    if c.type != COMP_JOURNAL or not isinstance(s, JournalStatus):
        return
    c.set(Property(name=_PROP_STATUS, value=str(s)))
    hashing.set_x_vstar(c)


def complete(c: Component, t: datetime) -> None:
    """Mark a VTODO finished at ``t``.

    Writes all three of ``STATUS:COMPLETED``, ``COMPLETED`` and
    ``PERCENT-COMPLETE:100``, then refreshes the hash once. Doing it in
    one call is the point: the three together are what "done" means, and
    three separate setters would restamp the hash three times and leave
    two intermediate states in which the component disagrees with
    itself.

    A no-op off VTODO.
    """
    if c.type != COMP_TODO:
        return
    c.set(Property(name=_PROP_STATUS, value=str(TodoStatus.COMPLETED)))
    c.set_completed(t)
    c.set(Property(name=_PROP_PERCENT, value=str(_PERCENT_MAX)))
    hashing.set_x_vstar(c)


# --------------------------------------------------------------------
# Due
# --------------------------------------------------------------------


def due(c: Component, cal: Calendar) -> datetime | None:
    """``DUE`` resolved against ``cal``'s VTIMEZONE registry.

    A thin reader beside :func:`set_due`, so the pair lives in one
    place; equivalent to ``c.due(cal)``.
    """
    return c.due(cal)


def set_due(c: Component, t: datetime) -> None:
    """Write ``DUE`` in UTC form #2 and refresh the hash."""
    c.set_due(t)
    hashing.set_x_vstar(c)


# --------------------------------------------------------------------
# Internals
# --------------------------------------------------------------------


def _stamp_uid(c: Component, uid: str, what: str) -> Component:
    """Set ``UID`` then ``DTSTAMP`` on ``c``, rejecting an empty UID."""
    if uid == "":
        raise MissingUid(f"{what}: uid is empty")
    c.set(Property(name=_PROP_UID, value=uid))
    c.set(Property(name=_PROP_DTSTAMP, value=format_time(_now())))
    return c


def _now() -> datetime:
    """The current instant, UTC-aware.

    Factored out so a test can see exactly one clock call per
    construction, and so no constructor reaches for a naive
    ``datetime.now()``.
    """
    return datetime.now(UTC)


def _new_alarm_with_trigger(
    uid: str, action: str, trigger: Trigger, what: str
) -> Component:
    """Assemble a VALARM around an already-built trigger."""
    c = _stamp_uid(Component(type=COMP_ALARM), uid, what)
    c.set(Property(name=_PROP_ACTION, value=action))
    c.set(trigger.to_property())
    hashing.set_x_vstar(c)
    return c


def _dedupe_preserve(values: list[str]) -> list[str]:
    """``values`` trimmed and de-duplicated, first-seen order kept."""
    seen: set[str] = set()
    out: list[str] = []
    for v in values:
        t = v.strip()
        if t == "" or t in seen:
            continue
        seen.add(t)
        out.append(t)
    return out


def _int_prop(
    c: Component, name: str, lo: int | None = None, hi: int | None = None
) -> int | None:
    """``name``'s value as a non-negative int within ``lo``-``hi``.

    Strict on purpose: the parse must round-trip, so ``"03"``, ``"+3"``
    and ``" 3"`` are all rejected rather than quietly read as 3. A wire
    value that does not render back to itself is not the integer it
    looks like, and accepting it would make the canonical bytes depend
    on how the producer spelled it.
    """
    p = c.get(name)
    if p is None:
        return None
    try:
        n = int(p.value)
    except ValueError:
        return None
    if n < 0 or str(n) != p.value:
        return None
    if lo is not None and n < lo:
        return None
    if hi is not None and n > hi:
        return None
    return n


def _enum_prop(c: Component, name: str, enum: type[_EnumT]) -> _EnumT | None:
    """``name``'s value as a member of ``enum``, or ``None``.

    An unrecognized wire value reads as absence rather than raising: the
    getters report what they can recognize, and a value outside the
    vocabulary is something the validation layer reports, not something
    an accessor should refuse to return from.
    """
    p = c.get(name)
    if p is None:
        return None
    try:
        return enum(p.value)
    except ValueError:
        return None
