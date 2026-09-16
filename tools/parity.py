#!/usr/bin/env python3
# SPDX-License-Identifier: MIT

"""The Python parity emitter for the cross-language parity harness.

It takes the ``spec/`` directory as its single argument, runs the V*
public API over every fixture in ``spec/v1.0/conformance/`` and
``spec/behavior/``, and prints ONE JSON document to stdout.
``tools/parity/parity.py`` diffs this document against the Go
reference's, key by key; any difference fails the run.

The normative description of the document -- every key, every value
shape, every ordering rule -- is ``tools/parity/README.md``. This
command implements that document, not the Go emitter's source.

Three rules shape every value:

* Nothing human-readable is emitted. Diagnostic messages and exception
  text reword between versions without the behavior changing. Codes,
  paths, severities, op kinds and failure-class tokens are the stable
  surface.
* A failure serializes as ``{"error": "<SentinelName>"}`` using the Go
  sentinel's identifier as the cross-language token. This port carries
  those identifiers natively on :attr:`vstar.VstarError.sentinel`, so
  classification is a lookup rather than a translation.
* Output is deterministic. ``json.dumps(sort_keys=True)`` sorts every
  object key, matching Go's ``encoding/json``; every list is built in
  an order the contract pins.

Usage::

    PYTHONPATH=py/src python3 py/tools/parity.py spec

Exits 0 having printed the document; exits 1 with a diagnostic on
stderr when a fixture cannot be read or a contract it depends on is
broken.
"""

from __future__ import annotations

import hashlib
import json
import sys
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any, NoReturn

import vstar
from vstar import (
    canonical,
    diff,
    duration,
    ext,
    hashing,
    helpers,
    rrule,
    supersession,
    validate,
)
from vstar.codec import rfc5545, rfc6350
from vstar.errors import VstarError
from vstar.types import Calendar, Card, Component, CompType, Param

# Fixture extensions, named once so the families read alike.
EXT_ICS = ".ics"
EXT_VCF = ".vcf"
EXT_RRULE = ".rrule"

# The escape hatch for a failure matching no class the family
# recognizes. It surfaces under a name no port implements -- a loud
# mismatch -- rather than silently under a wrong token.
CLASS_UNCLASSIFIED = "Unclassified"

# The general class every codec layer may wrap; always tried last.
CLASS_MALFORMED = "ErrMalformed"


def fail(message: str) -> NoReturn:
    """Abort with a diagnostic on stderr, mirroring the reference's exit 1."""
    print(f"parity: {message}", file=sys.stderr)
    raise SystemExit(1)


def classify(err: BaseException | None, table: Sequence[str]) -> str | None:
    """Classify a caught failure into its cross-language token.

    First-match over ``table``, which the family orders specific to
    general. The Go reference matches with ``errors.Is``, walking a wrap
    chain; this port raises a single :class:`VstarError` whose
    ``sentinel`` already names the class, so membership in the table is
    the whole test.

    A failure that is not a :class:`VstarError`, or whose sentinel the
    family does not list, reports ``None`` and the caller turns that
    into a diagnostic rather than an emitted token no port recognizes.
    """
    if not isinstance(err, VstarError):
        return None
    return err.sentinel if err.sentinel in table else None


def classify_or_unclassified(err: BaseException | None, table: Sequence[str]) -> str:
    """Classify a failure, falling back to :data:`CLASS_UNCLASSIFIED`.

    Used by the families whose contract names that token -- duration
    parsing and alarm resolution -- where an unrecognized class travels
    into the document instead of aborting the emitter.
    """
    token = classify(err, table)
    return token if token is not None else CLASS_UNCLASSIFIED


def each_fixture(
    directory: Path, suffix: str, fn: Callable[[Path, Path], None]
) -> None:
    """Call ``fn`` for every file of ``directory`` carrying ``suffix``.

    Entries come in sorted order, with the full path and the
    suffix-stripped stem. A missing directory is a silent no-op, so the
    emitter tolerates a corpus that has yet to grow a family.
    """
    if not directory.is_dir():
        return
    for path in sorted(directory.iterdir(), key=lambda p: p.name):
        if path.is_dir() or not path.name.endswith(suffix):
            continue
        fn(path, path.parent / path.name[: -len(suffix)])


def walk_files(root: Path) -> list[Path]:
    """Every file under ``root``, recursively, in a deterministic order.

    The rrule corpus is the one nested tree; sorting each directory's
    entries by name keeps the walk independent of the platform's
    directory order.
    """
    out: list[Path] = []
    if not root.is_dir():
        return out
    for entry in sorted(root.iterdir(), key=lambda p: p.name):
        if entry.is_dir():
            out.extend(walk_files(entry))
        else:
            out.append(entry)
    return out


def fixture_key(root: Path, stem: Path) -> str:
    """Render ``stem`` as a slash-separated path relative to ``root``.

    The document's key space is filesystem layout with the extension
    dropped, identical on every platform a port runs on.
    """
    return stem.relative_to(root).as_posix()


def record(out: dict[str, Any], root: Path, stem: Path, value: Any) -> None:
    """Key ``value`` by ``stem`` relative to ``root``, refusing a collision.

    Two fixtures colliding on one key would silently drop a case from
    the document and shrink the harness' coverage without failing it.
    """
    key = fixture_key(root, stem)
    if key in out:
        fail(f"duplicate fixture key {key!r}")
    out[key] = value


def read_bytes(path: Path) -> bytes:
    """Read a fixture as raw bytes."""
    try:
        return path.read_bytes()
    except OSError as exc:
        fail(f"read {path}: {exc}")


def read_text(path: Path) -> str:
    """Read a fixture as UTF-8 text."""
    return read_bytes(path).decode("utf-8")


def read_json(path: Path) -> Any:
    """Read and parse a JSON sidecar."""
    try:
        return json.loads(read_text(path))
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        fail(f"parse {path}: {exc}")


def read_calendar(path: Path) -> Calendar:
    """Parse an ``.ics`` fixture, failing the emitter on error."""
    try:
        return rfc5545.parse(read_bytes(path))
    except VstarError as exc:
        fail(f"parse {path}: {exc}")


# --- conformance ----------------------------------------------------

# The vocabulary a `malformed/*` fixture may produce, most specific
# first. The emitter reports which one the fixture actually produced;
# this list only bounds what behavior is recognized.
MALFORMED_CLASSES = (
    "ErrUnsupportedVersion",
    "ErrUnclosedBlock",
    "ErrMissingUID",
    CLASS_MALFORMED,
)

# The conformance subdirectories whose `.ics` files parse into a Calendar.
CALENDAR_DIRS = ("rfc5545", "supersession")


def crlf_to_lf(data: bytes) -> bytes:
    """Replace every CRLF pair in ``data`` with a single LF."""
    return data.replace(b"\r\n", b"\n")


def canonical_digest(data: bytes) -> str:
    """Hash canonical bytes after folding CRLF to LF.

    The canonical form per spec/03 is CRLF, but the corpus stores it LF
    and every port reads the same LF file. Digesting the LF form keeps
    line-ending handling from producing false mismatches between ports.
    """
    return hashlib.sha256(crlf_to_lf(data)).hexdigest()


def check_hash_sibling(path: Path, suffix: str, got: str) -> None:
    """Compare a computed hash against the committed ``<stem>.hash`` sibling.

    This self-check is what keeps a port from emitting a hash that is
    merely self-consistent: the corpus carries an independent
    expectation for this one family, and disagreeing with it is a broken
    port rather than a parity mismatch to report downstream.
    """
    sibling = path.parent / (path.name[: -len(suffix)] + ".hash")
    want = read_text(sibling).rstrip("\r\n")
    if got != want:
        fail(f"{sibling}: hash {got} does not match committed {want}")


def calendar_entry(path: Path) -> dict[str, str]:
    """Parse an ``.ics`` fixture, canonicalize, hash, and self-check."""
    try:
        cal = rfc5545.parse(read_bytes(path))
    except VstarError as exc:
        fail(f"parse {path}: {exc}")
    entry = {
        "hash": hashing.calendar(cal),
        "canonical_sha256": canonical_digest(canonical.calendar(cal)),
    }
    check_hash_sibling(path, EXT_ICS, entry["hash"])
    return entry


def card_entry(path: Path) -> dict[str, str]:
    """:func:`calendar_entry` for a ``.vcf`` fixture.

    The corpus holds exactly one card per file; more would mean the
    fixture changed shape under the emitter and the contract no longer
    says which card the hash belongs to.
    """
    try:
        cards = rfc6350.parse(read_bytes(path))
    except VstarError as exc:
        fail(f"parse {path}: {exc}")
    if len(cards) != 1:
        fail(f"{path}: expected exactly one card, got {len(cards)}")
    entry = {
        "hash": hashing.card(cards[0]),
        "canonical_sha256": canonical_digest(canonical.card(cards[0])),
    }
    check_hash_sibling(path, EXT_VCF, entry["hash"])
    return entry


def malformed_token(path: Path, suffix: str) -> str:
    """Run a malformed fixture through the codec and report its token.

    Most fixtures fail at parse time. ``ErrMissingUID`` is encoder-only
    -- the rfc6350 parser accepts a UID-less VCARD and the
    encoder refuses it -- so a fixture that parses is re-encoded and the
    encode failure classified instead. A fixture where both stages
    succeed is a fault.
    """
    data = read_bytes(path)
    parse_err: BaseException | None = None
    encode_err: BaseException | None = None
    parsed = False

    if suffix == EXT_ICS:
        try:
            rfc5545.parse(data)
            parsed = True
        except VstarError as exc:
            parse_err = exc
    else:
        cards: list[Card] | None = None
        try:
            cards = rfc6350.parse(data)
            parsed = True
        except VstarError as exc:
            parse_err = exc
        if cards is not None:
            if not cards:
                fail(f"{path}: parse returned no cards and no error")
            try:
                for card in cards:
                    rfc6350.encode(card)
            except VstarError as exc:
                encode_err = exc
                parsed = False

    from_parse = classify(parse_err, MALFORMED_CLASSES)
    if from_parse is not None:
        return from_parse
    from_encode = classify(encode_err, MALFORMED_CLASSES)
    if from_encode is not None:
        return from_encode
    if parsed:
        fail(f"{path}: expected a failure, parse and encode both succeeded")
    fail(f"{path}: failure matches no known sentinel: {parse_err or encode_err}")


def emit_conformance(corpus: Path) -> dict[str, Any]:
    """Walk the conformance corpus, keying every fixture by its stem.

    ``time/`` fixtures are VTIMEZONE registries the ``time`` family
    consumes and carry no ``.canonical``/``.hash`` siblings, so they are
    not part of this family; ``fuzz-seed/`` is fuzz-target input.
    """
    out: dict[str, Any] = {}

    for name in CALENDAR_DIRS:
        each_fixture(
            corpus / name,
            EXT_ICS,
            lambda path, stem: record(out, corpus, stem, calendar_entry(path)),
        )
    each_fixture(
        corpus / "rfc6350",
        EXT_VCF,
        lambda path, stem: record(out, corpus, stem, card_entry(path)),
    )
    for suffix in (EXT_ICS, EXT_VCF):
        each_fixture(
            corpus / "malformed",
            suffix,
            lambda path, stem, s=suffix: record(
                out, corpus, stem, {"error": malformed_token(path, s)}
            ),
        )
    return out


# --- rrule ----------------------------------------------------------

# The failure vocabulary the rrule family reports, most specific first.
# Every token is a class named by spec/05 "Failure classes".
RRULE_CLASSES = (
    "ErrUnsupportedRRule",
    "ErrIterationCap",
    "ErrUnboundedExpansion",
    CLASS_MALFORMED,
)


def exists(path: Path) -> bool:
    """Whether ``path`` exists, used to test for a sidecar."""
    return path.exists()


def read_sidecar(path: Path) -> dict[str, Any] | None:
    """Read a sidecar's input fields, reporting ``None`` when absent."""
    if not exists(path):
        return None
    return read_json(path)


def parse_stamp(path: Path, field: str, value: Any) -> Any:
    """Read an RFC 5545 form #2 sidecar input value."""
    parsed = vstar.parse_time(value) if isinstance(value, str) else None
    if parsed is None:
        fail(f"{path}: bad {field} {json.dumps(value if value is not None else '')}")
    return parsed


def failure_token(path: Path, err: BaseException | None, succeeded: bool) -> str:
    """Classify a failure into its rrule class token.

    Refuses to emit anything for a success or an unrecognized class: an
    unrecognized class must fail the emitter rather than travel into the
    document as a token no port implements.
    """
    if succeeded:
        fail(f"{path}: expected a failure, the call succeeded")
    token = classify(err, RRULE_CLASSES)
    if token is None:
        fail(f"{path}: failure matches no known class: {err}")
    return token


def format_stamps(times: Sequence[Any]) -> list[str]:
    """Render occurrences as RFC 5545 form #2."""
    return [vstar.format_time(t) for t in times]


def add_bounded(
    entry: dict[str, Any],
    path: Path,
    key: str,
    run: Callable[[], tuple[list[Any], bool]],
) -> None:
    """Record a bounded-expansion outcome on ``entry``.

    The occurrence list lands under ``key`` plus a ``<key>_complete``
    flag on success, or ``<key>_error`` naming the failure class.

    Every key is flat on the entry rather than nested under one
    sub-object, so which contracts a fixture pins is readable off the
    entry's key set.
    """
    try:
        times, complete = run()
    except VstarError as exc:
        entry[f"{key}_error"] = failure_token(path, exc, False)
        return
    entry[key] = format_stamps(times)
    entry[f"{key}_complete"] = complete


def add_formatted(stem: Path, rule: rrule.Rule, entry: dict[str, Any]) -> None:
    """Report ``str(rule)`` when a ``<stem>.formatted`` sidecar exists."""
    if not exists(stem.parent / (stem.name + ".formatted")):
        return
    entry["formatted"] = str(rule)


def add_next(stem: Path, rule: rrule.Rule, entry: dict[str, Any]) -> None:
    """Walk ``next_occurrence`` the way the sidecar's expected list is shaped.

    One step per entry, each feeding its result back as the next
    ``after``. The emitted list is what this port yielded.

    One extra step runs past the end, and its outcome is the terminal
    contract: ``next_error`` names the class the series failed with, or
    ``next_complete`` states whether it terminated. Emitting that step
    unconditionally means a port cannot pass by stopping early -- a
    series that should terminate and one that should raise
    ``ErrIterationCap`` differ in the document.
    """
    path = stem.parent / (stem.name + ".next.json")
    spec = read_sidecar(path)
    if spec is None:
        return
    dtstart = parse_stamp(path, "dtstart", spec.get("dtstart"))
    after = parse_stamp(path, "after", spec.get("after"))

    stamps: list[str] = []
    for index in range(len(spec.get("expected") or [])):
        try:
            got = rrule.next_occurrence(rule, dtstart, after)
        except VstarError as exc:
            fail(f"{path}: next_occurrence step {index} failed: {exc}")
        if got is None:
            fail(f"{path}: next_occurrence step {index} terminated early")
        stamps.append(vstar.format_time(got))
        after = got
    entry["next"] = stamps

    try:
        got = rrule.next_occurrence(rule, dtstart, after)
    except VstarError as exc:
        entry["next_error"] = failure_token(path, exc, False)
    else:
        entry["next_complete"] = got is None


def add_expand(stem: Path, rule: rrule.Rule, entry: dict[str, Any]) -> None:
    """Report bounded expansion over the ``.expand.json`` sidecar's limit."""
    path = stem.parent / (stem.name + ".expand.json")
    spec = read_sidecar(path)
    if spec is None:
        return
    dtstart = parse_stamp(path, "dtstart", spec.get("dtstart"))
    limit = int(spec.get("limit") or 0)
    add_bounded(entry, path, "expand", lambda: rrule.occurrences(rule, dtstart, limit))


def add_between(stem: Path, rule: rrule.Rule, entry: dict[str, Any]) -> None:
    """Report ``between`` over the sidecar's half-open window.

    ``between`` has no completeness notion -- the window bounds the
    answer -- so the success shape is the list alone.
    """
    path = stem.parent / (stem.name + ".between.json")
    spec = read_sidecar(path)
    if spec is None:
        return
    dtstart = parse_stamp(path, "dtstart", spec.get("dtstart"))
    start = parse_stamp(path, "start", spec.get("start"))
    end = parse_stamp(path, "end", spec.get("end"))
    try:
        entry["between"] = format_stamps(rrule.between(rule, dtstart, start, end))
    except VstarError as exc:
        entry["between_error"] = failure_token(path, exc, False)


def rule_entry(path: Path) -> dict[str, Any]:
    """Evaluate one ``<stem>.rrule`` fixture against every sidecar it has.

    A ``.expect.json`` sidecar means the rule must be rejected: the
    emitter reports the class ``validate_rrule`` produced and stops,
    since no other contract applies to a rule that does not parse.
    """
    value = read_text(path).rstrip("\r\n")
    stem = path.parent / path.name[: -len(EXT_RRULE)]

    if exists(stem.parent / (stem.name + ".expect.json")):
        err: BaseException | None = None
        succeeded = False
        try:
            rrule.validate_rrule(value)
            succeeded = True
        except VstarError as exc:
            err = exc
        return {"error": failure_token(path, err, succeeded)}

    try:
        rule = rrule.parse_rrule(value)
    except VstarError as exc:
        fail(f"{path}: parse_rrule failed: {exc}")

    entry: dict[str, Any] = {"parsed": True}
    add_formatted(stem, rule, entry)
    add_next(stem, rule, entry)
    add_expand(stem, rule, entry)
    add_between(stem, rule, entry)
    return entry


def set_entry(path: Path) -> dict[str, Any]:
    """Evaluate one ``<stem>.ics`` recurrence-set fixture.

    The calendar's first component goes through
    ``rule_set_from_component``, then either ``.expect.json`` pins a
    rejection or ``.occurrences.json`` pins the bounded expansion.
    """
    stem = path.parent / path.name[: -len(EXT_ICS)]

    rule_set: rrule.RuleSet | None = None
    set_err: BaseException | None = None
    try:
        cal = rfc5545.parse(read_bytes(path))
        if not cal.components:
            raise vstar.Malformed("calendar has no components")
        rule_set = rrule.rule_set_from_component(cal.components[0])
    except VstarError as exc:
        set_err = exc

    if exists(stem.parent / (stem.name + ".expect.json")):
        return {"error": failure_token(path, set_err, rule_set is not None)}
    if rule_set is None:
        fail(f"{path}: {set_err}")

    entry: dict[str, Any] = {"parsed": True}
    occ_path = stem.parent / (stem.name + ".occurrences.json")
    spec = read_sidecar(occ_path)
    if spec is None:
        return entry
    limit = int(spec.get("limit") or 0)
    add_bounded(entry, occ_path, "occurrences", lambda: rule_set.occurrences(limit))
    return entry


def emit_rrule(root: Path) -> dict[str, Any]:
    """Walk the rrule corpus, keyed by stem relative to the conformance root."""
    corpus = root.parent
    out: dict[str, Any] = {}
    for path in walk_files(root):
        if path.name.endswith(EXT_RRULE):
            stem = path.parent / path.name[: -len(EXT_RRULE)]
            record(out, corpus, stem, rule_entry(path))
        elif path.name.endswith(EXT_ICS):
            stem = path.parent / path.name[: -len(EXT_ICS)]
            record(out, corpus, stem, set_entry(path))
    return out


# --- validate -------------------------------------------------------


def emit_validate(directory: Path) -> dict[str, Any]:
    """Run ``validate`` over every ``<name>.ics``, sorted by (path, code).

    The sort is the contract, not any port's emission order: checks run
    in an order that is an implementation detail. Sorting both sides
    makes the comparison about which diagnostics were raised. The
    message is deliberately absent -- it is prose that rewords between
    versions without the behavior changing.
    """
    root = directory.parent
    out: dict[str, Any] = {}

    def visit(path: Path, stem: Path) -> None:
        entries = [
            {"code": d.code, "severity": d.severity, "path": d.path}
            for d in validate.validate(read_calendar(path))
        ]
        entries.sort(key=lambda e: (e["path"], e["code"]))
        record(out, root, stem, entries)

    each_fixture(directory, EXT_ICS, visit)
    return out


# --- diff -----------------------------------------------------------

# The lowercase wire tokens the behavior fixtures record, held apart
# from DiffOp's capitalized display spellings.
OP_TOKENS = {
    diff.DiffOp.ADDED: "add",
    diff.DiffOp.REMOVED: "remove",
    diff.DiffOp.CHANGED: "change",
}


def param_entries(params: Sequence[Param]) -> list[dict[str, str]]:
    """Project a property's parameters onto the emitted shape."""
    return [{"name": p.name, "value": p.value} for p in params]


def uid_from_path(path: str) -> str:
    """Lift the uid out of a rendered path such as ``VCALENDAR.VTODO[uid=t]``.

    Empty for a positional path (``VCALENDAR.VALARM[#0]``), which has no
    UID to key on.
    """
    marker = "[uid="
    index = path.rfind(marker)
    if index < 0 or not path.endswith("]"):
        return ""
    return path[index + len(marker) : -1]


def property_name(pd: diff.PropertyDiff) -> str:
    """Report the name the op is about, from whichever side carries it."""
    return pd.property.name if pd.property.name != "" else pd.old.name


def op_entries(pds: Sequence[diff.PropertyDiff]) -> list[dict[str, Any]]:
    """Project property diffs onto the emitted op shape.

    ``before`` is null on an add, ``after`` null on a remove. Params
    travel apart from the value because a parameter-only change is a
    ``change`` op whose values are equal and whose parameter lists
    differ.
    """
    out: list[dict[str, Any]] = []
    for pd in pds:
        token = OP_TOKENS[pd.op]
        if pd.op is diff.DiffOp.ADDED:
            before, after = None, pd.property.value
            before_params, after_params = [], param_entries(pd.property.params)
        elif pd.op is diff.DiffOp.REMOVED:
            before, after = pd.property.value, None
            before_params, after_params = param_entries(pd.property.params), []
        else:
            before, after = pd.old.value, pd.property.value
            before_params = param_entries(pd.old.params)
            after_params = param_entries(pd.property.params)
        out.append(
            {
                "op": token,
                "property": property_name(pd),
                "before": before,
                "after": after,
                "before_params": before_params,
                "after_params": after_params,
            }
        )
    return out


def component_diff_entries(ds: Sequence[diff.ComponentDiff]) -> list[dict[str, Any]]:
    """Project component diffs, dropping sub-diffs that record no change.

    ``of_calendar`` filters these at the top level but carries them
    nested; the document reports only real changes.
    """
    return [
        {
            "uid": uid_from_path(d.path),
            "path": d.path,
            "ops": op_entries(d.properties),
            "subs": component_diff_entries(
                [s for s in d.sub_diffs if not s.is_empty()]
            ),
        }
        for d in ds
    ]


def emit_diff(directory: Path) -> dict[str, Any]:
    """Run ``of_calendar`` over every ``<name>.a.ics`` / ``<name>.b.ics`` pair.

    No sorting happens here. ``of_calendar`` emits components in pairing
    order and properties sorted by name case-insensitively, and that
    ordering is the contract a port reproduces -- sorting it again would
    hide an ordering divergence rather than catch it.
    """
    root = directory.parent
    out: dict[str, Any] = {}

    def visit(path: Path, stem: Path) -> None:
        a = read_calendar(path)
        b = read_calendar(stem.parent / (stem.name + ".b" + EXT_ICS))
        record(out, root, stem, component_diff_entries(diff.of_calendar(a, b)))

    each_fixture(directory, ".a" + EXT_ICS, visit)
    return out


# --- supersession ---------------------------------------------------


def emit_supersession(conformance: Path, directory: Path) -> dict[str, Any]:
    """Project the effective status each supersession ledger imposes.

    Keyed by component UID. The inputs are the conformance corpus'
    supersession fixtures; the behavior tree holds only the
    ``<name>.effective.json`` sidecars, so the sidecar names which
    ``.ics`` to load. A UID absent from the map is not superseded --
    supersession is a projection query, not a validator.
    """
    root = directory.parent
    inputs = conformance / "supersession"
    out: dict[str, Any] = {}

    def visit(_path: Path, stem: Path) -> None:
        cal = read_calendar(inputs / (stem.name + EXT_ICS))
        effective: dict[str, str] = {}
        for component in cal.components:
            status = supersession.superseded(component, cal.components)
            if status is None:
                continue
            uid = component.uid()
            if uid == "":
                fail(f"{stem.name}: superseded component has no UID")
            effective[uid] = status
        record(out, root, stem, effective)

    each_fixture(directory, ".effective.json", visit)
    return out


# --- duration -------------------------------------------------------

# The failure vocabulary alarm resolution reports, most specific first.
# An implementation that also wraps ErrMalformed around one of these
# must still report the specific one, which first-match ordering gives.
TRIGGER_CLASSES = ("ErrNoTrigger", "ErrNoAnchor", CLASS_MALFORMED)

# The vocabulary `duration.parse` failures report. Every failure is
# ErrMalformed today; classifying rather than assuming means a class the
# port grows surfaces as Unclassified instead of traveling as a wrong
# token.
DURATION_CLASSES = (CLASS_MALFORMED,)

# Seconds per unit, for projecting a VDuration onto the one
# representation every target language has.
_SECONDS_PER_MINUTE = 60
_SECONDS_PER_HOUR = 3600
_SECONDS_PER_DAY = 86400
_SECONDS_PER_WEEK = 604800


def parse_duration(value: str) -> dict[str, Any]:
    """Report what ``duration.parse`` makes of one value.

    The signed second count and sign flag, or the failure class.
    ``seconds`` is the whole duration as a signed second count;
    ``negative`` is kept separate because a zero-length duration written
    with a leading sign cannot be distinguished by ``seconds`` alone.
    """
    try:
        d = duration.parse(value)
    except VstarError as exc:
        return {
            "value": value,
            "seconds": None,
            "negative": None,
            "error": classify_or_unclassified(exc, DURATION_CLASSES),
        }
    return {
        "value": value,
        "seconds": int(d.signed().total_seconds()),
        "negative": d.is_negative(),
        "error": "",
    }


def alarm_entries(cal: Calendar) -> list[dict[str, str]]:
    """Resolve every VALARM in the calendar, in document order.

    Parent components in calendar order, VALARMs in the order they
    appear inside their parent.
    """
    out: list[dict[str, str]] = []
    for parent in cal.components:
        for alarm in parent.sub:
            if alarm.type != CompType.ALARM:
                continue
            out.append(resolve_alarm(alarm, parent, cal))
    return out


def resolve_alarm(alarm: Component, parent: Component, cal: Calendar) -> dict[str, str]:
    """Report when one VALARM fires, or the class its resolution failed with."""
    alarm_uid = alarm.uid()
    try:
        fires_at = helpers.alarm_fires_at(alarm, parent, cal)
    except VstarError as exc:
        return {
            "alarm_uid": alarm_uid,
            "fires_at": "",
            "error": classify_or_unclassified(exc, TRIGGER_CLASSES),
        }
    return {
        "alarm_uid": alarm_uid,
        "fires_at": vstar.format_time(fires_at),
        "error": "",
    }


def emit_duration(directory: Path) -> dict[str, Any]:
    """Cover both duration families.

    The flat parse table at ``duration/parse.json``, and one
    alarm-resolution list per ``<name>.ics``. The parse table's inputs
    come from the committed fixture's ``value`` column rather than a
    list hard-coded here, so a value added to the corpus reaches every
    port without an emitter edit.
    """
    root = directory.parent
    out: dict[str, Any] = {}

    rows = read_json(directory / "parse.json")
    out["duration/parse"] = [parse_duration(row["value"]) for row in rows]

    each_fixture(
        directory,
        EXT_ICS,
        lambda path, stem: record(out, root, stem, alarm_entries(read_calendar(path))),
    )
    return out


# --- ext ------------------------------------------------------------


def emit_ext(directory: Path) -> dict[str, Any]:
    """Classify every name in the committed ``ext/scopes.json``.

    In the order the file lists them: it is a flat table, not a set, so
    order is part of what a port reproduces. ``scope`` is the lowercase
    wire token and ``system`` the owning system's slug -- null for every
    scope but ``"system"``, since only a system-scoped name has an
    owner.
    """
    rows = read_json(directory / "scopes.json")
    return {
        "ext/scopes": [
            {
                "name": row["name"],
                "scope": ext.scope_of(row["name"]).value,
                "system": ext.system_name(row["name"]),
            }
            for row in rows
        ]
    }


# --- time -----------------------------------------------------------


def emit_time(conformance: Path, directory: Path) -> dict[str, Any]:
    """Resolve every (calendar, tzid, value) triple in ``time/tzid.json``.

    In file order. ``calendar`` names a conformance fixture supplying the
    VTIMEZONE registry; each registry is parsed once and reused, so a
    fixture's cost does not grow with the number of rows citing it.
    ``utc`` is null for every rejection: the API reports an absent value,
    not an error, so there is no failure class to name here.
    """
    rows = read_json(directory / "tzid.json")

    registries: dict[str, Calendar] = {}
    for row in rows:
        name = row["calendar"]
        if name not in registries:
            registries[name] = read_calendar(conformance / "time" / (name + EXT_ICS))

    out: list[dict[str, Any]] = []
    for row in rows:
        got = vstar.parse_time_with_tzid(
            row["value"], row["tzid"], registries[row["calendar"]]
        )
        out.append(
            {
                "calendar": row["calendar"],
                "tzid": row["tzid"],
                "value": row["value"],
                "utc": None if got is None else vstar.format_time(got),
            }
        )
    return {"time/tzid": out}


# --- main -----------------------------------------------------------


def main(argv: Sequence[str]) -> None:
    if len(argv) != 1:
        fail("usage: parity <spec-dir>")
    spec = Path(argv[0]).resolve()

    conformance = spec / "v1.0" / "conformance"
    behavior = spec / "behavior"
    for directory in (conformance, behavior):
        if not directory.is_dir():
            fail(f"not a directory: {directory}")

    # The eight top-level keys, in the order the contract lists them.
    # Their order in the emitted text does not matter to the harness,
    # which compares parsed documents, but keeping it matches the
    # reference's own struct order and makes the two files diffable by
    # eye.
    document = {
        "conformance": emit_conformance(conformance),
        "rrule": emit_rrule(conformance / "rrule"),
        "validate": emit_validate(behavior / "validate"),
        "diff": emit_diff(behavior / "diff"),
        "supersession": emit_supersession(conformance, behavior / "supersession"),
        "duration": emit_duration(behavior / "duration"),
        "ext": emit_ext(behavior / "ext"),
        "time": emit_time(conformance, behavior / "time"),
    }

    # sort_keys matches Go's encoding/json, which sorts map keys. Only
    # objects are reordered; every list is built in an order the
    # contract pins.
    sys.stdout.write(json.dumps(document, indent=2, sort_keys=True) + "\n")


if __name__ == "__main__":
    main(sys.argv[1:])
