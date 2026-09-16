# SPDX-License-Identifier: MIT

"""spec/05 §4 — supersession discipline."""

from __future__ import annotations

from typing import Final

from .._generated.codes import SUPERSESSION_MISSING_PROPS, SUPERSESSION_ORPHAN
from ..supersession import CATEGORY_STATUS_SUPERSESSION, PROP_EFFECTIVE_STATUS
from ..types import COMP_JOURNAL, Component
from ._internal import Diagnostic, diagnostic, equal_fold, wire_type

__all__ = ["check_supersession_discipline"]

#: The RFC 5545 §3.8.4.5 property carrying the supersession target.
_RELATED_TO: Final[str] = "RELATED-TO"


def check_supersession_discipline(
    c: Component,
    ledger: list[Component] | None,
    path: str,
) -> list[Diagnostic]:
    """Check a supersession VJOURNAL against spec/05 §4.

    Two rules live here. The missing-properties rule is
    component-local: a supersession journal that names no target, or
    records no effective status, is incomplete on its own terms. The
    orphan rule is not — it asks whether the named target exists, which
    only a ledger can answer.

    ``ledger`` is ``None`` for the single-component entry point, and the
    orphan rule is then skipped entirely rather than guessed at. Absence
    of evidence is not evidence of an orphan: a component validated in
    isolation has no calendar, so "the target is missing" is a claim it
    is not in a position to make.
    """
    if wire_type(c) != COMP_JOURNAL:
        return []
    if not _categories_contain_supersession(c):
        return []

    out: list[Diagnostic] = []

    related = c.get(_RELATED_TO)
    target = related.value.strip() if related is not None else ""
    if target == "":
        out.append(
            diagnostic(
                SUPERSESSION_MISSING_PROPS,
                f"supersession VJOURNAL missing {_RELATED_TO} (spec/02, spec/05 §4)",
                f"{path}.{_RELATED_TO}",
            )
        )

    effective = c.get(PROP_EFFECTIVE_STATUS)
    if effective is None or effective.value.strip() == "":
        out.append(
            diagnostic(
                SUPERSESSION_MISSING_PROPS,
                f"supersession VJOURNAL missing {PROP_EFFECTIVE_STATUS} "
                "(spec/02, spec/05 §4)",
                f"{path}.{PROP_EFFECTIVE_STATUS}",
            )
        )

    if (
        related is not None
        and ledger is not None
        and target != ""
        and not _ledger_contains_uid(ledger, target)
    ):
        out.append(
            diagnostic(
                SUPERSESSION_ORPHAN,
                f"supersession VJOURNAL {_RELATED_TO}={target} has no matching "
                "component in calendar (spec/02, spec/05 §4)",
                f"{path}.{_RELATED_TO}",
            )
        )

    return out


def _categories_contain_supersession(c: Component) -> bool:
    """Whether ``c`` carries a CATEGORIES token naming the supersession category.

    Comma-separated, compared case-insensitively.
    """
    return any(
        equal_fold(tok.strip(), CATEGORY_STATUS_SUPERSESSION)
        for p in c.get_all("CATEGORIES")
        for tok in p.value.split(",")
    )


def _ledger_contains_uid(ledger: list[Component], uid: str) -> bool:
    """Whether any component in ``ledger`` has UID ``uid``.

    Comparison is case-sensitive per RFC 5545 §3.8.4.7: UIDs are opaque
    identifiers, not user-facing text.
    """
    return any(c.uid() == uid for c in ledger)
