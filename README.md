# V\*

**`hop-top-vstar`** on PyPI — canonical calendar and contact
interchange for agentic systems: RFC 5545 and RFC 6350, with
byte-stable output and a content hash.

[![PyPI](https://img.shields.io/pypi/v/hop-top-vstar?label=pypi)](https://pypi.org/project/hop-top-vstar/)
[![CI](https://img.shields.io/github/actions/workflow/status/hop-top/poly-vstar/ci-py.yml?branch=main&label=ci)](https://github.com/hop-top/poly-vstar/actions/workflows/ci-py.yml?query=branch%3Amain)
[![Types](https://img.shields.io/badge/types-py.typed-blue)](https://peps.python.org/pep-0561/)
[![Spec](https://img.shields.io/badge/spec-draft%20v0.1-blue)](https://github.com/hop-top/poly-vstar/tree/main/spec)
[![License](https://img.shields.io/badge/license-MIT-green)](https://github.com/hop-top/poly-vstar/blob/main/LICENSE)

> **Read-only mirror.** This package is developed in the polyglot
> monorepo [`hop-top/poly-vstar`](https://github.com/hop-top/poly-vstar)
> under `py/` and republished on each release to
> [`hop-top/vstar-py`](https://github.com/hop-top/vstar-py). Open issues
> and pull requests against the monorepo, not the mirror.

## What V\* is

V\* (pronounced "vee-star") represents agentic-system state — worlds,
missions, players, turns, observations, decisions — as **iCalendar
(RFC 5545) and vCard (RFC 6350) components**. Agent work that already
has time, identity and sequence semantics rides existing calendar,
scheduler and contact tooling instead of a bespoke protocol. This
distribution is the Python implementation; the Go reference and the
TypeScript, Rust and PHP ports produce the same bytes for the same
input.

Parse an `.ics` with a generic iCalendar library and you get a tree of
objects. Ask whether two of those trees mean the same thing and you are
on your own: the RFCs let one logical document be written many ways —
properties in any order, parameters in any order, datetimes in local or
UTC form, folding at any column — so `==` on serialized output is
meaningless and a `hashlib` digest over it is noise. V\* pins that down
with a **canonical form** — one byte sequence per logical content — and
an `X-VSTAR-HASH` over those bytes, so "did this change?" is `==` on
two strings rather than a tree walk. On top it adds what agent state
needs and a calendar library does not carry: a `validate` pass with
stable diagnostic codes, a bounded `rrule` evaluator, structural
`diff`, and append-only `supersession` for state transitions.

## Use this when

- You emit agent state — todos, journals, events, contacts — and want
  it to interoperate with calendars, schedulers or contact directories
  with no custom serialization.
- Consumers in other runtimes must agree with you byte-for-byte, and
  you want a hash that proves they did. This port is verified against
  the Go reference over the whole conformance corpus — not merely
  self-consistent. The quick start below prints the same
  `sha256:e551d177…` every implementation prints for that input. See
  [Conformance](#conformance).
- You need content addressing — deduplicate, cache or compare documents
  across services by a stable hash — or append-only history, where a
  status change is a new record that points at the old one rather than
  a mutation.

In a Python project specifically: the distribution has no runtime
dependency — the standard library only — and it ships `py.typed`,
checked under mypy `strict`, so its types hold in yours.

## Skip this if

You need a full calendaring client — timezone database management,
free/busy scheduling across attendees, CalDAV sync, or broad support
for RFC 5545's long tail. Use a general iCalendar library such as
`icalendar`. V\* deliberately implements a bounded subset chosen for
machine-generated state: its `RRULE` scope excludes `FREQ=SECONDLY`
and `RSCALE`, and its vCard codec accepts version 4.0 only. If you simply want to read someone else's calendar
file, this is more machinery than you need.

## Install

```sh
pip install hop-top-vstar
```

```sh
uv add hop-top-vstar
```

Requires **Python 3.11 or newer**. Pure standard library —
`dependencies = []`, nothing transitive to audit or pin. The
distribution is `hop-top-vstar`; the import name is `vstar`. Type hints
ship inline, the package is checked under mypy `strict`, and `py.typed`
advertises them, so mypy and pyright see them with no `types-*`
companion. Versions are prereleases (`1.0.0a*`, the PEP 440 form of
`1.0.0-alpha.*`); pin an exact version (`==1.0.0a0`) until 1.0.0.

## Usage

Parse, hash, canonicalize — the most common path:

```python
from vstar.canonical import calendar as canonical_calendar
from vstar.codec.rfc5545 import parse
from vstar.hashing import calendar as hash_calendar

ics = (
    "BEGIN:VCALENDAR\r\n"
    "VERSION:2.0\r\n"
    "PRODID:-//example//EN\r\n"
    "BEGIN:VTODO\r\n"
    "UID:todo-1\r\n"
    "DTSTAMP:20260101T000000Z\r\n"
    "DUE:20260102T000000Z\r\n"
    "SUMMARY:Ship the port\r\n"
    "END:VTODO\r\n"
    "END:VCALENDAR\r\n"
)

cal = parse(ics)

print(hash_calendar(cal))
# sha256:e551d17793785d5876edc6e33bca47f2aae73eb9feac49678d76159a78c91b18

# Canonical form is a BYTE sequence; compare it as one.
data = canonical_calendar(cal)
print(type(data).__name__, len(data))
# bytes 175
```

That `sha256:e551d177…` is the string every V\* implementation prints
for this input. The hash is the cross-language contract.

## API

Each area is its own subpackage, so an application imports only what it
uses. The root package re-exports the data model, the error classes,
the time helpers, and the `canonical`, `diff`, `duration`, `ext`,
`hashing`, `helpers` and `supersession` namespaces.

| Import | Area |
| --- | --- |
| `vstar` | Data model, error classes, time helpers, plus the namespaces below |
| `vstar.codec.rfc5545` | iCalendar parse and serialize |
| `vstar.codec.rfc6350` | vCard parse and serialize |
| `vstar.codec.stream` | One component at a time, from bytes, text or a file-like object |
| `vstar.canonical` | Canonical byte form |
| `vstar.hashing` | `X-VSTAR-HASH` compute and verify |
| `vstar.validate` | Diagnostics with stable codes |
| `vstar.rrule` | Recurrence parse and bounded expansion |
| `vstar.duration` | ISO 8601 durations and alarm triggers; `signed()` is a `timedelta` |
| `vstar.ext` | `X-*` extension namespaces |
| `vstar.diff` | Structural diff |
| `vstar.supersession` | Append-only state transitions |
| `vstar.helpers` | Convenience constructors and accessors |

### Validate

Diagnostics carry a stable `code` and a dotted `path`. Match on the
code; the message is prose and rewords between versions. The calendar
above has no `X-VSTAR-HASH` yet, which is exactly what `VS003` reports.

```python
from vstar.validate import severity_of, validate

for d in validate(cal):
    print(d.severity, d.code, d.path)
# error VS003 VCALENDAR.VTODO[uid=todo-1].X-VSTAR-HASH

print(severity_of("VS003"), severity_of("VS999"))
# error None
```

`severity_of` answers for any code in the catalog and `None` otherwise;
`Severity` is the literal `"error" | "warning"`, so it compares as a
plain string.

### Recurrence

Expansion is always bounded: `occurrences` takes a limit and reports
whether the series ended within it, so an unbounded rule cannot hang a
caller.

```python
from vstar import format_time, parse_time
from vstar.rrule import occurrences, parse_rrule

rule = parse_rrule("FREQ=DAILY;COUNT=3")
dtstart = parse_time("20260401T120000Z")

times, complete = occurrences(rule, dtstart, 10)
print([format_time(t) for t in times], complete)
# ['20260401T120000Z', '20260402T120000Z', '20260403T120000Z'] True
```

### Hashing and tamper detection

`set_x_vstar` stamps the hash onto a component; `verify_x_vstar`
recomputes it and reports whether the content still matches.

```python
from vstar import Property, parse_time
from vstar.helpers import new_todo, set_todo_status, todo_status
from vstar.hashing import set_x_vstar, verify_x_vstar
from vstar.types import TodoStatus

todo = new_todo("todo-9", parse_time("20260501T090000Z"))
set_todo_status(todo, TodoStatus.IN_PROCESS)
print(todo.type, todo.uid(), todo.get("DUE").value, todo_status(todo))
# VTODO todo-9 20260501T090000Z IN-PROCESS

set_x_vstar(todo)
ok, want, got = verify_x_vstar(todo)
print(ok)
# True

todo.set(Property(name="SUMMARY", value="edited"))
print(verify_x_vstar(todo)[0])
# False
```

### Diff

`of_calendar` pairs components across two calendars and reports the
property-level changes, with paths that locate each change site.

```python
from vstar.codec.rfc5545 import parse
from vstar.diff import of_calendar


def todo_cal(summary: str):
    return parse(
        "BEGIN:VCALENDAR\r\nVERSION:2.0\r\nPRODID:-//example//EN\r\n"
        "BEGIN:VTODO\r\nUID:todo-1\r\nDTSTAMP:20260101T000000Z\r\n"
        f"DUE:20260102T000000Z\r\nSUMMARY:{summary}\r\n"
        "END:VTODO\r\nEND:VCALENDAR\r\n"
    )


before = todo_cal("Ship the port")
after = todo_cal("Ship the Python port")

for d in of_calendar(before, after):
    print(d.path)
    for pd in d.properties:
        print(" ", pd.op, pd.property.name, pd.old.value, "->", pd.property.value)
# VCALENDAR.VTODO[uid=todo-1]
#   Changed SUMMARY Ship the port -> Ship the Python port
```

`pd.op` is a `DiffOp` enum member; it renders as `Changed` because
`__str__` carries the reference's display spelling. Compare against
`DiffOp.CHANGED`, not against the string.

### Streaming

The batch codecs hold a whole document in memory. `vstar.codec.stream`
reads one top-level component at a time from bytes, text, or any
readable stream, so a ledger larger than memory still moves through.
Exhaustion is `StopIteration`, never an error.

```python
import io

from vstar.codec.stream import VCalendarParser

ics = (
    "BEGIN:VCALENDAR\r\nVERSION:2.0\r\nPRODID:-//example//EN\r\n"
    "BEGIN:VTODO\r\nUID:todo-1\r\nDTSTAMP:20260101T000000Z\r\nEND:VTODO\r\n"
    "BEGIN:VTODO\r\nUID:todo-2\r\nDTSTAMP:20260101T000000Z\r\nEND:VTODO\r\n"
    "END:VCALENDAR\r\n"
)

with io.BytesIO(ics.encode()) as f:
    for comp in VCalendarParser(f):
        print(comp.type, comp.uid())
# VTODO todo-1
# VTODO todo-2
```

### Errors

Every failure raises a subclass of `VstarError`, one class per
sentinel, so the idiomatic `except` clause selects the failure. Each
instance also carries `sentinel` — the Go identifier, spelled
identically in every V\* implementation — for logging or dispatch
across language boundaries.

```python
from vstar import Malformed, VstarError
from vstar.codec.rfc5545 import parse

try:
    parse(b"BEGIN:VCALENDAR\r\nnot a content line\r\n")
except Malformed as e:
    print(e.sentinel)
    # ErrMalformed
except VstarError as e:
    if e.sentinel == "ErrUnclosedBlock":
        ...
```

## Conformance

This port is a **round-trip** implementation and self-certifies in
[`VSTAR-CONFORMANCE.md`](VSTAR-CONFORMANCE.md) — implementation class,
every deviation from the reference, and the gates that are green.

Its output is checked against the Go reference by the cross-language
parity harness: both emitters run the same corpus and must produce a
byte-identical document, so agreement is proven rather than assumed.
From the monorepo root:

```sh
make test-parity
```

## Develop

[uv](https://docs.astral.sh/uv/) drives the environment and syncs it on
first use; `uv.lock` is committed. From this directory:

```sh
uv run ruff check .
uv run ruff format --check .
uv run mypy
uv run pytest
uv build
```

ruff also formats the Python blocks in this README, so a snippet that
drifts from the formatter fails the lint gate. In the monorepo,
`make ci-py` runs the same sequence and `make ci` adds the parity gate.

`src/vstar/_generated/` is rendered from the spec registry by
`make registry-gen`. Never hand-edit it; `make registry-check` fails
on drift.

See [`CONTRIBUTING.md`](https://github.com/hop-top/poly-vstar/blob/main/CONTRIBUTING.md)
for repo-wide rules and
[`docs/dev/`](https://github.com/hop-top/poly-vstar/blob/main/docs/INDEX.md#for-developers)
for the development loop.

## Links

- [Specification](https://github.com/hop-top/poly-vstar/tree/main/spec) — normative text and the conformance corpus
- [How-tos](https://github.com/hop-top/poly-vstar/blob/main/docs/INDEX.md) — validate and hash, recurrence, implementing V\*
- [Diagnostic codes](https://github.com/hop-top/poly-vstar/blob/main/docs/validate-codes.md) — the `VS***` catalog
- [API mapping](https://github.com/hop-top/poly-vstar/blob/main/docs/dev/api-mapping.md) — every Go symbol and its Python spelling
- [Monorepo](https://github.com/hop-top/poly-vstar) — source of truth; [issues](https://github.com/hop-top/poly-vstar/issues) and pull requests go here

## License

MIT. See [`LICENSE`](https://github.com/hop-top/poly-vstar/blob/main/LICENSE)
at the monorepo root.
