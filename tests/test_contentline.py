# SPDX-License-Identifier: MIT

"""The shared content-line scanner and folder.

Unfolding is liberal (CRLF, LF, or a mixture); folding is 75 OCTETS
measured in UTF-8 bytes and applied after property assembly.
"""

from __future__ import annotations

from _fixtures import physical_lines
from vstar._contentline import (
    MAX_LINE_OCTETS,
    Scanner,
    escape_text,
    fold_line,
    scan_all,
    unescape_text,
)


class TestScanner:
    def test_unfolds_crlf_input(self) -> None:
        assert scan_all(b"SUMMARY:one\r\n two\r\n") == ["SUMMARY:onetwo"]

    def test_unfolds_lf_only_input(self) -> None:
        assert scan_all(b"SUMMARY:one\n two\n") == ["SUMMARY:onetwo"]

    def test_unfolds_mixed_terminators(self) -> None:
        assert scan_all(b"A:1\r\nB:2\n\tcont\r\nC:3\n") == ["A:1", "B:2cont", "C:3"]

    def test_strips_only_the_single_leading_wsp(self) -> None:
        assert scan_all("SUMMARY:a\r\n  b\r\n") == ["SUMMARY:a b"]

    def test_surfaces_a_trailing_partial_line(self) -> None:
        assert scan_all("A:1\r\nB:2") == ["A:1", "B:2"]

    def test_skips_blank_physical_lines(self) -> None:
        assert scan_all("A:1\r\n\r\n\r\nB:2\r\n") == ["A:1", "B:2"]

    def test_wsp_line_after_a_blank_starts_a_fresh_logical_line(self) -> None:
        assert scan_all("DESCRIPTION:start\r\n\r\n more\r\n") == [
            "DESCRIPTION:start",
            "more",
        ]

    def test_empty_input_yields_nothing(self) -> None:
        assert scan_all(b"") == []

    def test_scanner_is_iterable_and_exhausts(self) -> None:
        s = Scanner("A:1\r\n")
        assert list(s) == ["A:1"]
        assert s.next() is None

    def test_accepts_str_and_bytes_alike(self) -> None:
        assert scan_all("A:1\r\n") == scan_all(b"A:1\r\n")


class TestFolding:
    def test_short_line_gets_one_crlf(self) -> None:
        assert fold_line("UID:x") == b"UID:x\r\n"

    def test_a_line_of_exactly_75_octets_is_not_folded(self) -> None:
        line = "X" * MAX_LINE_OCTETS
        assert fold_line(line) == line.encode() + b"\r\n"

    def test_a_line_of_76_octets_folds(self) -> None:
        line = "X" * (MAX_LINE_OCTETS + 1)
        assert fold_line(line) == b"X" * 75 + b"\r\n X\r\n"

    def test_no_physical_line_exceeds_75_octets(self) -> None:
        out = fold_line("SUMMARY:" + "a" * 500)
        for line in physical_lines(out):
            assert len(line) <= MAX_LINE_OCTETS

    def test_width_is_utf8_bytes_not_code_points(self) -> None:
        # 40 'e-acute': 40 code points, 80 UTF-8 bytes. A code-point
        # count would see 40 and refuse to fold; the octet count folds.
        value = "é" * 40
        out = fold_line(value)
        assert b"\r\n " in out
        for line in physical_lines(out):
            assert len(line) <= MAX_LINE_OCTETS

    def test_a_folded_line_unfolds_back_to_the_original(self) -> None:
        line = "SUMMARY:" + "é" * 120
        assert scan_all(fold_line(line)) == [line]

    def test_continuation_payload_is_74_octets(self) -> None:
        out = fold_line("X" * 300)
        lines = physical_lines(out)
        assert len(lines[0]) == 75
        for line in lines[1:]:
            assert line.startswith(b" ")
            assert len(line) <= 75


class TestEscaping:
    def test_escape_text_covers_the_rfc_set(self) -> None:
        assert escape_text("a,b;c\\d\ne") == "a\\,b\\;c\\\\d\\ne"

    def test_escape_text_drops_cr(self) -> None:
        assert escape_text("a\r\nb") == "a\\nb"

    def test_escape_text_passes_clean_text_through(self) -> None:
        assert escape_text("plain text") == "plain text"

    def test_unescape_text_reverses_the_rfc_set(self) -> None:
        assert unescape_text("a\\,b\\;c\\\\d\\ne", "drop-backslash") == "a,b;c\\d\ne"
        assert unescape_text("a\\Nb", "drop-backslash") == "a\nb"

    def test_unescape_text_unknown_escape_modes_differ(self) -> None:
        assert unescape_text("a\\xb", "drop-backslash") == "axb"
        assert unescape_text("a\\xb", "keep-both") == "a\\xb"

    def test_unescape_text_keeps_a_trailing_solitary_backslash(self) -> None:
        assert unescape_text("abc\\", "drop-backslash") == "abc\\"

    def test_round_trip_through_escape_and_unescape(self) -> None:
        raw = "Line one\nsemi; comma, back\\slash"
        assert unescape_text(escape_text(raw), "drop-backslash") == raw
