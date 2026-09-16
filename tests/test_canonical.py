# SPDX-License-Identifier: MIT

"""The canonical-form gate: byte identity against the corpus, rule by rule.

Two gates live here and they are not redundant.

The **corpus gate** walks every fixture carrying a ``.canonical`` sibling
and asserts byte identity, plus the ``.hash`` sibling over the CRLF
bytes. It is necessary and it is not sufficient: disabling NFC entirely
once passed every byte-identity fixture in an earlier revision of this
corpus, because nothing in it exercised rule 9. Four fixtures close that
today — ``fold_split_utf8`` (rule 3), ``sort_utf8_uids`` (rule 6),
``nfc_decomposed`` (rule 9) and ``attach_binary`` (rule 10) — and a
fifth, ``all_day_vtodo``, covers rule 11.

The **rule gates** are the ones below the corpus block: hand-built
inputs that isolate one rule each, so a regression names the rule it
broke rather than a fixture that happens to exercise it.

Comparison is on ``bytes``, never ``str``, and the only licensed
transform is CRLF→LF applied to *this port's* output — see
``_fixtures.crlf_to_lf`` for why the direction matters.
"""

from __future__ import annotations

import hashlib

import pytest

from _fixtures import (
    CONFORMANCE_DIR,
    assert_bytes_equal,
    crlf_to_lf,
    load_fixtures,
    physical_lines,
)
from vstar import Calendar, Card, Component, CompType, Param, Property
from vstar.canonical import calendar, card, component, component_in_context
from vstar.codec import rfc5545, rfc6350

#: Corpus families carrying ``.canonical`` / ``.hash`` siblings, and the
#: input extension each uses. Walked, never hard-coded by name.
CANONICAL_FAMILIES = (
    ("rfc5545", ".ics"),
    ("rfc6350", ".vcf"),
    ("supersession", ".ics"),
)


def _cases() -> list[tuple[str, str, bytes, bytes | None, str | None]]:
    """Every corpus case with a ``.canonical`` sibling.

    Yields ``(family, stem, input bytes, canonical bytes, hash)``. The
    tree is walked; adding a fixture upstream makes it a test with no
    edit here.
    """
    out: list[tuple[str, str, bytes, bytes | None, str | None]] = []
    for family, ext in CANONICAL_FAMILIES:
        for fixture in load_fixtures(family, ext):
            want = CONFORMANCE_DIR / family / f"{fixture.stem}.canonical"
            if not want.is_file():
                continue
            digest = CONFORMANCE_DIR / family / f"{fixture.stem}.hash"
            out.append(
                (
                    family,
                    fixture.stem,
                    fixture.input,
                    want.read_bytes(),
                    digest.read_text(encoding="utf-8").strip()
                    if digest.is_file()
                    else None,
                )
            )
    return out


CASES = _cases()
CASE_IDS = [f"{family}/{stem}" for family, stem, _, _, _ in CASES]


def _canonicalize(family: str, data: bytes) -> bytes:
    """The canonical bytes of one corpus input, per its family's shape.

    vCards canonicalize one card at a time and concatenate, matching the
    codec's own asymmetry — ``rfc6350.parse`` returns a list.
    """
    if family == "rfc6350":
        return b"".join(card(c) for c in rfc6350.parse(data))
    return calendar(rfc5545.parse(data))


def _hash_of(family: str, data: bytes) -> str:
    """The ``sha256:<hex>`` of one corpus input, per its family's shape."""
    from vstar import hashing

    if family == "rfc6350":
        cards = rfc6350.parse(data)
        assert len(cards) == 1, "the hash sibling assumes a single-card fixture"
        return hashing.card(cards[0])
    return hashing.calendar(rfc5545.parse(data))


def test_the_corpus_has_canonical_fixtures_to_walk() -> None:
    """A loader that silently finds nothing would pass every test below."""
    assert len(CASES) >= 25


@pytest.mark.parametrize(
    ("family", "stem", "data", "want", "digest"), CASES, ids=CASE_IDS
)
def test_canonical_bytes_match_the_corpus(
    family: str, stem: str, data: bytes, want: bytes, digest: str | None
) -> None:
    """Canonical bytes equal the ``.canonical`` sibling, byte for byte."""
    got = _canonicalize(family, data)
    assert_bytes_equal(crlf_to_lf(got), want, f"{family}/{stem}")


@pytest.mark.parametrize(
    ("family", "stem", "data", "want", "digest"), CASES, ids=CASE_IDS
)
def test_hash_matches_the_corpus(
    family: str, stem: str, data: bytes, want: bytes, digest: str | None
) -> None:
    """The hash equals the ``.hash`` sibling, computed over the CRLF bytes.

    Hashing the LF-transformed bytes would be a different digest, which
    is exactly why the hash siblings are the backstop for a comparison
    that lies.
    """
    if digest is None:
        pytest.skip(f"{family}/{stem} has no .hash sibling")
    assert _hash_of(family, data) == digest


@pytest.mark.parametrize(
    ("family", "stem", "data", "want", "digest"), CASES, ids=CASE_IDS
)
def test_canonical_output_is_crlf_terminated(
    family: str, stem: str, data: bytes, want: bytes, digest: str | None
) -> None:
    """Rule 1: every physical line ends CRLF, including the last.

    The ``.canonical`` comparison strips CR before LF, so a port emitting
    bare LF would pass it. Nothing else catches that.
    """
    got = _canonicalize(family, data)
    assert got.endswith(b"\r\n")
    assert b"\n" not in got.replace(b"\r\n", b"")


@pytest.mark.parametrize(
    ("family", "stem", "data", "want", "digest"), CASES, ids=CASE_IDS
)
def test_canonical_physical_lines_fit_75_octets(
    family: str, stem: str, data: bytes, want: bytes, digest: str | None
) -> None:
    """Rule 3: no physical line exceeds 75 octets, measured in UTF-8."""
    for i, line in enumerate(physical_lines(_canonicalize(family, data))):
        assert len(line) <= 75, f"{family}/{stem} physical line {i} is {len(line)}"


@pytest.mark.parametrize(
    ("family", "stem", "data", "want", "digest"), CASES, ids=CASE_IDS
)
def test_canonical_form_is_a_fixpoint(
    family: str, stem: str, data: bytes, want: bytes, digest: str | None
) -> None:
    """Canonicalizing canonical bytes returns them unchanged.

    NFC is idempotent and sorting is stable, so the canonical form is the
    equivalence-class representative — re-canonicalizing must be a no-op.
    A transform applied in the wrong order usually is not idempotent, so
    this catches ordering bugs the corpus does not reach.
    """
    once = _canonicalize(family, data)
    twice = _canonicalize(family, once)
    assert_bytes_equal(twice, once, f"{family}/{stem} refused to reach a fixpoint")


# --- Rule-level gates -------------------------------------------------
#
# Hand-built inputs, one rule each. The corpus is thin by construction;
# these name the rule that broke.


def _event(*props: Property, uid: str = "u1") -> Component:
    """A VEVENT carrying ``props`` plus a UID, for the rule gates."""
    return Component(
        type=CompType.EVENT,
        props=[Property("UID", [], uid), *props],
    )


def _wrap(*components: Component) -> Calendar:
    """A calendar around ``components`` with a fixed PRODID."""
    return Calendar(prod_id="-//test//EN", components=list(components))


def test_rule_2_sorts_properties_alphabetically_by_name() -> None:
    """Rule 2: properties emit in alphabetical order regardless of input."""
    c = Component(
        type=CompType.EVENT,
        props=[
            Property("SUMMARY", [], "z"),
            Property("UID", [], "u1"),
            Property("DTSTAMP", [], "20260101T000000Z"),
        ],
    )
    lines = [line.split(b":", 1)[0] for line in physical_lines(component(c))]
    assert lines == [b"BEGIN", b"DTSTAMP", b"SUMMARY", b"UID", b"END"]


def test_rule_2_sorts_parameters_alphabetically_by_name() -> None:
    """Rule 2: a property's parameters emit in alphabetical order too."""
    c = _event(
        Property(
            "ATTENDEE",
            [Param("ROLE", "CHAIR"), Param("CN", "Jad"), Param("CUTYPE", "INDIVIDUAL")],
            "mailto:jad@example.com",
        )
    )
    out = component(c)
    assert b"ATTENDEE;CN=Jad;CUTYPE=INDIVIDUAL;ROLE=CHAIR:" in out


def test_rule_2_property_sort_is_stable_for_repeated_names() -> None:
    """Rule 2: two same-named properties keep their relative input order."""
    c = _event(
        Property("CATEGORIES", [], "first"),
        Property("CATEGORIES", [], "second"),
    )
    out = component(c)
    assert out.index(b"CATEGORIES:first") < out.index(b"CATEGORIES:second")


def test_rule_3_folds_at_75_octets_not_76() -> None:
    """Rule 3: the first physical line is exactly 75 octets when it overflows.

    A 76-octet fold reads as "one more character fits" and produces
    output that unfolds to the same logical line, so only a byte
    comparison catches it. This pins the boundary directly.
    """
    value = "a" * 200
    out = component(_event(Property("SUMMARY", [], value)))
    lines = physical_lines(out)
    summary = next(line for line in lines if line.startswith(b"SUMMARY"))
    assert len(summary) == 75


def test_rule_3_folds_on_octets_and_may_split_a_utf8_sequence() -> None:
    """Rule 3: the fold counts octets and MAY land mid-sequence.

    ``é`` is one code point and two octets. Padding so the boundary falls
    between the two octets of one ``é`` must split it: retreating the cut
    to a character boundary changes where every later fold lands, and
    therefore changes the canonical bytes and the hash.
    """
    # "SUMMARY:" is 8 octets; 66 ASCII fillers put the 75th octet on the
    # first octet of the following é (positions 75 and 76).
    value = "a" * 66 + "é" * 5
    out = component(_event(Property("SUMMARY", [], value)))
    lines = physical_lines(out)
    first = next(line for line in lines if line.startswith(b"SUMMARY"))
    assert len(first) == 75
    # The final octet is the LEAD byte of a two-octet sequence, so this
    # physical line is not valid UTF-8 on its own.
    assert first[-1] == 0xC3
    with pytest.raises(UnicodeDecodeError):
        first.decode("utf-8")


def test_rule_3_folded_output_unfolds_to_the_original_logical_line() -> None:
    """Rule 3: a split sequence survives unfolding, which is the point."""
    value = "a" * 66 + "é" * 5
    out = component(_event(Property("SUMMARY", [], value)))
    reparsed = rfc5545.parse(
        b"BEGIN:VCALENDAR\r\nVERSION:2.0\r\nPRODID:x\r\n" + out + b"END:VCALENDAR\r\n"
    )
    summary = reparsed.components[0].get("SUMMARY")
    assert summary is not None
    assert summary.value == value


def test_rule_3_continuation_lines_carry_a_single_leading_space() -> None:
    """Rule 3: a continuation costs one of the 75 octets, leaving 74."""
    out = component(_event(Property("SUMMARY", [], "a" * 300)))
    lines = physical_lines(out)
    continuations = [line for line in lines if line.startswith(b" ")]
    assert continuations
    assert all(len(line) <= 75 for line in continuations)
    assert all(not line.startswith(b"  ") for line in continuations)


def test_rule_4_quotes_a_parameter_value_carrying_a_separator() -> None:
    """Rule 4: a parameter value with ``,`` ``;`` or ``:`` is DQUOTE-wrapped."""
    out = component(
        _event(Property("ATTENDEE", [Param("CN", "Bitar, Jad")], "mailto:a@b.c"))
    )
    assert b'ATTENDEE;CN="Bitar, Jad":' in out


def test_rule_5_resolves_a_tzid_datetime_to_utc_and_drops_the_parameter() -> None:
    """Rule 5: a resolvable TZID becomes UTC form #2 and the TZID goes."""
    cal = rfc5545.parse(
        (CONFORMANCE_DIR / "time" / "america_montreal.ics").read_bytes()
    )
    cal.components.append(
        _event(
            Property("DTSTAMP", [], "20260101T000000Z"),
            Property("DTSTART", [Param("TZID", "America/Montreal")], "20260104T133045"),
        )
    )
    out = calendar(cal)
    assert b"DTSTART:20260104T183045Z\r\n" in out
    assert b"TZID=America/Montreal" not in out.split(b"BEGIN:VEVENT")[1]


def test_rule_5_keeps_value_and_tzid_verbatim_when_resolution_fails() -> None:
    """Rule 5: an unresolvable TZID passes the value AND the parameter through."""
    cal = _wrap(
        _event(
            Property("DTSTAMP", [], "20260101T000000Z"),
            Property("DTSTART", [Param("TZID", "Mars/Olympus")], "20260104T133045"),
        )
    )
    out = calendar(cal)
    assert b"DTSTART;TZID=Mars/Olympus:20260104T133045\r\n" in out


def test_rule_5_leaves_a_utc_value_alone_even_with_a_tzid() -> None:
    """Rule 5: form #2 plus TZID is contradictory wire output, kept verbatim."""
    cal = rfc5545.parse(
        (CONFORMANCE_DIR / "time" / "america_montreal.ics").read_bytes()
    )
    cal.components.append(
        _event(
            Property("DTSTAMP", [], "20260101T000000Z"),
            Property(
                "DTSTART", [Param("TZID", "America/Montreal")], "20260104T183045Z"
            ),
        )
    )
    out = calendar(cal)
    assert b"DTSTART;TZID=America/Montreal:20260104T183045Z\r\n" in out


def test_rule_5_does_not_resolve_a_standard_child_dtstart() -> None:
    """Rule 5: a VTIMEZONE child's wall-clock DTSTART defines the rule itself."""
    data = (CONFORMANCE_DIR / "time" / "america_montreal.ics").read_bytes()
    out = calendar(rfc5545.parse(data))
    assert b"DTSTART:20070311T020000\r\n" in out
    assert b"DTSTART:20071104T020000\r\n" in out


def test_rule_6_sorts_top_level_components_by_uid() -> None:
    """Rule 6: top-level components sort by UID, byte-wise on UTF-8."""
    cal = _wrap(
        _event(Property("DTSTAMP", [], "20260101T000000Z"), uid="zeta"),
        _event(Property("DTSTAMP", [], "20260101T000000Z"), uid="alpha"),
        _event(Property("DTSTAMP", [], "20260101T000000Z"), uid="mid"),
    )
    out = calendar(cal)
    assert out.index(b"UID:alpha") < out.index(b"UID:mid") < out.index(b"UID:zeta")


def test_rule_6_sorts_a_vtimezone_by_its_tzid() -> None:
    """Rule 6: a top-level VTIMEZONE has no UID; its TZID is the sort key."""
    tz = Component(type=CompType.TIMEZONE, props=[Property("TZID", [], "AAA/Zone")])
    cal = _wrap(_event(Property("DTSTAMP", [], "20260101T000000Z"), uid="zzz"), tz)
    out = calendar(cal)
    assert out.index(b"TZID:AAA/Zone") < out.index(b"UID:zzz")


def test_rule_6_sorts_a_keyless_component_last() -> None:
    """Rule 6: a component with neither UID nor TZID sorts to the END."""
    keyless = Component(type=CompType.EVENT, props=[Property("SUMMARY", [], "orphan")])
    cal = _wrap(keyless, _event(Property("DTSTAMP", [], "20260101T000000Z"), uid="a"))
    out = calendar(cal)
    assert out.index(b"UID:a") < out.index(b"SUMMARY:orphan")


def test_rule_6_component_sort_is_stable_on_equal_uids() -> None:
    """Rule 6: equal UIDs — a producer bug — keep their input order."""
    cal = _wrap(
        _event(Property("SUMMARY", [], "first"), uid="same"),
        _event(Property("SUMMARY", [], "second"), uid="same"),
    )
    out = calendar(cal)
    assert out.index(b"SUMMARY:first") < out.index(b"SUMMARY:second")


def test_rule_6_sorts_astral_uids_after_bmp_ones() -> None:
    """Rule 6: UTF-8 byte order, which puts U+1D400 after U+FF21.

    Python's ``str`` comparison is by code point, and code-point order
    agrees with UTF-8 byte order — unlike UTF-16 code-unit order, which
    puts a surrogate pair below every BMP character from U+E000 up. This
    pins the property rather than assuming it.
    """
    # Built with chr() rather than spelled out: a mathematical capital A
    # and a fullwidth capital A are visually confusable with plain ASCII,
    # and the code points are the whole subject of the test.
    astral = "uid-" + chr(0x1D400)  # MATHEMATICAL BOLD CAPITAL A
    fullwidth = "uid-" + chr(0xFF21)  # FULLWIDTH LATIN CAPITAL LETTER A
    latin1 = "uid-" + chr(0x00FF)  # LATIN SMALL LETTER Y WITH DIAERESIS
    cal = _wrap(
        _event(Property("DTSTAMP", [], "20260101T000000Z"), uid=astral),
        _event(Property("DTSTAMP", [], "20260101T000000Z"), uid=fullwidth),
        _event(Property("DTSTAMP", [], "20260101T000000Z"), uid=latin1),
    )
    out = calendar(cal)
    assert (
        out.index(f"UID:{latin1}".encode())
        < out.index(f"UID:{fullwidth}".encode())
        < out.index(f"UID:{astral}".encode())
    )


def test_rule_6_does_not_sort_sub_components() -> None:
    """Rule 6: nested sub-components have no sort key and keep input order."""
    parent = Component(
        type=CompType.EVENT,
        props=[Property("UID", [], "u1")],
        sub=[
            Component(type=CompType("DAYLIGHT"), props=[Property("TZNAME", [], "EDT")]),
            Component(type=CompType("STANDARD"), props=[Property("TZNAME", [], "EST")]),
        ],
    )
    out = component(parent)
    assert out.index(b"BEGIN:DAYLIGHT") < out.index(b"BEGIN:STANDARD")


def test_rule_7_strips_x_vstar_hash_from_the_canonical_bytes() -> None:
    """Rule 7: the hash property is excluded from its own input."""
    c = _event(
        Property("DTSTAMP", [], "20260101T000000Z"),
        Property("X-VSTAR-HASH", [], "sha256:deadbeef"),
    )
    assert b"X-VSTAR-HASH" not in component(c)


def test_rule_7_strips_x_vstar_hash_case_insensitively() -> None:
    """Rule 7: property names are case-insensitive per RFC 5545 §3.1."""
    c = _event(Property("x-vstar-hash", [], "sha256:deadbeef"))
    assert b"vstar-hash" not in component(c).lower()


def test_rule_7_strips_x_vstar_hash_from_a_sub_component() -> None:
    """Rule 7: the exclusion is recursive, not top-level only."""
    parent = Component(
        type=CompType.EVENT,
        props=[Property("UID", [], "u1")],
        sub=[
            Component(
                type=CompType.ALARM,
                props=[Property("X-VSTAR-HASH", [], "sha256:deadbeef")],
            )
        ],
    )
    assert b"X-VSTAR-HASH" not in component(parent)


def test_rule_8_preserves_an_rrule_value_verbatim() -> None:
    """Rule 8: RRULE values are not normalized — no reordering, no eliding."""
    value = "FREQ=DAILY;INTERVAL=1;WKST=MO"
    out = component(_event(Property("RRULE", [], value)))
    assert f"RRULE:{value}\r\n".encode() in out


def test_rule_9_normalizes_a_property_value_to_nfc() -> None:
    """Rule 9: a decomposed value composes. ``e`` + U+0301 becomes ``é``."""
    out = component(_event(Property("SUMMARY", [], "Café")))
    assert "SUMMARY:Café\r\n".encode() in out
    assert "́".encode() not in out


def test_rule_9_normalizes_a_parameter_value_to_nfc() -> None:
    """Rule 9: parameter values normalize too, not just property values."""
    out = component(_event(Property("LOCATION", [Param("X-CITY", "Zürich")], "x")))
    assert "X-CITY=Zürich".encode() in out


def test_rule_9_normalizes_the_calendar_prodid() -> None:
    """Rule 9: PRODID is a property value like any other."""
    out = calendar(Calendar(prod_id="-//Café//EN", components=[]))
    assert "PRODID:-//Café//EN\r\n".encode() in out


def test_rule_9_does_not_normalize_a_property_name() -> None:
    """Rule 9: names are ASCII and uppercased, never normalized."""
    out = component(_event(Property("x-custom", [], "v")))
    assert b"X-CUSTOM:v\r\n" in out


def test_rule_9_runs_before_folding_so_the_octet_count_is_the_composed_one() -> None:
    """Rule 9 before rule 3: NFC changes UTF-8 length, so it must come first.

    ``e`` + U+0301 is three octets; ``é`` is two. Folding a
    pre-normalization string puts the break at the wrong octet, and the
    damage surfaces as a canonical-byte mismatch nowhere near the bug.
    """
    decomposed = "a" * 40 + "é" * 20
    composed = "a" * 40 + "é" * 20
    assert component(_event(Property("SUMMARY", [], decomposed))) == component(
        _event(Property("SUMMARY", [], composed))
    )


def test_rule_9_is_idempotent() -> None:
    """Rule 9: NFC of NFC is NFC, which is what makes the form a fixpoint."""
    once = component(_event(Property("SUMMARY", [], "Café")))
    twice = component(_event(Property("SUMMARY", [], "Café")))
    assert once == twice


def test_rule_10_strips_value_binary_and_encoding_base64_from_attach() -> None:
    """Rule 10: ATTACH is reference-only on emit; the value is untouched."""
    out = component(
        _event(
            Property(
                "ATTACH",
                [Param("VALUE", "BINARY"), Param("ENCODING", "BASE64")],
                "aGVsbG8=",
            )
        )
    )
    assert b"ATTACH:aGVsbG8=\r\n" in out


def test_rule_10_keeps_other_attach_parameters() -> None:
    """Rule 10 strips two named parameters, not every parameter."""
    out = component(
        _event(
            Property(
                "ATTACH",
                [Param("VALUE", "BINARY"), Param("FMTTYPE", "text/plain")],
                "https://example.com/a.txt",
            )
        )
    )
    assert b"ATTACH;FMTTYPE=text/plain:https://example.com/a.txt\r\n" in out


def test_rule_10_does_not_strip_value_binary_from_a_non_attach_property() -> None:
    """Rule 10 is scoped to ATTACH; another property keeps its parameters."""
    out = component(_event(Property("X-BLOB", [Param("VALUE", "BINARY")], "aGk=")))
    assert b"X-BLOB;VALUE=BINARY:aGk=\r\n" in out


def test_rule_11_emits_a_date_value_verbatim_and_keeps_the_parameter() -> None:
    """Rule 11: ``VALUE=DATE`` is load-bearing and stays; the value is verbatim."""
    out = component(_event(Property("DTSTART", [Param("VALUE", "DATE")], "20260515")))
    assert b"DTSTART;VALUE=DATE:20260515\r\n" in out


def test_rule_11_upper_cases_the_value_argument_on_a_date() -> None:
    """Rule 11: ``VALUE=date`` and ``VALUE=DATE`` converge."""
    out = component(_event(Property("DUE", [Param("VALUE", "date")], "20260515")))
    assert b"DUE;VALUE=DATE:20260515\r\n" in out


def test_rule_11_strips_a_tzid_from_a_date_value() -> None:
    """Rule 11: RFC 5545 §3.2.19 scopes TZID to DATE-TIME and TIME values."""
    out = component(
        _event(
            Property(
                "DTSTART",
                [Param("VALUE", "DATE"), Param("TZID", "America/Montreal")],
                "20260515",
            )
        )
    )
    assert b"DTSTART;VALUE=DATE:20260515\r\n" in out
    assert b"TZID" not in out


def test_rule_11_never_promotes_a_date_to_a_date_time() -> None:
    """Rule 11: the resolution registry is not consulted for a DATE.

    A promotion would emit ``20260515T000000Z`` and silently turn an
    all-day value into a midnight instant.
    """
    cal = rfc5545.parse(
        (CONFORMANCE_DIR / "time" / "america_montreal.ics").read_bytes()
    )
    cal.components.append(
        _event(
            Property("DTSTAMP", [], "20260101T000000Z"),
            Property(
                "DTSTART",
                [Param("VALUE", "DATE"), Param("TZID", "America/Montreal")],
                "20260515",
            ),
        )
    )
    out = calendar(cal)
    assert b"DTSTART;VALUE=DATE:20260515\r\n" in out
    assert b"20260515T" not in out


def test_rule_12_preserves_a_duration_value_verbatim() -> None:
    """Rule 12: units are not normalized — ``P1D`` is not ``PT24H``."""
    out = component(_event(Property("DURATION", [], "P1D")))
    assert b"DURATION:P1D\r\n" in out


def test_rule_12_preserves_a_relative_trigger_verbatim() -> None:
    """Rule 12: the relative TRIGGER form is a DURATION value."""
    alarm = Component(
        type=CompType.ALARM,
        props=[Property("TRIGGER", [], "-PT15M"), Property("ACTION", [], "DISPLAY")],
    )
    out = component(Component(type=CompType.EVENT, props=[], sub=[alarm]))
    assert b"TRIGGER:-PT15M\r\n" in out


def test_rule_12_distinguishes_p0d_from_pt0s() -> None:
    """Rule 12: both are numerically zero; the authored spelling survives."""
    assert b"DURATION:P0D\r\n" in component(_event(Property("DURATION", [], "P0D")))
    assert b"DURATION:PT0S\r\n" in component(_event(Property("DURATION", [], "PT0S")))


# --- Entry-point shape ------------------------------------------------


def test_component_and_component_in_context_are_not_an_overload() -> None:
    """The context-taking form resolves a TZID; the plain form cannot.

    A component without a parent calendar genuinely has no VTIMEZONE
    registry to consult, so the asymmetry is real behaviour, not a
    convenience wrapper.
    """
    cal = rfc5545.parse(
        (CONFORMANCE_DIR / "time" / "america_montreal.ics").read_bytes()
    )
    c = _event(
        Property("DTSTAMP", [], "20260101T000000Z"),
        Property("DTSTART", [Param("TZID", "America/Montreal")], "20260104T133045"),
    )
    assert b"DTSTART;TZID=America/Montreal:20260104T133045\r\n" in component(c)
    assert b"DTSTART:20260104T183045Z\r\n" in component_in_context(c, cal)


def test_canonical_does_not_mutate_its_input() -> None:
    """Every entry point is pure; a caller never observes the transforms."""
    c = _event(
        Property("SUMMARY", [], "Café"),
        Property("X-VSTAR-HASH", [], "sha256:deadbeef"),
    )
    before = [(p.name, [(x.name, x.value) for x in p.params], p.value) for p in c.props]
    component(c)
    after = [(p.name, [(x.name, x.value) for x in p.params], p.value) for p in c.props]
    assert before == after


def test_calendar_does_not_mutate_its_component_order() -> None:
    """The rule-6 sort operates on a copy."""
    cal = _wrap(
        _event(Property("DTSTAMP", [], "20260101T000000Z"), uid="zeta"),
        _event(Property("DTSTAMP", [], "20260101T000000Z"), uid="alpha"),
    )
    calendar(cal)
    assert [c.uid() for c in cal.components] == ["zeta", "alpha"]


def test_card_promotes_version_ahead_of_alphabetical_order() -> None:
    """RFC 6350 §3.3 requires VERSION immediately after ``BEGIN:VCARD``."""
    out = card(Card(uid="u1", props=[Property("FN", [], "Jad")]))
    lines = physical_lines(out)
    assert lines[0] == b"BEGIN:VCARD"
    assert lines[1] == b"VERSION:4.0"


def test_card_absorbs_a_uid_already_present_in_props() -> None:
    """A UID in ``props`` is not duplicated by the synthesized one."""
    out = card(Card(uid="u1", props=[Property("UID", [], "u1")]))
    assert out.count(b"UID:u1") == 1


def test_card_omits_kind_when_absent() -> None:
    """The empty Kind means "no KIND property"; the encoder writes no line."""
    assert b"KIND" not in card(Card(uid="u1", props=[Property("FN", [], "Jad")]))


def test_canonical_returns_bytes_not_str() -> None:
    """The canonical form is a byte sequence; the distinction is load-bearing."""
    assert isinstance(component(_event()), bytes)
    assert isinstance(calendar(_wrap()), bytes)
    assert isinstance(card(Card(uid="u1")), bytes)


# --- Determinism and order-irrelevance --------------------------------


def test_canonical_bytes_are_deterministic_over_100_runs() -> None:
    """The same input canonicalizes to the same bytes, every time.

    A set or dict iteration order leaking into the output would be
    stable within a process and unstable across them; hashing over the
    result makes any per-run variation a failure here.
    """
    data = (CONFORMANCE_DIR / "rfc5545" / "world.ics").read_bytes()
    first = calendar(rfc5545.parse(data))
    digests = {
        hashlib.sha256(calendar(rfc5545.parse(data))).hexdigest() for _ in range(100)
    }
    assert digests == {hashlib.sha256(first).hexdigest()}


def test_input_property_order_does_not_change_canonical_bytes() -> None:
    """Rule 2 makes property input order irrelevant to the output."""
    props = [
        Property("UID", [], "u1"),
        Property("DTSTAMP", [], "20260101T000000Z"),
        Property("SUMMARY", [], "hello"),
    ]
    forward = component(Component(type=CompType.EVENT, props=list(props)))
    reverse = component(Component(type=CompType.EVENT, props=list(reversed(props))))
    assert forward == reverse


def test_input_component_order_does_not_change_canonical_bytes() -> None:
    """Rule 6 makes top-level component input order irrelevant."""
    a = _event(Property("DTSTAMP", [], "20260101T000000Z"), uid="alpha")
    b = _event(Property("DTSTAMP", [], "20260101T000000Z"), uid="beta")
    assert calendar(_wrap(a, b)) == calendar(_wrap(b, a))


def test_input_parameter_order_does_not_change_canonical_bytes() -> None:
    """Rule 2 makes parameter input order irrelevant."""
    params = [Param("CN", "Jad"), Param("ROLE", "CHAIR")]
    forward = component(_event(Property("ATTENDEE", list(params), "mailto:a@b.c")))
    reverse = component(
        _event(Property("ATTENDEE", list(reversed(params)), "mailto:a@b.c"))
    )
    assert forward == reverse
