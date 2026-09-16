# SPDX-License-Identifier: MIT

"""The V* wire-format codecs.

``vstar.codec.rfc5545`` reads and writes iCalendar (RFC 5545);
``vstar.codec.rfc6350`` reads and writes vCard 4.0 (RFC 6350). Both
preserve wire order on parse — canonical form is the only layer that
sorts.
"""

from __future__ import annotations

from . import rfc5545, rfc6350

__all__ = ["rfc5545", "rfc6350"]
