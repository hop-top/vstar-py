# V* conformance — `hop-top-vstar` (Python)

This is the self-certification
[spec/v0.1/05-conformance.md](https://github.com/hop-top/poly-vstar/blob/main/spec/v0.1/05-conformance.md#self-certification)
asks every implementation to publish. Until a formal conformance suite
exists (planned for v0.2) it is the honor-system substitute, and for a
port most of it is a statement of which gates are green.

## Spec revision

Targets spec revision `93afaaf2546a154c3672611f00794c5969cca9a9`.

The spec is authored in the same repository as this port, so the
revision is a commit of that repository rather than an external pin. A
change to `spec/` that this port has not caught up with fails
`make test-parity` before it can go unnoticed.

## Implementation class

**Round-trip.**

Documents this implementation emits re-parse and re-emit
byte-identically. Both directions are exercised: `tests/test_rfc5545.py`
and `tests/test_rfc6350.py` round-trip every conformance fixture, and
`tests/test_reference_parity.py` pins the encoder's byte length and an
FNV-1a fingerprint of its output against values captured from the Go
reference — so "byte-identical" means identical to the reference, not
merely stable under this port's own round trip.

## Conformance criteria

Criteria are numbered per
[spec/v0.1/05-conformance.md](https://github.com/hop-top/poly-vstar/blob/main/spec/v0.1/05-conformance.md).

| # | Criterion | Status |
|---|---|---|
| 1 | Emits valid RFC 5545 / RFC 6350 | met |
| 2 | Emits required common properties | met |
| 3 | Honors canonicalization rules | met |
| 4 | Uses correct component types | met |
| 5 | Respects the extension namespace | met |
| 6 | Is append-only (supersession) | met |
| 7 | Keeps duration values well-formed | met |
| 8 | Keeps enumerated and integer values in their RFC domains | met |

Criterion 1 is "met" in the sense the spec defines it — output passes a
generic iCalendar/vCard validator — and is evidenced by the
byte-identical agreement with the Go reference recorded below, not by a
run against a third-party validator. No independent validator has been
run against this port's output.

## Failure classes

All twelve sentinels are surfaced and distinguishable: **yes**.

Each is its own `VstarError` subclass, so the idiomatic Python
`except` clause selects one:

```python
try:
    parse(data)
except UnclosedBlock:
    ...
```

The Go identifier is recoverable from any caught failure as the
`sentinel` attribute, which every subclass sets verbatim:

```python
except VstarError as e:
    if e.sentinel == "ErrIterationCap":
        ...
```

Class names drop the `Err` prefix — `Malformed`, not `ErrMalformed` —
because `raise MalformedError` is not the Python idiom and the class is
already an exception. The `sentinel` string keeps the Go spelling
exactly, so the cross-language contract is unaffected by the local
naming. `docs/dev/api-mapping.md` fixes those class names across the
ports, so a port-local respelling is a documented divergence rather
than a silent one.

## Corpus gates

Every gate below runs in CI (`ci-py.yml` for the port's own suite,
`ci-parity.yml` for the cross-language document).

| Gate | Status |
|---|---|
| conformance round-trip (rfc5545, rfc6350) | green — `tests/test_rfc5545.py`, `tests/test_rfc6350.py` |
| reference byte parity (encoder) | green — `tests/test_reference_parity.py` |
| malformed sentinels | green — `tests/test_malformed.py` |
| canonical bytes | green — `tests/test_canonical.py` |
| hash values | green — `tests/test_hashing.py`, plus the emitter's own self-check against every committed `.hash` sibling |
| behavior/time, behavior/duration | green — `tests/test_time.py`, `tests/test_duration.py` |
| rrule sidecars | green — `tests/test_rrule.py` |
| behavior/validate | green — `tests/test_validate.py` |
| behavior/{ext,supersession,diff} | green — `tests/test_ext.py`, `tests/test_supersession.py`, `tests/test_diff.py` |
| fuzz seeds | green — `tests/test_fuzz_seed.py` |
| parity emitter | green — `make test-parity` reports `parity: ok go php py rs ts` plus the case count it measured; see [tools/parity/README.md](https://github.com/hop-top/poly-vstar/blob/main/tools/parity/README.md) |

The parity gate is the strongest of these. `tools/parity.py` and the Go
reference emitter independently run their own implementations over the
shared corpus and print one JSON document each; the harness fails on
any difference. The two documents are identical across all eight
families, so this port's agreement with the reference is measured
rather than asserted.

## Known deviations

Three, all deliberate, none affecting emitted bytes.

1. **A subclass per sentinel, with the `Err` prefix dropped.** Where
   the Go reference exposes twelve `error` values and the TypeScript
   port a single class carrying a `code` string, this port raises
   `Malformed`, `UnclosedBlock` and ten siblings, all deriving from
   `VstarError`. Python's `except` clause dispatches on class, so a
   shared class would force every caller to catch broadly and re-test a
   string. The `sentinel` attribute preserves the Go identifier
   verbatim on every instance, so nothing about the cross-language
   contract is lost.

2. **Instants are timezone-aware `datetime`, not a numeric epoch.** The
   model represents an absolute instant as a `datetime` carrying an
   explicit UTC `tzinfo`, where the TypeScript port uses a millisecond
   number. Naive datetimes are rejected at the boundary rather than
   silently assumed to be UTC, which is the failure mode that makes
   timezone bugs expensive. The consequence for a caller is that
   instants compare and subtract with the usual `datetime` operators
   and are rendered with `format_time`. Sub-second precision is not
   representable on the wire — RFC 5545 timestamps are
   second-resolution — so nothing is lost there.

3. **`VDuration.signed()` returns a `timedelta`, where the Go
   reference returns `time.Duration` (nanoseconds) and the TypeScript
   port a millisecond number.** A `timedelta` is the representation
   Python callers already compose with `datetime`, and returning an
   integer count would force every caller to convert. All three reduce
   to the same second count, which is the unit the cross-language
   corpus compares, so this is a surface difference rather than a
   behavioral one.

No deviation is known in canonical form, hashing, validation codes,
diff ordering, supersession projection, recurrence evaluation, or
extension scoping — the parity gate would fail on any of them.

## Test artifacts

The corpus run is the artifact. Rather than pin a handful of golden
documents here, where they would drift from the corpus they were copied
out of, this port is certified by the gates above over the whole of
`spec/v0.1/conformance/` and `spec/behavior/`:

- **Hashes** — the parity emitter recomputes the content hash of every
  parseable fixture and compares it against that fixture's committed
  `.hash` sibling, aborting on any mismatch. The corpus is therefore an
  independent expectation this port is checked against, not a record of
  what it happened to produce.
- **Canonical bytes** — `tests/test_canonical.py` compares this port's
  canonical output against each fixture's committed `.canonical`
  sibling as bytes.
- **Cross-language document** — `make test-parity` emits one JSON
  document per implementation and requires them to be identical. At the
  spec revision above this port's emitter matches the Go reference over
  every case the run counts. The count is printed by `make test-parity`
  rather than recorded here, so it cannot drift from the corpus.

To reproduce all three from a checkout:

```sh
make test-py
make test-parity
```
