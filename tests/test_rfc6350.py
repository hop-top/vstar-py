# SPDX-License-Identifier: MIT

"""The vCard codec, over the whole ``rfc6350/`` conformance family."""

from __future__ import annotations

import pytest

from _fixtures import Fixture, assert_bytes_equal, load_fixtures, physical_lines
from vstar import Card, Kind, MissingUid, property_equal
from vstar.codec import rfc6350

FIXTURES = load_fixtures("rfc6350", ".vcf")
IDS = [f.stem for f in FIXTURES]

UIDLESS = b"BEGIN:VCARD\r\nVERSION:4.0\r\nFN:No UID Here\r\nEND:VCARD\r\n"
TWO_CARDS = (
    b"BEGIN:VCARD\r\nVERSION:4.0\r\nUID:a\r\nFN:A\r\nEND:VCARD\r\n"
    b"BEGIN:VCARD\r\nVERSION:4.0\r\nUID:b\r\nFN:B\r\nEND:VCARD\r\n"
)


def encode_all(cards: list[Card]) -> bytes:
    return b"".join(rfc6350.encode(c) for c in cards)


def test_the_corpus_is_found() -> None:
    assert FIXTURES, "no rfc6350 fixtures loaded"


@pytest.mark.parametrize("fixture", FIXTURES, ids=IDS)
def test_parse_returns_a_list_of_cards(fixture: Fixture) -> None:
    cards = rfc6350.parse(fixture.input)
    assert isinstance(cards, list)
    assert cards
    assert all(isinstance(c, Card) for c in cards)


@pytest.mark.parametrize("fixture", FIXTURES, ids=IDS)
def test_round_trips_semantically(fixture: Fixture) -> None:
    first = rfc6350.parse(fixture.input)
    second = rfc6350.parse(encode_all(first))
    assert len(second) == len(first)
    for got, want in zip(second, first, strict=True):
        assert_cards_equal(got, want)


@pytest.mark.parametrize("fixture", FIXTURES, ids=IDS)
def test_re_encode_is_byte_stable(fixture: Fixture) -> None:
    once = encode_all(rfc6350.parse(fixture.input))
    twice = encode_all(rfc6350.parse(once))
    assert_bytes_equal(twice, once, fixture.stem)


@pytest.mark.parametrize("fixture", FIXTURES, ids=IDS)
def test_every_terminator_is_crlf(fixture: Fixture) -> None:
    out = encode_all(rfc6350.parse(fixture.input))
    for i, byte in enumerate(out):
        if byte == 0x0A:
            assert out[i - 1] == 0x0D, f"bare LF at offset {i} in {fixture.stem}"


@pytest.mark.parametrize("fixture", FIXTURES, ids=IDS)
def test_folds_at_75_octets(fixture: Fixture) -> None:
    for line in physical_lines(encode_all(rfc6350.parse(fixture.input))):
        assert len(line) <= 75, f"over-long physical line in {fixture.stem}: {line!r}"


@pytest.mark.parametrize("fixture", FIXTURES, ids=IDS)
def test_preserves_property_and_parameter_order(fixture: Fixture) -> None:
    for card in rfc6350.parse(fixture.input):
        wire_names = [
            p.name.upper() for p in rfc6350.parse(rfc6350.encode(card))[0].props
        ]
        assert wire_names == [p.name.upper() for p in card.props]


class TestMultiCardStreams:
    def test_each_block_becomes_its_own_card(self) -> None:
        cards = rfc6350.parse(TWO_CARDS)
        assert [c.uid for c in cards] == ["a", "b"]

    def test_encode_emits_exactly_one_card(self) -> None:
        out = rfc6350.encode(rfc6350.parse(TWO_CARDS)[0])
        assert out.count(b"BEGIN:VCARD") == 1
        assert out.count(b"END:VCARD") == 1

    def test_empty_input_is_no_cards_not_an_error(self) -> None:
        assert rfc6350.parse(b"") == []


class TestUidIsEncoderOnly:
    """``ErrMissingUID`` is an ENCODER-time sentinel.

    The parser accepts a UID-less VCARD so adopters can recover a
    non-conforming document rather than lose it; the encoder refuses to
    emit one. A port that implements only the parse side passes the
    ``malformed/missing_uid.vcf`` fixture while being wrong, so both
    halves are asserted here.
    """

    def test_the_parser_accepts_a_uid_less_vcard(self) -> None:
        cards = rfc6350.parse(UIDLESS)
        assert len(cards) == 1
        assert cards[0].uid == ""

    def test_the_encoder_refuses_a_uid_less_card(self) -> None:
        card = rfc6350.parse(UIDLESS)[0]
        with pytest.raises(MissingUid) as excinfo:
            rfc6350.encode(card)
        assert excinfo.value.sentinel == "ErrMissingUID"

    def test_a_card_with_a_uid_encodes_fine(self) -> None:
        card = rfc6350.parse(UIDLESS)[0]
        card.uid = "now-present"
        assert b"UID:now-present\r\n" in rfc6350.encode(card)


class TestGroupPrefixes:
    def test_the_group_prefix_and_its_case_survive(self) -> None:
        doc = b"BEGIN:VCARD\r\nVERSION:4.0\r\nUID:g\r\nhome.TEL:+1\r\nEND:VCARD\r\n"
        assert rfc6350.parse(doc)[0].props[0].name == "home.TEL"

    def test_the_bare_name_is_uppercased_on_encode(self) -> None:
        doc = b"BEGIN:VCARD\r\nVERSION:4.0\r\nUID:g\r\nhome.tel:+1\r\nEND:VCARD\r\n"
        assert b"home.TEL:+1\r\n" in rfc6350.encode(rfc6350.parse(doc)[0])


class TestKind:
    def test_kind_is_lifted_off_the_property_list(self) -> None:
        doc = (
            b"BEGIN:VCARD\r\nVERSION:4.0\r\nUID:k\r\nKIND:ORG\r\nFN:X\r\nEND:VCARD\r\n"
        )
        card = rfc6350.parse(doc)[0]
        assert card.kind == Kind.ORG
        assert [p.name for p in card.props] == ["FN"]

    def test_absent_kind_is_the_empty_string(self) -> None:
        doc = b"BEGIN:VCARD\r\nVERSION:4.0\r\nUID:k\r\nFN:X\r\nEND:VCARD\r\n"
        card = rfc6350.parse(doc)[0]
        assert card.kind == ""
        assert b"KIND:" not in rfc6350.encode(card)


class TestCodecSurface:
    def test_new_codec_new_parser_new_encoder_and_default(self) -> None:
        cards = rfc6350.new_parser().parse(TWO_CARDS)
        assert len(cards) == 2
        assert rfc6350.new_encoder().encode(cards[0]).startswith(b"BEGIN:VCARD")
        assert len(rfc6350.new_codec().parse(TWO_CARDS)) == 2
        assert len(rfc6350.DEFAULT.parse(TWO_CARDS)) == 2


def assert_cards_equal(got: Card, want: Card) -> None:
    assert got.uid == want.uid
    assert got.kind == want.kind
    assert len(got.props) == len(want.props)
    for x, y in zip(got.props, want.props, strict=True):
        assert property_equal(x, y), f"{x!r} != {y!r}"
