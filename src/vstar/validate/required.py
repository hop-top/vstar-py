# SPDX-License-Identifier: MIT

"""spec/05 §1 — required common properties."""

from __future__ import annotations

from .._generated.codes import MISSING_DTSTAMP, MISSING_UID, MISSING_XVSTAR_HASH
from ..types import Component
from ._internal import X_VSTAR_HASH, Diagnostic, diagnostic, has

__all__ = ["check_required_common"]


def check_required_common(c: Component, path: str) -> list[Diagnostic]:
    """One diagnostic per missing required common property.

    UID, DTSTAMP and X-VSTAR-HASH are checked in that order so the
    diagnostic stream is deterministic. Each path appends the property
    name to the component locator.
    """
    out: list[Diagnostic] = []
    if not has(c, "UID"):
        out.append(
            diagnostic(
                MISSING_UID,
                "required common property UID is missing (spec/02)",
                f"{path}.UID",
            )
        )
    if not has(c, "DTSTAMP"):
        out.append(
            diagnostic(
                MISSING_DTSTAMP,
                "required common property DTSTAMP is missing (spec/02)",
                f"{path}.DTSTAMP",
            )
        )
    if not has(c, X_VSTAR_HASH):
        out.append(
            diagnostic(
                MISSING_XVSTAR_HASH,
                f"required common property {X_VSTAR_HASH} is missing (spec/02)",
                f"{path}.{X_VSTAR_HASH}",
            )
        )
    return out
