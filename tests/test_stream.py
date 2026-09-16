# SPDX-License-Identifier: MIT

"""The streaming codecs, gated by re-parse equality against the batch codecs."""

from __future__ import annotations

import io
from typing import IO, cast

import pytest

from _fixtures import CONFORMANCE_DIR, assert_bytes_equal, load_fixtures
from vstar import (
    COMP_TODO,
    AlreadyClosed,
    Calendar,
    Card,
    Component,
    HeaderLocked,
    Malformed,
    MissingUid,
    Property,
    UnclosedBlock,
    UnsupportedVersion,
)
from vstar.codec import rfc5545, rfc6350
from vstar.codec.stream import (
    VCalendarEncoder,
    VCalendarParser,
    VCardEncoder,
    VCardParser,
)

CALENDAR_FIXTURES = load_fixtures("rfc5545", ".ics")
CARD_FIXTURES = load_fixtures("rfc6350", ".vcf")


def test_fixtures_are_discovered() -> None:
    """A vacuous walk would make the whole re-parse gate disappear."""
    assert len(CALENDAR_FIXTURES) >= 15
    assert len(CARD_FIXTURES) >= 5


# --------------------------------------------------------------------
# The re-parse gate: streamed parse == batch parse, for every fixture
# --------------------------------------------------------------------


@pytest.mark.parametrize("fx", CALENDAR_FIXTURES, ids=lambda f: f.stem)
def test_calendar_stream_parse_equals_batch(fx: object) -> None:
    """Streaming a calendar yields exactly what parsing it whole does.

    Property values included — which is the point. Splitting a content
    line and unescaping its value are separate steps, and a stream
    parser doing only the first would hand back ``Last\\, Comma`` where
    the batch parser hands back ``Last, Comma``. The two would then
    disagree about the same bytes.
    """
    data = fx.input  # type: ignore[attr-defined]
    want = rfc5545.parse(data)

    parser = VCalendarParser(data)
    header = parser.header()
    got = Calendar(prod_id=header.prod_id, components=list(parser))

    assert got.prod_id == want.prod_id
    assert _calendar_shape(got) == _calendar_shape(want)


@pytest.mark.parametrize("fx", CARD_FIXTURES, ids=lambda f: f.stem)
def test_card_stream_parse_equals_batch(fx: object) -> None:
    """Streaming a vCard yields exactly what parsing it whole does.

    ``escaping.vcf`` is the case that matters: its ``N`` carries an
    escaped comma, so a stream parser routed through the wrong format's
    content-line reader would leave the backslash in place and this
    comparison would catch it.
    """
    data = fx.input  # type: ignore[attr-defined]
    want = rfc6350.parse(data)
    got = list(VCardParser(data))
    assert [_card_shape(c) for c in got] == [_card_shape(c) for c in want]


def test_escaped_text_is_unescaped_by_the_stream_parser() -> None:
    """The regression this gate exists for, stated on its own.

    Named explicitly rather than left to the corpus sweep because the
    sweep proves the two parsers agree, not that either is *right* — if
    both left the value escaped they would agree and the sweep would
    still pass.
    """
    data = (CONFORMANCE_DIR / "rfc6350" / "escaping.vcf").read_bytes()
    streamed = list(VCardParser(data))
    assert len(streamed) == 1
    values = [p.value for p in streamed[0].props]
    assert any("\\," not in v for v in values)
    assert all("\\," not in v for v in values), f"still escaped: {values}"


def test_a_fold_may_split_a_utf8_sequence() -> None:
    """Unfolding happens on bytes, before decoding (spec rule 3).

    ``fold_split_utf8`` folds mid-character on purpose. Decoding the
    physical lines first would turn each half into a replacement
    character and the text would be lost before the fold was ever
    rejoined.
    """
    data = (CONFORMANCE_DIR / "rfc5545" / "fold_split_utf8.ics").read_bytes()
    want = rfc5545.parse(data)
    got = list(VCalendarParser(data))
    assert _components_shape(got) == _components_shape(want.components)
    assert "�" not in "".join(p.value for c in got for p in c.props), (
        "a replacement character means the fold was decoded before rejoining"
    )


# --------------------------------------------------------------------
# Incrementality
# --------------------------------------------------------------------


def test_calendar_parser_is_genuinely_incremental() -> None:
    """The parser pulls lines as asked, not the whole input up front.

    Asserted by counting what a deliberately slow source yielded by the
    time the first component came back. A parser that read everything
    first would show the full count here and the streaming claim would
    be a lie the type name told.
    """
    data = (CONFORMANCE_DIR / "rfc5545" / "world.ics").read_bytes()
    source = _CountingBytes(data)

    parser = VCalendarParser(cast(IO[bytes], source))
    first = next(iter(parser))

    assert first is not None
    assert source.reads > 0, "nothing was read at all"
    assert source.consumed < len(data), (
        f"consumed all {len(data)} bytes to produce one component; "
        "the parser is buffering the whole input"
    )


def test_card_parser_is_genuinely_incremental() -> None:
    """The same claim for the vCard side."""
    blocks = b"".join(
        (CONFORMANCE_DIR / "rfc6350" / f"{name}.vcf").read_bytes()
        for name in ("minimal", "kind_org", "grouped")
    )
    source = _CountingBytes(blocks)

    parser = VCardParser(cast(IO[bytes], source))
    first = next(iter(parser))

    assert first.uid != ""
    assert source.consumed < len(blocks), (
        "consumed every card to produce the first; the parser is not streaming"
    )


# --------------------------------------------------------------------
# Round-trip through the encoders
# --------------------------------------------------------------------


@pytest.mark.parametrize("fx", CALENDAR_FIXTURES, ids=lambda f: f.stem)
def test_calendar_stream_encode_equals_batch(fx: object) -> None:
    """A streamed encode is byte-identical to a batch encode."""
    cal = rfc5545.parse(fx.input)  # type: ignore[attr-defined]

    sink = io.BytesIO()
    enc = VCalendarEncoder(sink)
    enc.set_header(cal)
    for c in cal.components:
        enc.encode(c)
    enc.close()

    assert_bytes_equal(sink.getvalue(), rfc5545.encode(cal), fx.stem)  # type: ignore[attr-defined]


def test_card_stream_encode_concatenates_blocks() -> None:
    """Each encode writes one complete, self-contained VCARD block."""
    cards = [
        rfc6350.parse((CONFORMANCE_DIR / "rfc6350" / f"{n}.vcf").read_bytes())[0]
        for n in ("minimal", "kind_org")
    ]
    sink = io.BytesIO()
    enc = VCardEncoder(sink)
    for c in cards:
        enc.encode(c)
    enc.close()

    assert_bytes_equal(
        sink.getvalue(), b"".join(rfc6350.encode(c) for c in cards), "concatenated"
    )


def test_streamed_calendar_round_trips_through_its_own_parser() -> None:
    """Encode then stream-parse recovers the components."""
    cal = rfc5545.parse((CONFORMANCE_DIR / "rfc5545" / "world.ics").read_bytes())
    sink = io.BytesIO()
    enc = VCalendarEncoder(sink)
    enc.set_header(cal)
    for c in cal.components:
        enc.encode(c)
    enc.close()

    back = list(VCalendarParser(sink.getvalue()))
    assert _components_shape(back) == _components_shape(cal.components)


# --------------------------------------------------------------------
# Encoder lifecycle
# --------------------------------------------------------------------


def test_vcard_encoder_has_no_set_header() -> None:
    """A vCard stream has no wrapper, so there is no header to set.

    An encoder that grew one for symmetry would have nothing for it to
    do, and its existence would invite a caller to emit a wrapper every
    parser rejects.
    """
    assert not hasattr(VCardEncoder(io.BytesIO()), "set_header")


def test_calendar_header_locks_at_first_encode() -> None:
    """Locking the header is what keeps the wire ordering deterministic."""
    enc = VCalendarEncoder(io.BytesIO())
    enc.set_header(Calendar(prod_id="-//A//B//EN"))
    enc.encode(Component(type=COMP_TODO, props=[Property("UID", [], "u")]))
    with pytest.raises(HeaderLocked):
        enc.set_header(Calendar(prod_id="-//C//D//EN"))


def test_calendar_encoder_refuses_use_after_close() -> None:
    """A silently ignored double close hides a lifecycle bug."""
    enc = VCalendarEncoder(io.BytesIO())
    enc.close()
    with pytest.raises(AlreadyClosed):
        enc.close()
    with pytest.raises(AlreadyClosed):
        enc.encode(Component(type=COMP_TODO))


def test_card_encoder_refuses_use_after_close() -> None:
    """The same lifecycle contract on the vCard side."""
    enc = VCardEncoder(io.BytesIO())
    enc.close()
    with pytest.raises(AlreadyClosed):
        enc.close()
    with pytest.raises(AlreadyClosed):
        enc.encode(Card(uid="u"))


def test_closing_without_encoding_emits_an_empty_calendar() -> None:
    """The header is still flushed, so the output is legal."""
    sink = io.BytesIO()
    enc = VCalendarEncoder(sink)
    enc.close()
    out = sink.getvalue()
    assert out.startswith(b"BEGIN:VCALENDAR\r\nVERSION:2.0\r\nPRODID:")
    assert out.endswith(b"END:VCALENDAR\r\n")
    assert rfc5545.parse(out).components == []


def test_card_encoder_refuses_a_uid_less_card() -> None:
    """The encoder is the one place a missing UID is a failure."""
    enc = VCardEncoder(io.BytesIO())
    with pytest.raises(MissingUid):
        enc.encode(Card(uid=""))


# --------------------------------------------------------------------
# Parser failures
# --------------------------------------------------------------------


def test_empty_calendar_input_is_malformed() -> None:
    """No document at all is not an empty document."""
    with pytest.raises(Malformed):
        VCalendarParser(b"").header()


def test_calendar_without_begin_is_malformed() -> None:
    with pytest.raises(Malformed):
        list(VCalendarParser(b"VERSION:2.0\r\n"))


def test_unsupported_calendar_version_is_rejected() -> None:
    with pytest.raises(UnsupportedVersion):
        VCalendarParser(b"BEGIN:VCALENDAR\r\nVERSION:1.0\r\nEND:VCALENDAR\r\n").header()


def test_unclosed_calendar_is_reported() -> None:
    with pytest.raises(UnclosedBlock):
        list(VCalendarParser(b"BEGIN:VCALENDAR\r\nVERSION:2.0\r\nBEGIN:VTODO\r\n"))


def test_calendar_property_after_components_is_malformed() -> None:
    """A producer emits a header then a component run, never interleaved."""
    data = (
        b"BEGIN:VCALENDAR\r\nVERSION:2.0\r\n"
        b"BEGIN:VTODO\r\nUID:a\r\nEND:VTODO\r\n"
        b"METHOD:PUBLISH\r\nEND:VCALENDAR\r\n"
    )
    with pytest.raises(Malformed):
        list(VCalendarParser(data))


def test_exhausted_calendar_parser_stays_exhausted() -> None:
    """Past the end is still the end, however many times it is asked."""
    parser = VCalendarParser(b"BEGIN:VCALENDAR\r\nVERSION:2.0\r\nEND:VCALENDAR\r\n")
    assert list(parser) == []
    with pytest.raises(StopIteration):
        next(parser)


def test_empty_card_input_yields_no_cards() -> None:
    """ "No cards" is not an error — there is no wrapper to be missing."""
    assert list(VCardParser(b"")) == []


def test_card_without_version_is_malformed() -> None:
    with pytest.raises(Malformed):
        list(VCardParser(b"BEGIN:VCARD\r\nUID:u\r\nEND:VCARD\r\n"))


def test_unsupported_card_version_is_rejected() -> None:
    with pytest.raises(UnsupportedVersion):
        list(VCardParser(b"BEGIN:VCARD\r\nVERSION:3.0\r\nEND:VCARD\r\n"))


def test_nested_card_is_malformed() -> None:
    with pytest.raises(Malformed):
        list(VCardParser(b"BEGIN:VCARD\r\nVERSION:4.0\r\nBEGIN:VCARD\r\n"))


def test_unclosed_card_is_reported() -> None:
    with pytest.raises(UnclosedBlock):
        list(VCardParser(b"BEGIN:VCARD\r\nVERSION:4.0\r\nUID:u\r\n"))


# --------------------------------------------------------------------
# Shape helpers — compare structure, never object identity
# --------------------------------------------------------------------


def _prop_shape(p: Property) -> tuple[str, tuple[tuple[str, str], ...], str]:
    return (p.name, tuple((x.name, x.value) for x in p.params), p.value)


def _components_shape(cs: list[Component]) -> list[object]:
    return [
        (
            str(c.type),
            [_prop_shape(p) for p in c.props],
            _components_shape(c.sub),
        )
        for c in cs
    ]


def _calendar_shape(cal: Calendar) -> object:
    return (cal.prod_id, _components_shape(cal.components))


def _card_shape(c: Card) -> object:
    return (c.uid, str(c.kind), [_prop_shape(p) for p in c.props])


class _CountingBytes:
    """A byte source that reports how much of itself has been handed out.

    Distinguishes a parser that pulls as it goes from one that swallows
    the input and then hands back pieces of it. Deliberately serves a
    short chunk per call, well under any sane read size, so "read a
    line's worth" and "read everything" stay far apart in the count.

    A bare ``read`` rather than an :class:`io.RawIOBase` subclass: the
    method is the whole interface a parser needs from a byte source, and
    inheriting the ABC would add a surface this test does not exercise.
    """

    #: Bytes served per call, however many were asked for.
    _SERVE = 64

    def __init__(self, data: bytes) -> None:
        self._data = data
        self._pos = 0
        self.reads = 0

    @property
    def consumed(self) -> int:
        """Bytes handed out so far."""
        return self._pos

    def read(self, n: int = -1) -> bytes:
        """At most ``_SERVE`` bytes, however many were requested."""
        want = self._SERVE if n < 0 else min(n, self._SERVE)
        chunk = self._data[self._pos : self._pos + want]
        self._pos += len(chunk)
        if chunk:
            self.reads += 1
        return chunk
