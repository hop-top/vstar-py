# SPDX-License-Identifier: MIT

"""The twelve V* failure classes.

V* names twelve failure classes. Every port surfaces all twelve, makes
them programmatically distinguishable, and uses the Go sentinel name as
the stable identifier. That identifier is what the conformance corpus
asserts — ``malformed/*.error`` files and ``rrule/**/*.expect.json``
sidecars name a class by its Go spelling — so ``"ErrMalformed"`` is
data, not a Go implementation detail.

Catch by class or by attribute; both work::

    try:
        parse(data)
    except Malformed:
        ...
    except VstarError as e:
        if e.sentinel == "ErrIterationCap":
            ...

Class names drop the ``Err`` prefix, since ``raise MalformedError`` is
not the Python idiom and the class is already an exception. The
``sentinel`` attribute keeps the Go identifier verbatim.

Only the first four are raisable at the codec layer. The remaining
eight are declared here so the set is complete from the start and the
later layers have nothing to widen.
"""

# ruff: noqa: N818 - the class names are a cross-language naming
# contract, not a local style choice. docs/dev/api-mapping.md fixes them
# verbatim ("Malformed", "UnclosedBlock", ...) so the four ports land on
# one API shape; an "Error" suffix here would diverge the Python port
# from the other three. PHP keeps an "Exception" suffix for the same
# reason -- it is that language's norm; dropping the suffix is Python's.

from __future__ import annotations

__all__ = [
    "AlreadyClosed",
    "HeaderLocked",
    "IterationCap",
    "Malformed",
    "MissingUid",
    "NoAnchor",
    "NoTrigger",
    "TargetCorrupted",
    "UnboundedExpansion",
    "UnclosedBlock",
    "UnsupportedRrule",
    "UnsupportedVersion",
    "VstarError",
]


class VstarError(Exception):
    """Base of every V* failure.

    Subclasses set :attr:`sentinel` to the Go identifier. Positional
    context travels on :attr:`line` where the failure site is known,
    mirroring how the Go reference wraps its sentinels with
    ``fmt.Errorf("line %d: %w", n, ...)``.
    """

    #: The Go sentinel identifier, verbatim. Overridden per subclass.
    sentinel: str = "ErrVstar"

    #: 1-based content-line number, or ``None`` when the site is unknown.
    line: int | None

    def __init__(self, message: str, *, line: int | None = None) -> None:
        self.line = line
        rendered = (
            f"{self.sentinel}: {message}"
            if line is None
            else f"{self.sentinel}: line {line}: {message}"
        )
        super().__init__(rendered)


class Malformed(VstarError):
    """Structurally invalid input.

    A bad escape, bad parameter syntax, an unparseable value, or an
    RRULE on the parsing scope's hard-error list.
    """

    sentinel = "ErrMalformed"


class UnclosedBlock(VstarError):
    """A ``BEGIN`` line lacks its matching ``END`` before end of input."""

    sentinel = "ErrUnclosedBlock"


class UnsupportedVersion(VstarError):
    """A ``VERSION`` property is neither vCard 4.0 nor iCalendar 2.0."""

    sentinel = "ErrUnsupportedVersion"


class MissingUid(VstarError):
    """A component that requires ``UID`` has none.

    Encoder-only at the codec layer: the vCard *parser* accepts
    a UID-less VCARD so adopters can recover a non-conforming document,
    and the *encoder* refuses to emit one.
    """

    sentinel = "ErrMissingUID"


class UnsupportedRrule(VstarError):
    """Syntactically valid but outside the RRULE parsing scope."""

    sentinel = "ErrUnsupportedRRule"


class IterationCap(VstarError):
    """The evaluator reached its iteration bound without an occurrence."""

    sentinel = "ErrIterationCap"


class UnboundedExpansion(VstarError):
    """A request to expand into a list with no bound."""

    sentinel = "ErrUnboundedExpansion"


class TargetCorrupted(VstarError):
    """A target's ``X-VSTAR-HASH`` does not match its canonical form."""

    sentinel = "ErrTargetCorrupted"


class AlreadyClosed(VstarError):
    """``close`` called twice, or ``encode`` called after ``close``."""

    sentinel = "ErrAlreadyClosed"


class HeaderLocked(VstarError):
    """``set_header`` called after the first ``encode`` locked the header."""

    sentinel = "ErrHeaderLocked"


class NoTrigger(VstarError):
    """A ``VALARM`` without a ``TRIGGER``; the property is mandatory."""

    sentinel = "ErrNoTrigger"


class NoAnchor(VstarError):
    """A relative trigger resolved against a component lacking its anchor."""

    sentinel = "ErrNoAnchor"
