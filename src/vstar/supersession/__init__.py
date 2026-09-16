# SPDX-License-Identifier: MIT

"""V*'s append-only state-change discipline (spec/02).

V* ledgers are append-only: a component MUST NOT be mutated after it
is appended. A status change is expressed instead as a fresh VJOURNAL
"supersession" entry that references the target through ``RELATED-TO``
and carries ``CATEGORIES:status-supersession``, the new status in
``X-VSTAR-EFFECTIVE-STATUS``, and its own ``X-VSTAR-HASH``.

Two primitives live here:

:func:`supersedes`
    Constructs that VJOURNAL, refusing with
    :class:`~vstar.errors.TargetCorrupted` when the target's stored
    hash no longer verifies.

:func:`superseded`
    Projects a ledger onto one component, answering "what status does
    this ledger say it has now?".

V* defines only the encoding. Full ledger projection — state from log —
remains the consumer's job.
"""

from __future__ import annotations

from datetime import UTC, datetime

from .. import hashing
from ..errors import TargetCorrupted
from ..time import format_time, parse_time
from ..types import COMP_JOURNAL, Component, Property

__all__ = [
    "CATEGORY_STATUS_SUPERSESSION",
    "PROP_EFFECTIVE_STATUS",
    "superseded",
    "supersedes",
]

#: The ``CATEGORIES`` token marking a VJOURNAL as a supersession entry.
#: Consumers projecting a ledger match on this exact value,
#: case-insensitively.
CATEGORY_STATUS_SUPERSESSION = "status-supersession"

#: The property carrying the new status on a supersession VJOURNAL.
#:
#: Kept in this module rather than hoisted to the root package: the
#: name is meaningful only inside the supersession pattern, and a
#: root-level export invites callers to write it onto components
#: directly — precisely the mutation the append-only discipline
#: forbids.
PROP_EFFECTIVE_STATUS = "X-VSTAR-EFFECTIVE-STATUS"

#: The literal prefix every supersession UID carries. Consumers may
#: filter on it to enumerate supersession journals without parsing
#: ``CATEGORIES``, though matching the category is the spec-blessed
#: path.
_UID_PREFIX = "journal:status:"

_PROP_UID = "UID"
_PROP_DTSTAMP = "DTSTAMP"
_PROP_RELATED_TO = "RELATED-TO"
_PROP_CATEGORIES = "CATEGORIES"

#: The sentinel a missing or unparseable ``DTSTAMP`` sorts to. Aware,
#: because every datetime in this port is; the value is far enough in
#: the past that any real timestamp outranks it under "latest wins".
_ZERO_TIME = datetime(1, 1, 1, tzinfo=UTC)


def supersedes(target: Component, status: str, at: datetime) -> Component:
    """Build a supersession VJOURNAL superseding ``target``.

    The returned component carries, in order, ``UID``, ``DTSTAMP``,
    ``RELATED-TO``, ``CATEGORIES``, ``X-VSTAR-EFFECTIVE-STATUS`` and a
    freshly computed ``X-VSTAR-HASH``. ``target`` is never mutated.

    ``status`` is written verbatim. Its vocabulary is scoped to the
    *target's* component type, not the journal's: superseding a VEVENT
    writes an event status even though the carrier is a VJOURNAL.

    :raises TargetCorrupted: when ``target`` carries an
        ``X-VSTAR-HASH`` that does not verify against its own canonical
        form. Writing a supersession against a component mutated since
        it was hashed would silently attach the new status to different
        content, so the construction is refused outright. A target with
        no stored hash makes no integrity claim and is accepted.
    """
    if hashing.get_x_vstar(target) is not None:
        ok, want, got = hashing.verify_x_vstar(target)
        if not ok:
            raise TargetCorrupted(
                f"supersedes: target {target.uid()!r} hash {got} "
                f"does not match canonical form {want}"
            )

    stamp = format_time(at)
    target_uid = target.uid()

    c = Component(type=COMP_JOURNAL)
    c.set(Property(name=_PROP_UID, value=f"{_UID_PREFIX}{target_uid}:{stamp}"))
    c.set(Property(name=_PROP_DTSTAMP, value=stamp))
    c.set(Property(name=_PROP_RELATED_TO, value=target_uid))
    c.set(Property(name=_PROP_CATEGORIES, value=CATEGORY_STATUS_SUPERSESSION))
    c.set(Property(name=PROP_EFFECTIVE_STATUS, value=status))

    # The hash refresh MUST be the last mutation: it strips any
    # existing X-VSTAR-HASH before computing, so the stored value
    # covers every property written above.
    hashing.set_x_vstar(c)
    return c


def superseded(c: Component, ledger: list[Component]) -> str | None:
    """The status ``ledger`` projects onto ``c``, or ``None``.

    Walks ``ledger`` for VJOURNAL entries whose ``RELATED-TO`` names
    ``c``'s UID and whose ``CATEGORIES`` carries the supersession
    token, and returns the ``X-VSTAR-EFFECTIVE-STATUS`` of the latest
    by ``DTSTAMP``.

    Returns ``None`` when the ledger is empty, when ``c`` has no UID,
    when nothing supersedes it, or when the matching entries all lack
    the status property. "No" is an honest answer here, not a failure,
    which is why this returns an optional where :func:`supersedes`
    raises.

    Ties on ``DTSTAMP`` go to the entry later in the ledger — the scan
    is stable and takes a matching timestamp as the new best. An entry
    whose ``DTSTAMP`` is missing or unparseable sorts to the start and
    so loses to any real timestamp; it is not an error. This is a
    projection query, not a validator, and malformed ledger data is
    silently demoted rather than raised.
    """
    target_uid = c.uid()
    if target_uid == "":
        return None

    best_t = _ZERO_TIME
    best_status: str | None = None

    for entry in ledger:
        if entry.type != COMP_JOURNAL:
            continue
        rel = entry.get(_PROP_RELATED_TO)
        if rel is None or rel.value != target_uid:
            continue
        if not _categories_contain_supersession(entry):
            continue
        status_prop = entry.get(PROP_EFFECTIVE_STATUS)
        if status_prop is None:
            continue

        entry_t = _entry_dtstamp(entry)
        # Stable "latest wins": >= takes the later ledger position
        # when two entries share a timestamp, since the scan runs in
        # order.
        if best_status is None or entry_t >= best_t:
            best_t = entry_t
            best_status = status_prop.value

    return best_status


def _categories_contain_supersession(c: Component) -> bool:
    """Whether any ``CATEGORIES`` token marks ``c`` as a supersession.

    RFC 5545 §3.8.1.2 makes ``CATEGORIES`` comma-delimited, so each
    token is trimmed and compared case-insensitively rather than
    substring-matched against the raw value — otherwise
    ``status-supersession-deferred`` would falsely match.
    """
    for p in c.get_all(_PROP_CATEGORIES):
        for tok in p.value.split(","):
            if tok.strip().upper() == CATEGORY_STATUS_SUPERSESSION.upper():
                return True
    return False


def _entry_dtstamp(c: Component) -> datetime:
    """``c``'s parsed ``DTSTAMP``, or the zero sentinel."""
    raw = c.dtstamp_raw()
    if raw == "":
        return _ZERO_TIME
    return parse_time(raw) or _ZERO_TIME
