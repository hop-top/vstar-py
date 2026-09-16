# SPDX-License-Identifier: MIT

"""The ``X-VSTAR-HASH`` gate: ``sha256:`` over the canonical bytes.

The corpus ``.hash`` comparison lives with the canonical tests, where the
byte comparison it backstops also lives. This file pins the API shape —
the prefix, the exclusion rule, the three-value verification result — and
the behaviours no fixture reaches.
"""

from __future__ import annotations

import hashlib
import re

import pytest

from _fixtures import CONFORMANCE_DIR
from vstar import Calendar, Card, Component, CompType, Property, hashing
from vstar.canonical import calendar as canonical_calendar
from vstar.canonical import card as canonical_card
from vstar.canonical import component as canonical_component
from vstar.codec import rfc5545

_SHA256 = re.compile(r"\Asha256:[0-9a-f]{64}\Z")


def _event(*props: Property, uid: str = "u1") -> Component:
    """A VEVENT carrying ``props`` plus a UID."""
    return Component(type=CompType.EVENT, props=[Property("UID", [], uid), *props])


def test_the_property_name_constant_lives_in_hashing() -> None:
    """The constant is a hashing concern and is not hoisted to the root.

    The string is meaningful only in company with the functions that
    write and read it, and rule 7's exclusion of that property is a
    hashing concern. A port re-exporting it from the root has diverged.
    """
    assert hashing.X_VSTAR_HASH_PROPERTY == "X-VSTAR-HASH"
    import vstar

    assert not hasattr(vstar, "X_VSTAR_HASH_PROPERTY")


def test_component_hash_carries_the_sha256_prefix() -> None:
    """The prefix is part of the value, not decoration."""
    assert _SHA256.match(hashing.component(_event())) is not None


def test_calendar_hash_carries_the_sha256_prefix() -> None:
    """Same shape for a whole calendar."""
    assert _SHA256.match(hashing.calendar(Calendar(prod_id="x"))) is not None


def test_card_hash_carries_the_sha256_prefix() -> None:
    """Same shape for a vCard."""
    assert _SHA256.match(hashing.card(Card(uid="u1"))) is not None


def test_component_hash_is_sha256_of_the_canonical_bytes() -> None:
    """The digest is over the canonical bytes exactly, with nothing added."""
    c = _event(Property("SUMMARY", [], "hello"))
    want = hashlib.sha256(canonical_component(c)).hexdigest()
    assert hashing.component(c) == f"sha256:{want}"


def test_calendar_hash_is_sha256_of_the_canonical_bytes() -> None:
    """Same relationship at the calendar level."""
    cal = Calendar(prod_id="x", components=[_event()])
    want = hashlib.sha256(canonical_calendar(cal)).hexdigest()
    assert hashing.calendar(cal) == f"sha256:{want}"


def test_card_hash_is_sha256_of_the_canonical_bytes() -> None:
    """Same relationship for a vCard."""
    c = Card(uid="u1", props=[Property("FN", [], "Jad")])
    want = hashlib.sha256(canonical_card(c)).hexdigest()
    assert hashing.card(c) == f"sha256:{want}"


def test_the_hash_is_computed_over_crlf_bytes() -> None:
    """Rule 1: hashing LF-transformed bytes would be a different digest.

    The corpus ``.hash`` siblings are the backstop for a lying byte
    comparison precisely because SHA-256 over trimmed bytes differs.
    """
    c = _event(Property("SUMMARY", [], "hello"))
    lf = canonical_component(c).replace(b"\r\n", b"\n")
    assert hashing.component(c) != f"sha256:{hashlib.sha256(lf).hexdigest()}"


def test_an_existing_hash_property_does_not_change_the_hash() -> None:
    """Rule 7: the stored hash must not feed back into its own digest."""
    plain = _event(Property("SUMMARY", [], "hello"))
    stamped = _event(
        Property("SUMMARY", [], "hello"),
        Property("X-VSTAR-HASH", [], "sha256:deadbeef"),
    )
    assert hashing.component(plain) == hashing.component(stamped)


def test_a_nested_hash_property_does_not_change_the_calendar_hash() -> None:
    """Rule 7's exclusion reaches every depth, not only the top level."""

    def build(with_hash: bool) -> Calendar:
        alarm = Component(
            type=CompType.ALARM, props=[Property("ACTION", [], "DISPLAY")]
        )
        if with_hash:
            alarm.props.append(Property("X-VSTAR-HASH", [], "sha256:deadbeef"))
        return Calendar(
            prod_id="x",
            components=[
                Component(
                    type=CompType.EVENT, props=[Property("UID", [], "u1")], sub=[alarm]
                )
            ],
        )

    assert hashing.calendar(build(False)) == hashing.calendar(build(True))


def test_a_card_hash_property_does_not_change_the_card_hash() -> None:
    """Rule 7 applies to a vCard the same way."""
    plain = Card(uid="u1", props=[Property("FN", [], "Jad")])
    stamped = Card(
        uid="u1",
        props=[Property("FN", [], "Jad"), Property("X-VSTAR-HASH", [], "sha256:bad")],
    )
    assert hashing.card(plain) == hashing.card(stamped)


def test_set_x_vstar_writes_the_component_hash() -> None:
    """``set_x_vstar`` is the one writer here; it mutates its argument."""
    c = _event(Property("SUMMARY", [], "hello"))
    want = hashing.component(c)
    hashing.set_x_vstar(c)
    assert hashing.get_x_vstar(c) == want


def test_set_x_vstar_replaces_rather_than_duplicates() -> None:
    """A second call rewrites the property; it does not add another."""
    c = _event(Property("X-VSTAR-HASH", [], "sha256:stale"))
    hashing.set_x_vstar(c)
    hashing.set_x_vstar(c)
    assert len(c.get_all("X-VSTAR-HASH")) == 1


def test_set_x_vstar_is_idempotent() -> None:
    """Computing over the stripped bytes makes repeated calls stable."""
    c = _event(Property("SUMMARY", [], "hello"))
    hashing.set_x_vstar(c)
    once = hashing.get_x_vstar(c)
    hashing.set_x_vstar(c)
    assert hashing.get_x_vstar(c) == once


def test_get_x_vstar_returns_none_when_absent() -> None:
    """Absence is an optional, not a failure."""
    assert hashing.get_x_vstar(_event()) is None


def test_get_x_vstar_does_not_validate_the_stored_value() -> None:
    """Shape and freshness are ``verify_x_vstar``'s job, not this one's."""
    c = _event(Property("X-VSTAR-HASH", [], "not-a-hash"))
    assert hashing.get_x_vstar(c) == "not-a-hash"


def test_verify_x_vstar_reports_ok_want_and_got_on_success() -> None:
    """All three values come back, so a caller can say what differed."""
    c = _event(Property("SUMMARY", [], "hello"))
    hashing.set_x_vstar(c)
    ok, want, got = hashing.verify_x_vstar(c)
    assert ok is True
    assert want == got


def test_verify_x_vstar_reports_the_recomputed_hash_on_mismatch() -> None:
    """``want`` is populated regardless of ``ok`` — that is the whole point."""
    c = _event(
        Property("SUMMARY", [], "hello"),
    )
    c.set(Property("X-VSTAR-HASH", [], "sha256:0000"))
    ok, want, got = hashing.verify_x_vstar(c)
    assert ok is False
    assert got == "sha256:0000"
    assert _SHA256.match(want) is not None


def test_verify_x_vstar_reports_an_empty_got_when_no_hash_is_stored() -> None:
    """No stored hash is not ok, and ``got`` is the empty string not None."""
    ok, want, got = hashing.verify_x_vstar(_event())
    assert ok is False
    assert got == ""
    assert _SHA256.match(want) is not None


def test_verify_x_vstar_detects_a_mutated_property() -> None:
    """The corpus ``corrupt_mutated`` case in miniature."""
    c = _event(Property("SUMMARY", [], "original"))
    hashing.set_x_vstar(c)
    c.set(Property("SUMMARY", [], "tampered"))
    ok, _, _ = hashing.verify_x_vstar(c)
    assert ok is False


def test_hash_functions_do_not_mutate_their_input() -> None:
    """Every function here is pure except ``set_x_vstar``."""
    c = _event(Property("X-VSTAR-HASH", [], "sha256:deadbeef"))
    before = [(p.name, p.value) for p in c.props]
    hashing.component(c)
    hashing.verify_x_vstar(c)
    assert [(p.name, p.value) for p in c.props] == before


def test_calendar_hash_does_not_mutate_its_input() -> None:
    """The recursive strip operates on copies."""
    cal = Calendar(
        prod_id="x",
        components=[_event(Property("X-VSTAR-HASH", [], "sha256:deadbeef"))],
    )
    hashing.calendar(cal)
    assert cal.components[0].get("X-VSTAR-HASH") is not None


def test_component_hash_ignores_a_parent_calendar_by_design() -> None:
    """A component without a parent calendar has no registry to consult.

    ``hashing.component`` routes through the context-free canonical form,
    so a TZID-tagged datetime hashes over wire-form bytes. Hash the whole
    calendar to get registry-aware hashing.
    """
    from vstar import Param

    c = _event(
        Property("DTSTAMP", [], "20260101T000000Z"),
        Property("DTSTART", [Param("TZID", "America/Montreal")], "20260104T133045"),
    )
    resolved = _event(
        Property("DTSTAMP", [], "20260101T000000Z"),
        Property("DTSTART", [], "20260104T183045Z"),
    )
    assert hashing.component(c) != hashing.component(resolved)


def test_calendar_hash_resolves_tzids_against_its_own_registry() -> None:
    """The calendar-level hash is the one stable across producers."""
    from vstar import Param

    cal = rfc5545.parse(
        (CONFORMANCE_DIR / "time" / "america_montreal.ics").read_bytes()
    )
    tz = cal.components[0]
    local = Calendar(
        prod_id=cal.prod_id,
        components=[
            tz,
            _event(
                Property("DTSTAMP", [], "20260101T000000Z"),
                Property(
                    "DTSTART", [Param("TZID", "America/Montreal")], "20260104T133045"
                ),
            ),
        ],
    )
    utc = Calendar(
        prod_id=cal.prod_id,
        components=[
            tz,
            _event(
                Property("DTSTAMP", [], "20260101T000000Z"),
                Property("DTSTART", [], "20260104T183045Z"),
            ),
        ],
    )
    assert hashing.calendar(local) == hashing.calendar(utc)


def test_hashes_are_deterministic_over_100_runs() -> None:
    """A per-run variation would make every stored hash worthless."""
    data = (CONFORMANCE_DIR / "rfc5545" / "world.ics").read_bytes()
    digests = {hashing.calendar(rfc5545.parse(data)) for _ in range(100)}
    assert len(digests) == 1


def test_hash_is_indifferent_to_input_property_order() -> None:
    """The canonical sort is what makes the hash a content identity."""
    props = [
        Property("UID", [], "u1"),
        Property("DTSTAMP", [], "20260101T000000Z"),
        Property("SUMMARY", [], "hello"),
    ]
    forward = Component(type=CompType.EVENT, props=list(props))
    reverse = Component(type=CompType.EVENT, props=list(reversed(props)))
    assert hashing.component(forward) == hashing.component(reverse)


@pytest.mark.parametrize("stem", ["world", "one_vtodo", "nfc_decomposed"])
def test_hex_is_lowercase(stem: str) -> None:
    """Uppercase hex would be a different string for the same digest."""
    data = (CONFORMANCE_DIR / "rfc5545" / f"{stem}.ics").read_bytes()
    body = hashing.calendar(rfc5545.parse(data)).removeprefix("sha256:")
    assert body == body.lower()
