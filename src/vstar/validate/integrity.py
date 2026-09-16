# SPDX-License-Identifier: MIT

"""spec/05 §2 — X-VSTAR-HASH integrity."""

from __future__ import annotations

from .._generated.codes import BAD_XVSTAR_HASH
from ..hashing import verify_x_vstar
from ..types import Component
from ._internal import X_VSTAR_HASH, Diagnostic, diagnostic, has

__all__ = ["check_hash_integrity"]


def check_hash_integrity(c: Component, path: str) -> list[Diagnostic]:
    """Recompute ``c``'s hash and flag a stored one that is present but wrong.

    An **absent** hash is intentionally not flagged here — that case
    belongs to the required-common-property rule. The split keeps the
    diagnostic surface unambiguous: present-but-wrong is a different
    bug than absent, and a consumer that sees both codes at once is
    looking at a genuinely different document than one that sees either
    alone.
    """
    if not has(c, X_VSTAR_HASH):
        return []
    ok, want, got = verify_x_vstar(c)
    if ok:
        return []
    return [
        diagnostic(
            BAD_XVSTAR_HASH,
            f"{X_VSTAR_HASH} does not match recomputed canonical hash; "
            f"want={want} got={got} (spec/05 §2)",
            f"{path}.{X_VSTAR_HASH}",
        )
    ]
