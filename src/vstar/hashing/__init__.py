# SPDX-License-Identifier: MIT

"""SHA-256 content hashes of V* objects, in the ``sha256:<hex>`` form.

Hashes are computed over the canonical byte form, so two implementations
that agree on canonical bytes produce identical hashes. That is the
whole point: the hash is the cheap, transportable proof that two
documents carry the same logical content, and it is only ever as good as
the byte agreement underneath it.

The ``sha256:`` prefix is part of the value, not decoration. It exists so
a future ``sha3-256:`` or ``blake3:`` is expressible without ambiguity;
v0.1 emits only ``sha256:``.

**Hash exclusion.** Rule 7 excludes ``X-VSTAR-HASH`` from the bytes its
own value is computed over — otherwise the stored hash would feed back
into its own digest. The canonical layer strips it per its own contract,
and these functions strip it again. The redundancy is deliberate: it
documents the invariant at the API boundary, so a reader here does not
have to go and confirm the canonical layer's behaviour.

Every function is pure except :func:`set_x_vstar`, which is the one
writer.
"""

from __future__ import annotations

import hashlib

from .._hash_names import X_VSTAR_HASH_PROPERTY
from ..canonical import calendar as _canonical_calendar
from ..canonical import card as _canonical_card
from ..canonical import component as _canonical_component
from ..types import Calendar, Card, Component, Property

__all__ = [
    "X_VSTAR_HASH_PROPERTY",
    "calendar",
    "card",
    "component",
    "get_x_vstar",
    "set_x_vstar",
    "verify_x_vstar",
]

_SHA256_PREFIX = "sha256:"


def component(c: Component) -> str:
    """The ``sha256:<hex>`` digest of the canonical byte form of ``c``.

    This delegates to the **context-free** canonical form, not the
    context-taking one. A component carrying ``TZID``-tagged datetimes
    therefore hashes over wire-form bytes: two timezone spellings of the
    same logical instant hash differently. For calendar-aware hashing
    that resolves ``TZID`` against a VTIMEZONE registry, hash the whole
    calendar with :func:`calendar`.

    The asymmetry mirrors the canonical layer's own, and it is correct: a
    component without a parent calendar has no registry to consult.
    """
    return _digest(_canonical_component(_strip_component(c)))


def calendar(cal: Calendar) -> str:
    """The ``sha256:<hex>`` digest of the canonical byte form of ``cal``.

    ``X-VSTAR-HASH`` is stripped at every depth — top-level components
    and their sub-components alike — before the canonical pass.
    ``TZID``-tagged datetimes resolve against the calendar's own
    VTIMEZONE registry, so this is the entry point whose result is stable
    across producers that spell the same instant differently.
    """
    return _digest(
        _canonical_calendar(
            Calendar(
                prod_id=cal.prod_id,
                components=[_strip_component(c) for c in cal.components],
            )
        )
    )


def card(c: Card) -> str:
    """The ``sha256:<hex>`` digest of the canonical byte form of ``c``."""
    return _digest(
        _canonical_card(Card(uid=c.uid, kind=c.kind, props=_filter_out_hash(c.props)))
    )


def set_x_vstar(c: Component) -> None:
    """Write :func:`component`'s result to ``c`` as the ``X-VSTAR-HASH`` property.

    An existing value is replaced, not duplicated. This mutates ``c`` —
    it is the one function here that does.

    The hash is computed over the stripped bytes, so calling this
    repeatedly on the same logical component is idempotent: the second
    call computes the same hash and rewrites the same value.
    """
    c.set(Property(name=X_VSTAR_HASH_PROPERTY, value=component(c)))


def get_x_vstar(c: Component) -> str | None:
    """The stored ``X-VSTAR-HASH`` value, or ``None`` when absent.

    The stored value's format is not validated here. A caller wanting to
    confirm both shape and freshness uses :func:`verify_x_vstar`.
    """
    p = c.get(X_VSTAR_HASH_PROPERTY)
    return p.value if p is not None else None


def verify_x_vstar(c: Component) -> tuple[bool, str, str]:
    """Recompute ``c``'s hash and compare it against the stored one.

    Returns ``(ok, want, got)``:

    - ``ok`` — whether a hash is stored AND equals the recomputed one
      exactly;
    - ``want`` — the recomputed, correct hash. Always populated,
      regardless of ``ok``;
    - ``got`` — the stored hash; the empty string when none is stored.

    All three come back whatever the outcome, so a caller can report
    *what* differed rather than only *that* something did — which is the
    difference between a usable corruption report and a shrug. This is
    why the return is a triple and not an optional.
    """
    want = component(c)
    got = get_x_vstar(c)
    if got is None:
        return False, want, ""
    return got == want, want, got


def _digest(b: bytes) -> str:
    """``sha256:`` plus the lowercase hex digest of ``b``."""
    return _SHA256_PREFIX + hashlib.sha256(b).hexdigest()


def _strip_component(c: Component) -> Component:
    """A copy of ``c`` without ``X-VSTAR-HASH``, at every depth.

    Building a fresh component rather than editing in place is what keeps
    the hash functions pure: a caller never observes the strip.
    """
    return Component(
        type=c.type,
        props=_filter_out_hash(c.props),
        sub=[_strip_component(s) for s in c.sub],
    )


def _filter_out_hash(props: list[Property]) -> list[Property]:
    """A copy of ``props`` without any ``X-VSTAR-HASH`` property."""
    return [p for p in props if p.name.upper() != X_VSTAR_HASH_PROPERTY]
