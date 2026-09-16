# SPDX-License-Identifier: MIT

"""The iCalendar codec, over the whole ``rfc5545/`` conformance family."""

from __future__ import annotations

import pytest

from _fixtures import Fixture, assert_bytes_equal, load_fixtures, physical_lines
from vstar import Calendar, Component, CompType, Param, Property, property_equal
from vstar.codec import rfc5545

FIXTURES = load_fixtures("rfc5545", ".ics")
IDS = [f.stem for f in FIXTURES]


def test_the_corpus_is_found() -> None:
    assert FIXTURES, "no rfc5545 fixtures loaded"


@pytest.mark.parametrize("fixture", FIXTURES, ids=IDS)
def test_round_trips_semantically(fixture: Fixture) -> None:
    first = rfc5545.parse(fixture.input)
    second = rfc5545.parse(rfc5545.encode(first))
    assert_calendars_equal(second, first)


@pytest.mark.parametrize("fixture", FIXTURES, ids=IDS)
def test_re_encode_is_byte_stable(fixture: Fixture) -> None:
    once = rfc5545.encode(rfc5545.parse(fixture.input))
    twice = rfc5545.encode(rfc5545.parse(once))
    assert_bytes_equal(twice, once, fixture.stem)


@pytest.mark.parametrize("fixture", FIXTURES, ids=IDS)
def test_every_terminator_is_crlf(fixture: Fixture) -> None:
    out = rfc5545.encode(rfc5545.parse(fixture.input))
    for i, byte in enumerate(out):
        if byte == 0x0A:
            assert out[i - 1] == 0x0D, f"bare LF at offset {i} in {fixture.stem}"
    assert out.endswith(b"\r\n")


@pytest.mark.parametrize("fixture", FIXTURES, ids=IDS)
def test_folds_at_75_octets(fixture: Fixture) -> None:
    for line in physical_lines(rfc5545.encode(rfc5545.parse(fixture.input))):
        assert len(line) <= 75, f"over-long physical line in {fixture.stem}: {line!r}"


@pytest.mark.parametrize("fixture", FIXTURES, ids=IDS)
def test_preserves_property_and_component_order(fixture: Fixture) -> None:
    cal = rfc5545.parse(fixture.input)
    assert component_order(cal) == wire_component_order(logical_lines(fixture.input))


@pytest.mark.parametrize("fixture", FIXTURES, ids=IDS)
def test_parse_accepts_bytes_str_and_a_stream(fixture: Fixture) -> None:
    import io

    from_bytes = rfc5545.encode(rfc5545.parse(fixture.input))
    from_str = rfc5545.encode(rfc5545.parse(fixture.input.decode("utf-8")))
    from_stream = rfc5545.encode(rfc5545.parse(io.BytesIO(fixture.input)))
    assert from_str == from_bytes
    assert from_stream == from_bytes


class TestParseContentLine:
    def test_parses_a_bare_name_and_value(self) -> None:
        p = rfc5545.parse_content_line("SUMMARY:hello")
        assert (p.name, p.value, p.params) == ("SUMMARY", "hello", [])

    def test_parses_parameters_in_wire_order(self) -> None:
        p = rfc5545.parse_content_line(
            "ATTENDEE;ROLE=CHAIR;CN=Jad:mailto:jad@example.com"
        )
        assert [x.name for x in p.params] == ["ROLE", "CN"]
        assert p.value == "mailto:jad@example.com"

    def test_keeps_a_quoted_parameter_colon_out_of_the_value_split(self) -> None:
        p = rfc5545.parse_content_line('X-THING;ALT="a:b;c":payload')
        assert p.params == [Param("ALT", "a:b;c")]
        assert p.value == "payload"

    def test_preserves_the_wire_case_of_names(self) -> None:
        p = rfc5545.parse_content_line("x-thing;alt=1:v")
        assert p.name == "x-thing"
        assert p.params[0].name == "alt"


class TestEncodeComponent:
    def test_emits_begin_end_with_no_calendar_wrapper(self) -> None:
        comp = Component(type=CompType.TODO, props=[Property("UID", [], "x")], sub=[])
        assert (
            rfc5545.encode_component(comp) == b"BEGIN:VTODO\r\nUID:x\r\nEND:VTODO\r\n"
        )

    def test_recurses_into_sub_components(self) -> None:
        inner = Component(type=CompType.ALARM, props=[], sub=[])
        outer = Component(type=CompType.EVENT, props=[], sub=[inner])
        assert rfc5545.encode_component(outer) == (
            b"BEGIN:VEVENT\r\nBEGIN:VALARM\r\nEND:VALARM\r\nEND:VEVENT\r\n"
        )


class TestEncodeFoldsInOctets:
    def test_a_multi_byte_value_folds_on_byte_count(self) -> None:
        # 60 'e-acute': 60 code points, 120 UTF-8 bytes. With "SUMMARY:"
        # the logical line is 128 octets and MUST fold.
        cal = Calendar(
            prod_id="-//test//EN",
            components=[
                Component(
                    type=CompType.TODO,
                    props=[Property("SUMMARY", [], "é" * 60)],
                    sub=[],
                )
            ],
        )
        out = rfc5545.encode(cal)
        assert b"\r\n " in out
        for line in physical_lines(out):
            assert len(line) <= 75

    def test_folding_happens_after_parameters_are_appended(self) -> None:
        # The value alone is under the limit; name + parameters push the
        # assembled line over it. Folding a value before assembly would
        # emit no fold at all here.
        cal = Calendar(
            prod_id="-//t//EN",
            components=[
                Component(
                    type=CompType.EVENT,
                    props=[
                        Property(
                            "ATTENDEE",
                            [Param("CN", "A" * 60)],
                            "mailto:someone@example.com",
                        )
                    ],
                    sub=[],
                )
            ],
        )
        out = rfc5545.encode(cal)
        assert b"\r\n " in out
        for line in physical_lines(out):
            assert len(line) <= 75


class TestCodecSurface:
    def test_new_codec_and_default_both_round_trip(self) -> None:
        doc = b"BEGIN:VCALENDAR\r\nVERSION:2.0\r\nPRODID:-//t//EN\r\nEND:VCALENDAR\r\n"
        assert rfc5545.new_codec().encode(rfc5545.new_codec().parse(doc)) == doc
        assert rfc5545.DEFAULT.encode(rfc5545.DEFAULT.parse(doc)) == doc

    def test_prod_id_survives_the_round_trip(self) -> None:
        doc = (
            b"BEGIN:VCALENDAR\r\nVERSION:2.0\r\n"
            b"PRODID:-//Jad//V*//EN\r\nEND:VCALENDAR\r\n"
        )
        assert rfc5545.parse(doc).prod_id == "-//Jad//V*//EN"


def assert_calendars_equal(got: Calendar, want: Calendar) -> None:
    assert got.prod_id == want.prod_id
    assert_components_equal(got.components, want.components)


def assert_components_equal(got: list[Component], want: list[Component]) -> None:
    assert len(got) == len(want)
    for a, b in zip(got, want, strict=True):
        assert a.type == b.type
        assert len(a.props) == len(b.props)
        for x, y in zip(a.props, b.props, strict=True):
            assert property_equal(x, y), f"{x!r} != {y!r}"
        assert_components_equal(a.sub, b.sub)


def component_order(cal: Calendar) -> list[str]:
    """Flattened ``TYPE:prop,prop,...`` list, depth-first, in tree order."""
    out: list[str] = []

    def walk(comps: list[Component]) -> None:
        for c in comps:
            out.append(f"{c.type.value}:{','.join(p.name.upper() for p in c.props)}")
            walk(c.sub)

    walk(cal.components)
    return out


def logical_lines(data: bytes) -> list[str]:
    """Unfolded logical lines of an LF- or CRLF-terminated input."""
    out: list[str] = []
    for raw in data.decode("utf-8").replace("\r\n", "\n").split("\n"):
        if raw == "":
            continue
        if raw[0] in " \t" and out:
            out[-1] += raw[1:]
            continue
        out.append(raw)
    return out


def wire_component_order(lines: list[str]) -> list[str]:
    """The same list, read straight off the wire.

    Slots are reserved at BEGIN and filled at END so the result is
    pre-order, matching :func:`component_order`'s depth-first walk.
    """
    out: list[str] = []
    stack: list[tuple[int, str, list[str]]] = []
    for line in lines:
        colon = line.index(":")
        name = line[:colon].split(";")[0].upper()
        value = line[colon + 1 :]
        if name == "BEGIN":
            if value.upper() == "VCALENDAR":
                continue
            out.append("")
            stack.append((len(out) - 1, value.upper(), []))
            continue
        if name == "END":
            if not stack:
                continue
            index, ctype, props = stack.pop()
            out[index] = f"{ctype}:{','.join(props)}"
            continue
        if stack:
            stack[-1][2].append(name)
    return out
