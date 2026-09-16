# SPDX-License-Identifier: MIT

"""Fixtures are LF on disk; the encoder emits CRLF.

Three separate facts, and all three matter: the corpus files use ``\\n``,
the wire form is ``\\r\\n``, and parsers are liberal about both. The one
licensed transform for comparison is CRLF -> LF applied to *produced*
bytes; doing it the other way round would silently repair a bare ``\\n``
the encoder should never have emitted.
"""

from __future__ import annotations

import pytest

from _fixtures import Fixture, crlf_to_lf, load_fixtures
from vstar.codec import rfc5545, rfc6350

ICS = load_fixtures("rfc5545", ".ics")
VCF = load_fixtures("rfc6350", ".vcf")


@pytest.mark.parametrize("fixture", ICS + VCF, ids=[f.stem for f in ICS + VCF])
def test_the_fixture_on_disk_is_lf_terminated(fixture: Fixture) -> None:
    assert b"\r\n" not in fixture.input, f"{fixture.path} carries CRLF on disk"


@pytest.mark.parametrize("fixture", ICS, ids=[f.stem for f in ICS])
def test_the_ics_encoder_emits_crlf_and_never_a_bare_lf(fixture: Fixture) -> None:
    out = rfc5545.encode(rfc5545.parse(fixture.input))
    assert b"\r\n" in out
    assert crlf_to_lf(out).count(b"\n") == out.count(b"\r\n")


@pytest.mark.parametrize("fixture", VCF, ids=[f.stem for f in VCF])
def test_the_vcf_encoder_emits_crlf_and_never_a_bare_lf(fixture: Fixture) -> None:
    out = b"".join(rfc6350.encode(c) for c in rfc6350.parse(fixture.input))
    assert b"\r\n" in out
    assert crlf_to_lf(out).count(b"\n") == out.count(b"\r\n")


@pytest.mark.parametrize("fixture", ICS, ids=[f.stem for f in ICS])
def test_the_ics_parser_is_liberal_about_terminators(fixture: Fixture) -> None:
    """LF-only, CRLF, and a mixture all parse to the same encoded bytes."""
    lf = fixture.input
    crlf = lf.replace(b"\n", b"\r\n")
    mixed = b"\r\n".join(lf.split(b"\n")[:2]) + b"\n" + b"\n".join(lf.split(b"\n")[2:])

    baseline = rfc5545.encode(rfc5545.parse(lf))
    assert rfc5545.encode(rfc5545.parse(crlf)) == baseline
    assert rfc5545.encode(rfc5545.parse(mixed)) == baseline


@pytest.mark.parametrize("fixture", VCF, ids=[f.stem for f in VCF])
def test_the_vcf_parser_is_liberal_about_terminators(fixture: Fixture) -> None:
    lf = fixture.input
    crlf = lf.replace(b"\n", b"\r\n")

    def encoded(data: bytes) -> bytes:
        return b"".join(rfc6350.encode(c) for c in rfc6350.parse(data))

    assert encoded(crlf) == encoded(lf)


def test_crlf_to_lf_is_applied_to_produced_bytes_only() -> None:
    """The helper's direction is the load-bearing part.

    Transforming the file's LF up to CRLF would also compare equal, right
    up until the encoder emits a bare ``\\n`` somewhere — which that
    direction would silently repair.
    """
    assert crlf_to_lf(b"A:1\r\nB:2\r\n") == b"A:1\nB:2\n"
    assert crlf_to_lf(b"A:1\nB:2\n") == b"A:1\nB:2\n"
