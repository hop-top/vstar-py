# SPDX-License-Identifier: MIT

"""Predicates and accessors for the V* ``X-*`` extension namespace.

V* extensions live in three sanctioned tiers (spec/04)::

    X-VSTAR-*     cross-system, on the stabilization track
    X-<SYSTEM>-*  owned by one consuming system (e.g. X-AGR-INTENT)
    X-EXP-*       experimental; no guarantees

The promotion path runs ``X-EXP-FOO`` → ``X-<SYSTEM>-FOO`` →
``X-VSTAR-FOO``. Removing an extension is a breaking change for
consumers; the pattern is promote-then-replace, never rename.

Classification is case-insensitive throughout, and the reservation on
``VSTAR`` and ``EXP`` covers the whole slug segment rather than a
prefix of it — ``X-VSTARLIKE-FOO`` is an ordinary system extension
owned by ``VSTARLIKE``.
"""

from __future__ import annotations

from enum import Enum

from ..types import Component, Property

__all__ = [
    "Scope",
    "extensions_by_scope",
    "is_extension",
    "scope_of",
    "system_name",
]

#: The two reserved slugs. ``VSTAR`` is the cross-system tier and
#: ``EXP`` the experimental one; neither can own a system extension.
_RESERVED_VSTAR = "VSTAR"
_RESERVED_EXP = "EXP"


class Scope(Enum):
    """How an extension name classifies under spec/04.

    :data:`Scope.NONE` is first so it reads as the default state — a
    name that is not an ``X-*`` extension at all. The members carry the
    lowercase wire token used by ``spec/behavior/ext/scopes.json`` as
    their value; :meth:`__str__` renders the reference's capitalized
    display spelling instead.

    The two spellings are deliberately separate rather than
    case-mapped: ``VStar`` does not lowercase to ``vstar`` under a
    single transform that also maps ``Experimental`` to
    ``experimental``, so folding one into the other would make the
    fixture token depend on an incidental property of the display
    string.
    """

    #: Not an ``X-*`` extension at all.
    NONE = "none"
    #: ``X-VSTAR-*`` — the cross-system tier.
    VSTAR = "vstar"
    #: ``X-<SYSTEM>-*`` — owned by one consuming system.
    SYSTEM = "system"
    #: ``X-EXP-*`` — the unstable tier.
    EXPERIMENTAL = "experimental"
    #: Has the ``X-`` prefix but matches no sanctioned tier.
    UNKNOWN = "unknown"

    def __str__(self) -> str:
        """The reference's capitalized display spelling."""
        return _DISPLAY[self]


#: The display spelling per scope, mirroring Go's ``Scope.String()``.
#: Held apart from the member values, which are the lowercase wire
#: tokens the behavior fixtures record.
_DISPLAY: dict[Scope, str] = {
    Scope.NONE: "None",
    Scope.VSTAR: "VStar",
    Scope.SYSTEM: "System",
    Scope.EXPERIMENTAL: "Experimental",
    Scope.UNKNOWN: "Unknown",
}


def is_extension(name: str) -> bool:
    """Whether ``name`` carries the RFC 5545 §3.8.8 ``X-`` prefix.

    Case-insensitive: both ``"X-FOO"`` and ``"x-foo"`` are extensions.
    The hyphen is required — ``"X"`` is an ordinary identifier, while
    ``"X-"`` is an ill-formed extension. Pair this with
    :func:`scope_of` to classify a name.
    """
    if len(name) < 2:
        return False
    return name[0] in ("X", "x") and name[1] == "-"


def scope_of(name: str) -> Scope:
    """Classify ``name`` into one of the five scopes per spec/04.

    The decision tree::

        no X- prefix                → NONE
        X-VSTAR-<NAME>, NAME != ""  → VSTAR
        X-EXP-<NAME>,   NAME != ""  → EXPERIMENTAL
        X-<SYSTEM>-<NAME>           → SYSTEM
        anything else with X-       → UNKNOWN

    Spelled ``scope_of`` rather than ``scope`` to match the reference,
    where a Go type and function cannot share one identifier.
    """
    if not is_extension(name):
        return Scope.NONE
    rest = name[2:]
    if not rest:
        return Scope.UNKNOWN
    slug, suffix = _cut_slug(rest)
    if slug is None or not suffix:
        # "X-FOO" — a slug with no suffix, or no hyphen at all.
        return Scope.UNKNOWN
    upper = slug.upper()
    if upper == _RESERVED_VSTAR:
        return Scope.VSTAR
    if upper == _RESERVED_EXP:
        return Scope.EXPERIMENTAL
    return Scope.SYSTEM


def system_name(name: str) -> str | None:
    """The owning system's slug, upper-cased, or ``None``.

    Answers "which system owns this property?", which only a
    :data:`Scope.SYSTEM` name has an answer to. Returns ``None`` for
    non-extensions, for ``X-VSTAR-*`` and ``X-EXP-*`` (neither has an
    owner system), and for malformed names lacking the
    ``<SYSTEM>-<NAME>`` structure.

    The slug is normalized to upper case so callers can compare
    without re-normalizing: ``system_name("x-agr-intent")`` is
    ``"AGR"``.
    """
    if not is_extension(name):
        return None
    slug, suffix = _cut_slug(name[2:])
    if slug is None or not slug or not suffix:
        return None
    upper = slug.upper()
    if upper in (_RESERVED_VSTAR, _RESERVED_EXP):
        return None
    return upper


def extensions_by_scope(c: Component, scope: Scope) -> list[Property]:
    """Every property on ``c`` whose name classifies into ``scope``.

    Order follows ``c.props``; nothing is sorted. Does not recurse into
    ``c.sub`` — a caller wanting the whole tree walks it themselves.

    Passing :data:`Scope.NONE` selects every non-extension property
    (``UID``, ``DTSTART`` and the rest), which is how a caller diffs
    the V* core surface apart from its extensions.
    """
    return [p for p in c.props if scope_of(p.name) is scope]


def _cut_slug(s: str) -> tuple[str | None, str]:
    """Split ``"SLUG-REST"`` at the first hyphen.

    Returns ``(None, "")`` when there is no hyphen, distinguishing
    "no slug at all" from "an empty slug", which ``("", ...)`` would
    not.
    """
    i = s.find("-")
    if i < 0:
        return None, ""
    return s[:i], s[i + 1 :]
