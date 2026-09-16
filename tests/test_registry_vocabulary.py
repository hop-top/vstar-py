# SPDX-License-Identifier: MIT

"""Reconcile this port's wire constants with the registry vocabularies.

The two are built from different sources on purpose. The validator's
tables are projected from the wire constants the codec encodes against,
so they cannot disagree with what the library writes; the generated
tables are rendered from ``spec/registry/status-vocabulary.json``, so
they cannot disagree with the other four ports. These tests are the
join — what lets both guarantees hold at once. Without them, generating
the tables would buy cross-language agreement by giving up the codec
linkage, and deriving them would buy the codec linkage by giving up
cross-language agreement.

Order matters, not just membership: the VS044 message joins the allowed
values, so a reordering is a user-visible change the behavior fixtures
pin.
"""

from __future__ import annotations

import pytest

from vstar._generated.codes import (
    CLASS_VOCABULARY,
    RELTYPE_VOCABULARY,
    STATUS_VOCABULARY,
    TRANSP_VOCABULARY,
)
from vstar.types import (
    CLASS_CONFIDENTIAL,
    CLASS_PRIVATE,
    CLASS_PUBLIC,
    COMP_EVENT,
    COMP_JOURNAL,
    COMP_TODO,
    EVENT_CANCELLED,
    EVENT_CONFIRMED,
    EVENT_TENTATIVE,
    JOURNAL_CANCELLED,
    JOURNAL_DRAFT,
    JOURNAL_FINAL,
    REL_CHILD,
    REL_CONCEPT,
    REL_DEPENDS_ON,
    REL_FINISH_TO_FINISH,
    REL_FINISH_TO_START,
    REL_FIRST,
    REL_NEXT,
    REL_PARENT,
    REL_REF_ID,
    REL_SIBLING,
    REL_START_TO_FINISH,
    REL_START_TO_START,
    TODO_CANCELLED,
    TODO_COMPLETED,
    TODO_IN_PROCESS,
    TODO_NEEDS_ACTION,
    TRANSP_OPAQUE,
    TRANSP_TRANSPARENT,
)

# Projected from the wire constants, exactly as the validator's table
# is — not read back out of the generated module, which would make the
# assertion vacuous.
_FROM_CONSTANTS: dict[str, tuple[str, ...]] = {
    str(COMP_EVENT): (
        str(EVENT_TENTATIVE),
        str(EVENT_CONFIRMED),
        str(EVENT_CANCELLED),
    ),
    str(COMP_TODO): (
        str(TODO_NEEDS_ACTION),
        str(TODO_IN_PROCESS),
        str(TODO_COMPLETED),
        str(TODO_CANCELLED),
    ),
    str(COMP_JOURNAL): (
        str(JOURNAL_DRAFT),
        str(JOURNAL_FINAL),
        str(JOURNAL_CANCELLED),
    ),
}


def test_status_vocabulary_covers_the_same_component_types() -> None:
    assert sorted(STATUS_VOCABULARY) == sorted(_FROM_CONSTANTS)


@pytest.mark.parametrize("comp", sorted(_FROM_CONSTANTS))
def test_status_vocabulary_matches_wire_constants(comp: str) -> None:
    assert STATUS_VOCABULARY[comp] == _FROM_CONSTANTS[comp]


# CLASS and TRANSP are closed vocabularies. RELTYPE is not — RFC 5545
# §3.2.15 admits IANA and X- values — so the assertion is that the
# registry lists exactly the *registered* set this port names, not that
# no other value may appear on the wire.
_FLAT = {
    "CLASS": (
        CLASS_VOCABULARY,
        (str(CLASS_PUBLIC), str(CLASS_PRIVATE), str(CLASS_CONFIDENTIAL)),
    ),
    "TRANSP": (
        TRANSP_VOCABULARY,
        (str(TRANSP_OPAQUE), str(TRANSP_TRANSPARENT)),
    ),
    "RELTYPE": (
        RELTYPE_VOCABULARY,
        (
            REL_PARENT,
            REL_CHILD,
            REL_SIBLING,
            REL_FINISH_TO_START,
            REL_FINISH_TO_FINISH,
            REL_START_TO_FINISH,
            REL_START_TO_START,
            REL_DEPENDS_ON,
            REL_FIRST,
            REL_NEXT,
            REL_CONCEPT,
            REL_REF_ID,
        ),
    ),
}


@pytest.mark.parametrize("name", sorted(_FLAT))
def test_flat_vocabulary_matches_wire_constants(name: str) -> None:
    registry, want = _FLAT[name]
    assert registry == want
