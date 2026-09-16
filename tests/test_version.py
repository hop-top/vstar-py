# SPDX-License-Identifier: MIT

from __future__ import annotations

import re

from packaging.version import InvalidVersion, Version

import vstar

# The canonical PEP 440 spelling a wheel consumer sees: hatchling
# normalizes the version when it builds the artifact.
CANONICAL = re.compile(r"\d+\.\d+\.\d+(?:[ab]|rc)?\d*(?:\.dev\d+)?")


def test_version_is_pep440() -> None:
    # release-please writes its SemVer spelling ("X.Y.Z-alpha.N") into
    # pyproject.toml, and an editable install reports it verbatim, while
    # a built wheel carries the normalized "X.Y.ZaN". Both are one PEP 440
    # version: the test accepts any legal spelling and pins the canonical
    # form it normalizes to.
    try:
        parsed = Version(vstar.__version__)
    except InvalidVersion as exc:
        raise AssertionError(f"not a PEP 440 version: {vstar.__version__!r}") from exc
    assert CANONICAL.fullmatch(str(parsed)), str(parsed)


def test_version_is_exported() -> None:
    assert "__version__" in vstar.__all__
