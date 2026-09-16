# SPDX-License-Identifier: MIT

"""All twelve V* failure classes, and the sentinel identifiers they carry.

The identifier is the contract: ``malformed/*.error`` files name a class
by its Go spelling, so a port that re-spells one cannot run the shared
corpus.
"""

from __future__ import annotations

import pytest

from vstar import (
    AlreadyClosed,
    HeaderLocked,
    IterationCap,
    Malformed,
    MissingUid,
    NoAnchor,
    NoTrigger,
    TargetCorrupted,
    UnboundedExpansion,
    UnclosedBlock,
    UnsupportedRrule,
    UnsupportedVersion,
    VstarError,
)

TWELVE = [
    (Malformed, "ErrMalformed"),
    (UnclosedBlock, "ErrUnclosedBlock"),
    (UnsupportedVersion, "ErrUnsupportedVersion"),
    (MissingUid, "ErrMissingUID"),
    (UnsupportedRrule, "ErrUnsupportedRRule"),
    (IterationCap, "ErrIterationCap"),
    (UnboundedExpansion, "ErrUnboundedExpansion"),
    (TargetCorrupted, "ErrTargetCorrupted"),
    (AlreadyClosed, "ErrAlreadyClosed"),
    (HeaderLocked, "ErrHeaderLocked"),
    (NoTrigger, "ErrNoTrigger"),
    (NoAnchor, "ErrNoAnchor"),
]


@pytest.mark.parametrize(("cls", "sentinel"), TWELVE)
def test_sentinel_identifier_is_the_go_spelling(
    cls: type[VstarError], sentinel: str
) -> None:
    assert cls.sentinel == sentinel
    assert cls("boom").sentinel == sentinel


@pytest.mark.parametrize(("cls", "_sentinel"), TWELVE)
def test_every_class_derives_from_vstar_error(
    cls: type[VstarError], _sentinel: str
) -> None:
    assert issubclass(cls, VstarError)
    assert issubclass(cls, Exception)


def test_all_twelve_are_declared_and_distinct() -> None:
    assert len({cls for cls, _ in TWELVE}) == 12
    assert len({s for _, s in TWELVE}) == 12


def test_catching_by_class_and_by_attribute_both_work() -> None:
    with pytest.raises(Malformed):
        raise Malformed("x")
    try:
        raise IterationCap("y")
    except VstarError as e:
        assert e.sentinel == "ErrIterationCap"


def test_positional_context_is_carried_when_known() -> None:
    err = Malformed("bad escape", line=7)
    assert err.line == 7
    assert "7" in str(err)
    assert Malformed("bad escape").line is None
