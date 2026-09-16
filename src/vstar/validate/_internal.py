# SPDX-License-Identifier: MIT

"""The shared value types and locator helpers every rule builds on.

:class:`Diagnostic` and :class:`Severity` live here rather than in
:mod:`vstar.validate` so the rule modules can import them without
importing the package that imports them back.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from .._generated.codes import CODE_SEVERITIES
from ..types import Component

__all__ = [
    "X_VSTAR_HASH",
    "Diagnostic",
    "PathIndex",
    "Severity",
    "component_path",
    "diagnostic",
    "equal_fold",
    "has",
    "registry_severity",
    "wire_type",
]

#: The impact level of a :class:`Diagnostic`.
#:
#: ``"error"`` marks a MUST violation — the document is not V*
#: conformant. ``"warning"`` marks a SHOULD violation or a stylistic
#: concern, such as an unknown property name without the ``X-`` prefix.
#:
#: A string alias rather than an enum: the registry renders severities
#: as wire strings, the behavior fixtures pin those same strings, and a
#: second spelling would be a second source of truth.
Severity = Literal["error", "warning"]

#: The property name V* uses to carry the content hash.
#:
#: Deliberately a local constant rather than an import from
#: :mod:`vstar.hashing`: ``validate`` inspects raw property names
#: without taking on the hashing module's identity, and the fixtures
#: assert that the two agree.
X_VSTAR_HASH = "X-VSTAR-HASH"

#: Running positional index per component type, for UID-less paths.
PathIndex = dict[str, int]


@dataclass(frozen=True, slots=True)
class Diagnostic:
    """A single validation finding.

    ``code`` is the stable catalog identifier cataloged in
    docs/validate-codes.md; it is stable across minor versions per
    semver, so consumers may match on it programmatically.

    ``message`` is human-readable detail and is **not** stable across
    versions. Match ``code`` instead — the behavior fixtures omit
    messages for exactly this reason.

    ``path`` is a dotted component/property locator (see the package
    doc).
    """

    #: The stable catalog identifier.
    code: str
    #: ``"error"`` for a MUST violation, ``"warning"`` for a SHOULD.
    severity: Severity
    #: The dotted locator.
    path: str
    #: Human-readable detail. Not stable; do not match on it.
    message: str


def registry_severity(code: str) -> Severity | None:
    """The registry's severity for ``code``, narrowed to :data:`Severity`.

    The generated table is typed ``dict[str, str]`` — the generator
    emits wire strings and does not spell the closed set. Narrowing
    happens here, once, so every caller downstream works in the closed
    type. A value outside the set means the registry and this port have
    diverged, which is a generator bug rather than a document problem,
    so it is raised rather than reported as a diagnostic.
    """
    severity = CODE_SEVERITIES.get(code)
    if severity is None:
        return None
    if severity == "error":
        return "error"
    if severity == "warning":
        return "warning"
    raise ValueError(f"registry severity {severity!r} for {code} is not a Severity")


def diagnostic(code: str, message: str, path: str) -> Diagnostic:
    """Build a :class:`Diagnostic`, severity taken from the registry.

    Severity is registry data, not a per-rule decision: a rule that
    spelled its own severity would be a second source of truth, free to
    drift the moment ``spec/registry/diagnostic-codes.json`` changes.
    The only way to change a severity is to change the registry and
    re-run the generator.
    """
    severity = registry_severity(code)
    if severity is None:
        raise KeyError(f"{code} is not a registry diagnostic code")
    return Diagnostic(code=code, severity=severity, path=path, message=message)


def wire_type(c: Component) -> str:
    """The component's wire type as it arrived.

    :class:`~vstar.types.CompType` admits unregistered members, so a
    ``VCARD`` block nested inside a ``VCALENDAR`` carries its wire
    string through verbatim. Reading the raw string keeps the ``VCARD``
    rule reachable.
    """
    return str(c.type)


def equal_fold(a: str, b: str) -> bool:
    """Case-insensitive string comparison, per RFC 5545 §3.1."""
    return a.upper() == b.upper()


def has(c: Component, name: str) -> bool:
    """Whether ``c`` carries a property named ``name``, case-insensitively."""
    return c.get(name) is not None


def component_path(c: Component, index: PathIndex) -> str:
    """The path segment identifying ``c`` relative to its container.

    ``<TYPE>[uid=<uid>]``, or ``<TYPE>[#<n>]`` when ``c`` has no UID.
    ``index`` carries the running positional counter per type so two
    UID-less components of the same type get distinct, stable segments.
    """
    uid = c.uid()
    type_ = wire_type(c)
    if uid != "":
        return f"{type_}[uid={uid}]"
    n = index.get(type_, 0)
    index[type_] = n + 1
    return f"{type_}[#{n}]"
