# SPDX-License-Identifier: MIT

"""The ``X-VSTAR-HASH`` property name, in its own module.

The constant **belongs to** :mod:`vstar.hashing` and the public import
path is ``vstar.hashing.X_VSTAR_HASH_PROPERTY``. It sits in a private
module only to break an import cycle: :mod:`vstar.canonical` needs the
name to implement rule 7's exclusion, and :mod:`vstar.hashing` imports
:mod:`vstar.canonical` to compute the bytes it digests.

It cannot live inside the ``hashing`` package even as a sub-module —
importing ``vstar.hashing._names`` executes ``vstar/hashing/__init__.py``
first, which is the cycle — so it lives beside the package instead.

The alternative, hoisting the constant to the package root as public
surface, is explicitly ruled out by the API mapping: the string is
meaningful only in company with the hash functions that write and read
it, so the root must not export it.
"""

from __future__ import annotations

__all__ = ["X_VSTAR_HASH_PROPERTY"]

#: The property name V* uses to carry a component's content hash.
#:
#: Rule 7 excludes this property from the canonical bytes its own value
#: is computed over; otherwise the stored hash would feed back into its
#: own digest.
X_VSTAR_HASH_PROPERTY = "X-VSTAR-HASH"
