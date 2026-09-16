# SPDX-License-Identifier: MIT

"""Shared conformance-corpus loader.

The corpus is authored at ``spec/v0.1/conformance/``, two levels above
``py/``. Paths resolve from this file's own location rather than from
the working directory, so the loader works whichever directory pytest
is invoked from.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

#: Absolute path to ``spec/``.
SPEC_DIR = Path(__file__).resolve().parents[2] / "spec"

#: Absolute path to ``spec/v0.1/conformance/``.
CONFORMANCE_DIR = SPEC_DIR / "v0.1" / "conformance"

#: Absolute path to ``spec/behavior/`` — the language-agnostic tables
#: stating what a conformant implementation *does*, as opposed to the
#: conformance corpus, which pins what it *emits*.
BEHAVIOR_DIR = SPEC_DIR / "behavior"


@dataclass(frozen=True, slots=True)
class Fixture:
    """One corpus case: the stem plus whichever sibling files exist."""

    #: Basename without extension, e.g. ``world``.
    stem: str
    #: Absolute path of the input document.
    path: Path
    #: Raw input bytes, exactly as they sit on disk (LF-terminated).
    input: bytes
    #: The ``.error`` sibling's first non-empty line, when present.
    sentinel: str | None


def load_fixtures(family: str, ext: str) -> list[Fixture]:
    """Enumerate every fixture under ``<family>/`` whose input carries ``ext``.

    Sorted by stem so failures report in a stable order. The tree is
    walked; no fixture name is hard-coded.
    """
    directory = CONFORMANCE_DIR / family
    out: list[Fixture] = []
    for path in sorted(directory.glob(f"*{ext}")):
        stem = path.name[: -len(ext)]
        out.append(
            Fixture(
                stem=stem,
                path=path,
                input=path.read_bytes(),
                sentinel=_read_sentinel(directory, stem),
            )
        )
    return out


def load_fuzz_seeds(family: str) -> list[Fixture]:
    """Every ``fuzz-seed/<family>/*.bytes`` input, sorted by filename."""
    return load_fixtures(f"fuzz-seed/{family}", ".bytes")


def behavior_json(family: str, name: str) -> object:
    """One decoded ``spec/behavior/<family>/<name>`` sidecar."""
    path = BEHAVIOR_DIR / family / name
    return json.loads(path.read_text(encoding="utf-8"))


def behavior_stems(family: str, ext: str) -> list[str]:
    """Every stem under ``spec/behavior/<family>/`` carrying ``ext``.

    The tree is walked and sorted; no fixture name is hard-coded, so a
    fixture added upstream joins the gate without a code change here.
    """
    directory = BEHAVIOR_DIR / family
    return sorted(p.name[: -len(ext)] for p in directory.glob(f"*{ext}"))


def _read_sentinel(directory: Path, stem: str) -> str | None:
    """The first non-empty line of ``<stem>.error``, or ``None``."""
    sibling = directory / f"{stem}.error"
    if not sibling.is_file():
        return None
    for line in sibling.read_text(encoding="utf-8").splitlines():
        trimmed = line.strip()
        if trimmed:
            return trimmed
    return None


def crlf_to_lf(data: bytes) -> bytes:
    """Strip CR before LF in *produced* bytes, for corpus comparison.

    The corpus files are LF on disk; the encoder emits CRLF. The porting
    guide licenses exactly one transform, and this is its direction:
    normalize what *this port produced*, never what the file holds.
    Doing it the other way round would silently repair a bare ``\\n``
    the encoder should never have emitted.
    """
    return data.replace(b"\r\n", b"\n")


def assert_bytes_equal(got: bytes, want: bytes, label: str = "") -> None:
    """Assert two byte sequences are identical, reporting the divergence.

    This compares BYTES. It never trims, never re-decodes, and never
    normalizes line endings.
    """
    if got == want:
        return
    prefix = f"{label}: " if label else ""
    for i in range(min(len(got), len(want))):
        if got[i] != want[i]:
            raise AssertionError(
                f"{prefix}bytes diverge at offset {i}: "
                f"got 0x{got[i]:02x} ({_window(got, i)!r}), "
                f"want 0x{want[i]:02x} ({_window(want, i)!r})"
            )
    raise AssertionError(
        f"{prefix}byte lengths differ: got {len(got)}, want {len(want)}; "
        f"common prefix of {min(len(got), len(want))} bytes matches"
    )


def physical_lines(data: bytes) -> list[bytes]:
    """Split encoded bytes on CRLF, returning each physical line's bytes."""
    out = data.split(b"\r\n")
    if out and out[-1] == b"":
        out.pop()
    return out


def _window(data: bytes, i: int) -> str:
    """A short printable window around offset ``i``, for failure messages."""
    lo = max(0, i - 12)
    hi = min(len(data), i + 12)
    return data[lo:hi].decode("utf-8", errors="replace")
