# SPDX-License-Identifier: MIT

"""Cross-implementation parity against the Go reference encoder.

Round-trip tests prove a port is self-consistent; they do not prove it
agrees with any other implementation. This file pins the encoder's exact
output length and an FNV-1a fingerprint of its bytes for every
conformance fixture, captured by running the Go reference over the
corpus at the commit this port was written against::

    go/codec/rfc5545.Encode   (Parse -> Encode)
    go/codec/rfc6350.Encode   (Parse -> Encode per card, concatenated)

A mismatch means the two implementations produce different bytes for the
same input — the exact failure the specification exists to prevent — and
it surfaces here rather than several layers away as a canonical-byte or
hash mismatch. A mutant that sorts properties on parse passes every
round-trip test in this suite and fails only here.

Regenerating: these are *reference* values, not port values. Do not
"fix" a failure by re-recording from this port. Re-run the Go encoder
over the corpus and take its numbers.
"""

from __future__ import annotations

import pytest

from _fixtures import Fixture, load_fixtures
from vstar.codec import rfc5545, rfc6350

#: ``stem`` -> ``(byte length, FNV-1a/32 of the encoded bytes)``, from Go.
REFERENCE_ICS: dict[str, tuple[int, str]] = {
    "all_day_vtodo": (236, "9dd31ea5"),
    "all_day_vtodo_variant": (258, "87ce6c23"),
    "attach_binary": (281, "5851e5ba"),
    "empty": (70, "2f1663f4"),
    "escaping": (328, "cb662b54"),
    "fold_split_utf8": (262, "6ed7b525"),
    "nested_vtimezone": (331, "a21533fe"),
    "nfc_decomposed": (234, "48d3487d"),
    "one_vtodo": (166, "95720d63"),
    "related_reltype": (585, "7a456f7b"),
    "sort_utf8_uids": (468, "0da700aa"),
    "valarm_absolute_trigger": (328, "26571f9c"),
    "vevent_duration_alarm": (342, "b8ad3ec8"),
    "vevent_status_class_transp": (283, "9912fbb9"),
    "vevent_valarm": (293, "0c2c8733"),
    "vfreebusy": (351, "9a5cd9a0"),
    "vjournal": (264, "02a2dddb"),
    "vjournal_status": (217, "30ed2d0d"),
    "vtodo_sequence_percent": (250, "a8720014"),
    "world": (538, "efd06e5e"),
}

REFERENCE_VCF: dict[str, tuple[int, str]] = {
    "escaping": (161, "d244b29f"),
    "fold_long_note": (482, "35d23e1b"),
    "grouped": (168, "2d3957c2"),
    "kind_group": (286, "3502fb09"),
    "kind_org": (119, "5e2182c1"),
    "minimal": (102, "d33d501b"),
    "with_extensions": (221, "276195de"),
}

ICS = load_fixtures("rfc5545", ".ics")
VCF = load_fixtures("rfc6350", ".vcf")


def test_the_reference_table_has_no_entries_the_corpus_dropped_fixtures_for() -> None:
    """A renamed or deleted fixture must not leave a dead entry behind.

    The parametrized tests below enumerate the *corpus*, so every fixture
    on disk is asserted and a new one without an entry fails in
    ``_reference``. This catches the reverse direction, which nothing
    else would ever read.
    """
    assert sorted(REFERENCE_ICS) == sorted(f.stem for f in ICS)
    assert sorted(REFERENCE_VCF) == sorted(f.stem for f in VCF)


def _reference(
    table: dict[str, tuple[int, str]], family: str, stem: str
) -> tuple[int, str]:
    """The reference length and fingerprint for ``stem``, or a clear failure.

    Deriving the case list from the corpus means a fixture added upstream
    becomes a test immediately. What it must not become is a silently
    passing one, so an absent entry fails here naming the fixture and how
    to record it.
    """
    if stem not in table:
        pytest.fail(
            f"{family}/{stem} has no entry in this module's reference table. "
            f"Run the Go encoder under go/ over the fixture and record "
            f"(len, fnv1a) of its exact CRLF output; never record this "
            f"port's own bytes."
        )
    return table[stem]


@pytest.mark.parametrize("fixture", ICS, ids=[f.stem for f in ICS])
def test_ics_encodes_to_the_reference_bytes(fixture: Fixture) -> None:
    out = rfc5545.encode(rfc5545.parse(fixture.input))
    assert (len(out), fnv1a(out)) == _reference(REFERENCE_ICS, "rfc5545", fixture.stem)


@pytest.mark.parametrize("fixture", VCF, ids=[f.stem for f in VCF])
def test_vcf_encodes_to_the_reference_bytes(fixture: Fixture) -> None:
    out = b"".join(rfc6350.encode(c) for c in rfc6350.parse(fixture.input))
    assert (len(out), fnv1a(out)) == _reference(REFERENCE_VCF, "rfc6350", fixture.stem)


def fnv1a(data: bytes) -> str:
    """FNV-1a (32-bit) over raw bytes, as eight lowercase hex digits."""
    h = 0x811C9DC5
    for byte in data:
        h = ((h ^ byte) * 0x01000193) & 0xFFFFFFFF
    return f"{h:08x}"
