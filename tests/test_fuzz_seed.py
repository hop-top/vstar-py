# SPDX-License-Identifier: MIT

"""The robustness gate: a seed either parses or raises a ``VstarError``.

Nothing else is acceptable. A ``ValueError``, an ``IndexError`` or a
``UnicodeDecodeError`` escaping the codec is an unhandled edge case, not
a documented failure class.
"""

from __future__ import annotations

from collections.abc import Callable

import pytest

from _fixtures import Fixture, load_fuzz_seeds
from vstar import VstarError
from vstar.codec import rfc5545, rfc6350

ICS_SEEDS = load_fuzz_seeds("rfc5545")
VCF_SEEDS = load_fuzz_seeds("rfc6350")


def test_the_seeds_are_found() -> None:
    assert ICS_SEEDS, "no rfc5545 fuzz seeds loaded"
    assert VCF_SEEDS, "no rfc6350 fuzz seeds loaded"


@pytest.mark.parametrize("seed", ICS_SEEDS, ids=[s.stem for s in ICS_SEEDS])
def test_ics_seed_raises_only_vstar_error(seed: Fixture) -> None:
    # Re-encoding exercises the encoder on every seed that parses, so an
    # encoder crash surfaces here too.
    assert_only_vstar_error(
        lambda: rfc5545.encode(rfc5545.parse(seed.input)), seed.stem
    )


@pytest.mark.parametrize("seed", VCF_SEEDS, ids=[s.stem for s in VCF_SEEDS])
def test_vcf_seed_raises_only_vstar_error(seed: Fixture) -> None:
    def run() -> None:
        for card in rfc6350.parse(seed.input):
            rfc6350.encode(card)

    assert_only_vstar_error(run, seed.stem)


@pytest.mark.parametrize("seed", ICS_SEEDS, ids=[s.stem for s in ICS_SEEDS])
def test_ics_seed_survives_arbitrary_byte_truncation(seed: Fixture) -> None:
    for cut in range(0, len(seed.input), 7):
        assert_only_vstar_error(
            lambda: rfc5545.encode(rfc5545.parse(seed.input[:cut])),  # noqa: B023
            f"{seed.stem}[:{cut}]",
        )


@pytest.mark.parametrize("seed", VCF_SEEDS, ids=[s.stem for s in VCF_SEEDS])
def test_vcf_seed_survives_arbitrary_byte_truncation(seed: Fixture) -> None:
    for cut in range(0, len(seed.input), 7):

        def run(at: int = cut) -> None:
            for card in rfc6350.parse(seed.input[:at]):
                rfc6350.encode(card)

        assert_only_vstar_error(run, f"{seed.stem}[:{cut}]")


def assert_only_vstar_error(fn: Callable[[], object], label: str) -> None:
    try:
        fn()
    except VstarError as e:
        assert isinstance(e.sentinel, str)
    except Exception as e:
        raise AssertionError(
            f"{label}: expected VstarError, got {type(e).__name__}: {e}"
        ) from e
