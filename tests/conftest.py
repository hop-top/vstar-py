# SPDX-License-Identifier: MIT

"""Put the tests directory on ``sys.path`` so ``_fixtures`` imports.

pytest's rootdir-based insertion covers the default ``prepend`` import
mode, but making it explicit keeps the loader importable however the
suite is invoked.
"""

from __future__ import annotations

import sys
from pathlib import Path

_HERE = str(Path(__file__).resolve().parent)
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)
