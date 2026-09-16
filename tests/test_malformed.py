# SPDX-License-Identifier: MIT

"""Every ``malformed/`` fixture MUST fail, with the sentinel it names.

Failing is not enough — failing *correctly* is the gate. The ``.error``
sibling holds one line: the Go sentinel identifier, which every port
carries verbatim on ``VstarError.sentinel``.
"""

from __future__ import annotations

import pytest

from _fixtures import Fixture, load_fixtures
from vstar import VstarError
from vstar.codec import rfc5545, rfc6350

ICS = load_fixtures("malformed", ".ics")
VCF = load_fixtures("malformed", ".vcf")


def test_the_corpus_is_found() -> None:
    assert ICS, "no malformed .ics fixtures loaded"
    assert VCF, "no malformed .vcf fixtures loaded"


@pytest.mark.parametrize("fixture", ICS, ids=[f.stem for f in ICS])
def test_ics_fails_with_its_named_sentinel(fixture: Fixture) -> None:
    assert fixture.sentinel is not None, f"{fixture.stem} has no .error sibling"
    with pytest.raises(VstarError) as excinfo:
        rfc5545.parse(fixture.input)
    assert excinfo.value.sentinel == fixture.sentinel


@pytest.mark.parametrize("fixture", VCF, ids=[f.stem for f in VCF])
def test_vcf_fails_with_its_named_sentinel_on_parse_or_encode(
    fixture: Fixture,
) -> None:
    """Parse first; if it succeeds, the fixture targets an encoder sentinel.

    ``ErrMissingUID`` is encoder-only in v0.1 — the parser accepts a
    UID-less VCARD. A port that only checks the parse side passes the
    fixture silently and is wrong, so the encoder is exercised too.
    """
    assert fixture.sentinel is not None, f"{fixture.stem} has no .error sibling"

    try:
        cards = rfc6350.parse(fixture.input)
    except VstarError as parse_error:
        assert parse_error.sentinel == fixture.sentinel
        return

    assert cards, f"{fixture.stem}: parse succeeded with no cards to re-encode"
    with pytest.raises(VstarError) as excinfo:
        for card in cards:
            rfc6350.encode(card)
    assert excinfo.value.sentinel == fixture.sentinel


def test_the_corpus_covers_the_four_codec_layer_sentinels() -> None:
    seen = {f.sentinel for f in (*ICS, *VCF)}
    assert {
        "ErrMalformed",
        "ErrUnclosedBlock",
        "ErrUnsupportedVersion",
        "ErrMissingUID",
    } <= seen
