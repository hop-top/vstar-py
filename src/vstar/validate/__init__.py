# SPDX-License-Identifier: MIT

"""The V* semantic invariants the codec layer cannot catch.

A document can be syntactically valid RFC 5545 or RFC 6350, so that
parsing succeeds, and still violate V* discipline: a missing or
corrupted ``X-VSTAR-HASH``, a property outside the extension namespace,
a type-specific required property absent, a ``STATUS`` from the wrong
vocabulary, a malformed recurrence or duration.

The two entry points are :func:`validate` (a whole
:class:`~vstar.types.Calendar`) and :func:`validate_component` (one
:class:`~vstar.types.Component`). **Neither raises.** Validation *is*
the error channel: a document that fails every check still validates
successfully and returns a list of findings. An empty list means clean.
A port that raises on a diagnostic has inverted the API.

Every :class:`Diagnostic` carries a stable ``code`` — cataloged in
docs/validate-codes.md and generated from ``spec/registry/`` — that
consumers may match programmatically. ``message`` is human-readable and
may change in any release; do not match on it.

Coverage of spec/05, the conformance criteria:

- §1 required common properties (UID, DTSTAMP, X-VSTAR-HASH).
- §2 X-VSTAR-HASH integrity — the present-but-wrong case; an absent
  hash is reported by §1 instead.
- §3 extension namespace compliance — a non-standard property name
  without the ``X-`` prefix.
- §4 supersession discipline — a supersession VJOURNAL's required
  properties, and whether its ``RELATED-TO`` resolves.
- §5 type-specific required properties — VTODO, VEVENT, VFREEBUSY,
  VCARD.
- §6 RRULE conformance — unsupported (warning) and malformed (error).
- §7 DURATION well-formedness — the DURATION property, the relative
  form of TRIGGER, and the REPEAT count.
- §8 enumerated and integer value domains — a STATUS outside the
  vocabulary RFC 5545 §3.8.1.11 scopes to the component's own type; a
  CLASS outside §3.8.1.3's PUBLIC/PRIVATE/CONFIDENTIAL; a TRANSP
  outside §3.8.2.7's OPAQUE/TRANSPARENT; a PRIORITY, PERCENT-COMPLETE
  or SEQUENCE that is not a canonical decimal inside its domain (0-9,
  0-100, non-negative). Vocabularies compare case-insensitively; the
  canonical-decimal check is textual, so a SEQUENCE past any machine
  range is well-formed. REPEAT's form is checked by the same rule but
  reported under the §7 code. Values are checked wherever the property
  appears; component scope is not diagnosed, and :func:`validate` does
  not descend into sub-components.

**Path syntax.** ``Diagnostic.path`` is a dotted component/property
locator:

==================================  =====================================
Path                                Meaning
==================================  =====================================
``VCALENDAR``                       Calendar-level.
``VCALENDAR.VTODO[uid=foo]``        Component-level, on the VTODO whose
                                    UID is ``foo``.
``VCALENDAR.VTODO[uid=foo].DTSTAMP``  Property-level, on that VTODO's
                                    DTSTAMP.
``VCALENDAR.VTODO[#3]``             A UID-less VTODO, at positional
                                    index 3.
``VTODO[uid=foo].DTSTAMP``          :func:`validate_component` — no
                                    calendar prefix.
==================================  =====================================

Usage::

    from vstar.codec import rfc5545
    from vstar import validate

    for d in validate.validate(rfc5545.parse(data)):
        print(d.severity, d.code, d.path, d.message)
"""

from __future__ import annotations

from .._generated.codes import CODE_SEVERITIES
from ..types import Calendar, Component
from ._internal import (
    Diagnostic,
    PathIndex,
    Severity,
    component_path,
    registry_severity,
)
from .classification import check_classification
from .duration import check_duration
from .extensions import check_extension_namespace, standard_property_count
from .integer import check_integer_domains
from .integrity import check_hash_integrity
from .required import check_required_common
from .rrule import check_rrule
from .status import check_status_vocabulary
from .supersession import check_supersession_discipline
from .types import check_type_specific

__all__ = [
    "Diagnostic",
    "Severity",
    "codes",
    "severity_of",
    "standard_property_count",
    "validate",
    "validate_component",
]


def validate(cal: Calendar) -> list[Diagnostic]:
    """Check every component in ``cal`` and return the accumulated findings.

    An empty list means ``cal`` is clean. ``cal`` is not mutated.
    Diagnostics follow component order, then rule order within a
    component; consumers comparing against a fixture should sort, since
    only the set — not the emission order — is contractual.

    Prefer this over :func:`validate_component` whenever a calendar
    exists: the paths are more precise, and the cross-component rules
    (the orphan-supersession check) can only run here.
    """
    out: list[Diagnostic] = []
    index: PathIndex = {}
    for comp in cal.components:
        path = f"VCALENDAR.{component_path(comp, index)}"
        out.extend(_run_checks(comp, path, cal.components))
    return out


def validate_component(c: Component) -> list[Diagnostic]:
    """Check a single component in isolation.

    Paths start at the component itself, e.g.
    ``VTODO[uid=foo].DTSTAMP``.

    This is the right entry point when there is no parent calendar — a
    freshly minted component, say, checked before it is appended. The
    cross-component orphan-supersession rule is skipped, not guessed:
    with no ledger to resolve against, "this target does not exist" is a
    claim this entry point cannot make.
    """
    return _run_checks(c, component_path(c, {}), None)


def codes() -> list[str]:
    """Every registry diagnostic code, in registry order."""
    return list(CODE_SEVERITIES)


def severity_of(code: str) -> Severity | None:
    """The severity the registry assigns ``code``.

    ``None`` when the string names no known code. Consumers must
    tolerate unknown codes — new ones may appear in any release — so
    this reports absence rather than raising.
    """
    return registry_severity(code)


def _run_checks(
    c: Component,
    path: str,
    ledger: list[Component] | None,
) -> list[Diagnostic]:
    """Run every rule against ``c`` at ``path``.

    ``ledger`` supplies the cross-component context the
    orphan-supersession rule needs; ``None`` means there is none and
    that rule is skipped.
    """
    return [
        *check_required_common(c, path),
        *check_hash_integrity(c, path),
        *check_extension_namespace(c, path),
        *check_type_specific(c, path),
        *check_status_vocabulary(c, path),
        *check_classification(c, path),
        *check_integer_domains(c, path),
        *check_supersession_discipline(c, ledger, path),
        *check_rrule(c, path),
        *check_duration(c, path),
    ]
