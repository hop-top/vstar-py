# SPDX-License-Identifier: MIT

"""The ``validate`` surface — V*'s semantic conformance checks.

Gated by ``spec/behavior/validate/*.diagnostics.json``: every ``.ics``
under that directory has a same-stem ``.diagnostics.json`` sibling
naming the exact findings the reference emits. The tree is walked
rather than enumerated, so a fixture added upstream becomes a case here
without a test edit.

Messages are deliberately absent from the fixtures.
:attr:`~vstar.validate.Diagnostic.message` is human-readable and not
part of the contract (docs/validate-codes.md §Stability). Comparison is
on ``(code, severity, path)`` only, sorted by ``(path, code)``.
"""

from __future__ import annotations

import re
from copy import deepcopy
from pathlib import Path

import pytest

from _fixtures import BEHAVIOR_DIR, CONFORMANCE_DIR, behavior_json, behavior_stems
from vstar import Component, Property, hashing
from vstar._generated.codes import (
    CLASS_NOT_IN_VOCABULARY,
    CODE_SEVERITIES,
    INTEGER_OUT_OF_DOMAIN,
    MISSING_DTSTAMP,
    MISSING_UID,
    STANDARD_PROPERTIES,
    STATUS_NOT_IN_VOCABULARY,
    SUPERSESSION_MISSING_PROPS,
    SUPERSESSION_ORPHAN,
    TRANSP_NOT_IN_VOCABULARY,
)
from vstar.codec import rfc5545
from vstar.supersession import PROP_EFFECTIVE_STATUS
from vstar.types import Calendar
from vstar.validate import (
    Diagnostic,
    codes,
    severity_of,
    standard_property_count,
    validate,
    validate_component,
)

#: ``spec/behavior/validate/`` — the layer-(d) gate.
VALIDATE_DIR = BEHAVIOR_DIR / "validate"

#: Every fixture stem under the gate directory.
STEMS = behavior_stems("validate", ".ics")


def _row(d: Diagnostic) -> tuple[str, str, str]:
    """A diagnostic reduced to the three fields the fixtures compare."""
    return (d.path, d.code, d.severity)


def _rows(ds: list[Diagnostic]) -> list[tuple[str, str, str]]:
    """Sorted comparison rows for a diagnostic list."""
    return sorted(_row(d) for d in ds)


def _expected(stem: str) -> list[tuple[str, str, str]]:
    """Sorted comparison rows from ``<stem>.diagnostics.json``."""
    raw = behavior_json("validate", f"{stem}.diagnostics.json")
    assert isinstance(raw, list)
    out: list[tuple[str, str, str]] = []
    for entry in raw:
        assert isinstance(entry, dict)
        out.append((str(entry["path"]), str(entry["code"]), str(entry["severity"])))
    return sorted(out)


def _calendar(stem: str) -> Calendar:
    """Parse ``<stem>.ics`` from the gate directory."""
    return rfc5545.parse((VALIDATE_DIR / f"{stem}.ics").read_bytes())


def _sole_component(stem: str) -> Component:
    """The lone component of a single-component fixture."""
    cal = _calendar(stem)
    assert len(cal.components) == 1
    return cal.components[0]


def test_gate_directory_is_not_empty() -> None:
    assert STEMS


@pytest.mark.parametrize("stem", STEMS)
def test_behavior_fixture(stem: str) -> None:
    assert _rows(validate(_calendar(stem))) == _expected(stem)


def test_every_registry_code_is_exercised_by_a_fixture() -> None:
    emitted = {d.code for stem in STEMS for d in validate(_calendar(stem))}
    assert sorted(set(CODE_SEVERITIES) - emitted) == []


def test_every_fixture_row_severity_matches_the_registry() -> None:
    for stem in STEMS:
        for path, code, severity in _expected(stem):
            assert CODE_SEVERITIES[code] == severity, f"{stem}: {path}"


def test_every_emitted_severity_matches_the_registry() -> None:
    for stem in STEMS:
        for d in validate(_calendar(stem)):
            assert d.severity == CODE_SEVERITIES[d.code], f"{stem}: {d.path}"


def test_codes_lists_every_registry_code() -> None:
    assert sorted(codes()) == sorted(CODE_SEVERITIES)


def test_codes_is_in_registry_order() -> None:
    assert codes() == list(CODE_SEVERITIES)


def test_severity_of_answers_from_the_registry() -> None:
    for code in CODE_SEVERITIES:
        assert severity_of(code) == CODE_SEVERITIES[code]


def test_severity_of_is_none_for_an_unknown_code() -> None:
    assert severity_of("NOT-A-CODE") is None


def test_severity_of_spans_both_severities() -> None:
    # A constant-returning implementation would pass a single-severity
    # check; the registry carries both, so both must come back.
    assert {severity_of(c) for c in CODE_SEVERITIES} == {"error", "warning"}


def test_standard_property_count_matches_the_allow_list() -> None:
    assert standard_property_count() == len(STANDARD_PROPERTIES)
    assert standard_property_count() > 0


def test_validate_component_paths_omit_the_calendar_prefix() -> None:
    got = _rows(validate_component(_sole_component("missing_dtstamp")))
    assert got == [
        (
            "VJOURNAL[uid=journal-no-dtstamp].DTSTAMP",
            MISSING_DTSTAMP,
            CODE_SEVERITIES[MISSING_DTSTAMP],
        )
    ]


def test_validate_component_still_emits_the_component_local_supersession_code() -> None:
    comp = _sole_component("supersession_missing_props")
    assert SUPERSESSION_MISSING_PROPS in [d.code for d in validate_component(comp)]


def test_validate_component_skips_the_orphan_supersession_code() -> None:
    # The orphan fixture's RELATED-TO resolves to nothing even inside
    # its own calendar, so `validate` flags it. `validate_component`
    # sees one component and cannot resolve anything, so it must stay
    # silent rather than guess.
    cal = _calendar("supersession_orphan")
    assert SUPERSESSION_ORPHAN in [d.code for d in validate(cal)]
    comp = _sole_component("supersession_orphan")
    assert SUPERSESSION_ORPHAN not in [d.code for d in validate_component(comp)]


def test_validate_returns_empty_for_a_clean_calendar() -> None:
    assert validate(_calendar("clean_vevent")) == []


def test_uid_less_components_of_one_type_get_distinct_positional_paths() -> None:
    # No behavior fixture carries two UID-less components of the same
    # type, so the per-type positional counter would otherwise go
    # unexercised — and a counter frozen at zero would collapse two
    # findings onto one indistinguishable locator.
    cal = _calendar("missing_uid")
    cal.components.append(deepcopy(cal.components[0]))
    paths = {d.path for d in validate(cal) if d.code == MISSING_UID}
    assert paths == {
        "VCALENDAR.VJOURNAL[#0].UID",
        "VCALENDAR.VJOURNAL[#1].UID",
    }


@pytest.mark.parametrize("name", ["RELATED-TO", PROP_EFFECTIVE_STATUS])
def test_a_blank_supersession_property_counts_as_missing(name: str) -> None:
    # Present-but-blank is the shape the fixture cannot show: it omits
    # both properties outright. RFC 5545 §3.1 folding makes an
    # all-whitespace value indistinguishable from an absent one to a
    # consumer, so the rule trims before deciding.
    cal = _calendar("supersession_missing_props")
    comp = cal.components[0]
    comp.set(Property(name=name, value="   "))
    hits = [
        d.path
        for d in validate(cal)
        if d.code == SUPERSESSION_MISSING_PROPS and d.path.endswith(f".{name}")
    ]
    assert len(hits) == 1


def test_diagnostic_carries_a_non_empty_message() -> None:
    # Messages are not contractual in their text, but a diagnostic that
    # carries none has dropped a field the dataclass declares.
    for stem in STEMS:
        for d in validate(_calendar(stem)):
            assert d.message, f"{stem}: {d.code} at {d.path} has no message"


def _corpus_calendars(family: str) -> list[tuple[str, Path]]:
    """Every ``.ics`` under one conformance-corpus family, sorted."""
    paths = sorted((CONFORMANCE_DIR / family).glob("*.ics"))
    return [(f"{family}/{p.name}", p) for p in paths]


CORPUS = _corpus_calendars("rfc5545") + _corpus_calendars("supersession")


def test_corpus_is_not_empty() -> None:
    assert CORPUS


#: Every spec/05 §8 value-domain code.
_VALUE_DOMAIN_CODES = [
    STATUS_NOT_IN_VOCABULARY,
    CLASS_NOT_IN_VOCABULARY,
    TRANSP_NOT_IN_VOCABULARY,
    INTEGER_OUT_OF_DOMAIN,
]


@pytest.mark.parametrize(("label", "path"), CORPUS, ids=[label for label, _ in CORPUS])
def test_corpus_is_clean_of_every_value_domain_code(label: str, path: Path) -> None:
    # Mirrors the Go corpus walk: every VCALENDAR fixture in the
    # conformance corpus carries only STATUS, CLASS and TRANSP values
    # inside their vocabularies and only canonical, in-range integers.
    # A hit here means the port's rule is wrong, not the fixture.
    cal = rfc5545.parse(path.read_bytes())
    hits = [(d.path, d.code) for d in validate(cal) if d.code in _VALUE_DOMAIN_CODES]
    assert hits == []


def test_a_journal_only_status_on_a_vevent_is_flagged() -> None:
    # The cross-type shape the rule exists for: DRAFT is legal
    # iCalendar text, and legal for a VJOURNAL, but not for a VEVENT.
    cal = _calendar("clean_vevent")
    cal.components[0].set(Property(name="STATUS", value="DRAFT"))
    assert STATUS_NOT_IN_VOCABULARY in [d.code for d in validate(cal)]


#: The three properties the integer-domain rule bounds.
_INTEGER_PROPS = ["PRIORITY", "PERCENT-COMPLETE", "SEQUENCE"]


def _with_value(stem: str, name: str, value: str) -> Calendar:
    """A clean fixture calendar carrying one extra property, rehashed.

    Restamping the hash keeps the integrity rule quiet, so the only
    diagnostic left to fire is the one ``name``'s value provokes. The
    value is set on the model directly, never parsed, so a padded or
    signed string reaches the rule byte-for-byte.
    """
    cal = _calendar(stem)
    comp = cal.components[0]
    comp.set(Property(name=name, value=value))
    hashing.set_x_vstar(comp)
    return cal


def _codes(cal: Calendar) -> list[str]:
    return [d.code for d in validate(cal)]


def test_class_outside_vocabulary_is_flagged_off_a_vevent() -> None:
    # Every CLASS fixture is a VEVENT. The rule is not type-gated: the
    # value is checked wherever the property appears, and component
    # scope is not diagnosed.
    cal = _with_value("clean_vtodo_completed", "CLASS", "X-SECRET")
    hits = [d for d in validate(cal) if d.code == CLASS_NOT_IN_VOCABULARY]
    assert [(d.path, d.severity) for d in hits] == [
        ("VCALENDAR.VTODO[uid=todo-clean-completed].CLASS", "error")
    ]


def test_transp_outside_vocabulary_is_flagged_off_a_vevent() -> None:
    # RFC 5545 admits TRANSP on a VEVENT only, but V* diagnoses no scope
    # rule for any property, so a VTODO carrying TRANSP gets the same
    # value check and nothing else.
    cal = _with_value("clean_vtodo_completed", "TRANSP", "BUSY")
    hits = [d for d in validate(cal) if d.code == TRANSP_NOT_IN_VOCABULARY]
    assert [(d.path, d.severity) for d in hits] == [
        ("VCALENDAR.VTODO[uid=todo-clean-completed].TRANSP", "error")
    ]
    assert validate(_with_value("clean_vtodo_completed", "TRANSP", "OPAQUE")) == []


@pytest.mark.parametrize("name", _INTEGER_PROPS)
@pytest.mark.parametrize("value", [" 3", "3 "], ids=["leading", "trailing"])
def test_whitespace_padded_integer_is_flagged(name: str, value: str) -> None:
    # No fixture can carry padding: the encoder and the parser both
    # strip it. Set on the model, the padded string reaches the rule as
    # is, and a canonical decimal has no whitespace (spec/05 §8).
    cal = _with_value("clean_vtodo_completed", name, value)
    hits = [d.path for d in validate(cal) if d.code == INTEGER_OUT_OF_DOMAIN]
    assert hits == [f"VCALENDAR.VTODO[uid=todo-clean-completed].{name}"]


@pytest.mark.parametrize("name", _INTEGER_PROPS)
@pytest.mark.parametrize("value", ["+3", "07"], ids=["signed", "leading_zero"])
def test_non_canonical_integer_is_flagged_when_in_range(name: str, value: str) -> None:
    # `int("+3")` and `int("07")` both succeed and land inside every
    # bound, so a rule that parsed first and looked at the form second
    # would pass both. The form is textual and decided before any
    # magnitude comparison.
    cal = _with_value("clean_vtodo_completed", name, value)
    assert INTEGER_OUT_OF_DOMAIN in _codes(cal)


def test_sequence_past_machine_range_is_clean() -> None:
    # The rule never converts the value to decide well-formedness: the
    # spec bounds SEQUENCE below, never above, so 2^64 is well-formed.
    cal = _with_value("clean_vtodo_completed", "SEQUENCE", "18446744073709551616")
    assert validate(cal) == []


#: ``"VS0"``, spelled so this file is not itself an offender.
_NEEDLE = "VS" + "0"

#: The package source tree under test.
_SRC = Path(__file__).resolve().parents[1] / "src" / "vstar"

#: The one directory licensed to carry code literals.
_GENERATED = _SRC / "_generated"


def _py_sources() -> list[Path]:
    """Every ``.py`` under ``src/vstar/``, sorted."""
    return sorted(_SRC.rglob("*.py"))


def test_generated_is_the_sole_home_of_the_code_literals() -> None:
    # The registry is authoritative: `spec/registry/` renders into
    # `src/vstar/_generated/`, and hand-written source must reference
    # the generated constant by name. A literal spelled out by hand is
    # a second source of truth that drifts silently when the registry
    # changes. `make registry-check` guards the generated file; this
    # guards everything else.
    pattern = re.compile(rf"{_NEEDLE}\d\d")
    offenders: list[str] = []
    for path in _py_sources():
        if _GENERATED in path.parents:
            continue
        lines = path.read_text(encoding="utf-8").splitlines()
        for n, line in enumerate(lines, start=1):
            if pattern.search(line):
                offenders.append(f"{path}:{n}: {line.strip()}")
    assert offenders == []


def test_the_literal_guard_actually_fires() -> None:
    # A grep that matches nothing anywhere proves nothing. The
    # generated module does carry the literals, so the pattern must
    # find them there.
    generated = (_GENERATED / "codes.py").read_text(encoding="utf-8")
    assert re.search(rf"{_NEEDLE}\d\d", generated) is not None
