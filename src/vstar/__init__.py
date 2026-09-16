# SPDX-License-Identifier: MIT

"""V* calendar and contact interchange — Python port.

The distribution is ``hop-top-vstar``; the import name is ``vstar``.
release-please only rewrites a ``__init__.py`` version when the package
directory matches the distribution slug, which it does not here, so the
version is read back from the installed distribution metadata rather
than duplicated as a literal.

This module re-exports the data model, the twelve error sentinels, and
the codec protocols. The wire formats live under :mod:`vstar.codec`::

    from vstar.codec import rfc5545

    cal = rfc5545.parse(data)
    wire = rfc5545.encode(cal)
"""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as _version

from . import canonical, diff, duration, ext, hashing, helpers, supersession
from ._codec import Codec, Encoder, Parser
from .date import VALUE_DATE, VALUE_PARAM, VDate, date_of, format_date, parse_date
from .errors import (
    AlreadyClosed,
    HeaderLocked,
    IterationCap,
    Malformed,
    MissingUid,
    NoAnchor,
    NoTrigger,
    TargetCorrupted,
    UnboundedExpansion,
    UnclosedBlock,
    UnsupportedRrule,
    UnsupportedVersion,
    VstarError,
)
from .time import format_time, parse_time, parse_time_with_tzid
from .types import (
    CLASS_CONFIDENTIAL,
    CLASS_PRIVATE,
    CLASS_PUBLIC,
    COMP_ALARM,
    COMP_CALENDAR,
    COMP_EVENT,
    COMP_FREE_BUSY,
    COMP_JOURNAL,
    COMP_TIMEZONE,
    COMP_TODO,
    DEFAULT_REL_TYPE,
    EVENT_CANCELLED,
    EVENT_CONFIRMED,
    EVENT_TENTATIVE,
    JOURNAL_CANCELLED,
    JOURNAL_DRAFT,
    JOURNAL_FINAL,
    KIND_GROUP,
    KIND_INDIVIDUAL,
    KIND_ORG,
    REL_CHILD,
    REL_CONCEPT,
    REL_DEPENDS_ON,
    REL_FINISH_TO_FINISH,
    REL_FINISH_TO_START,
    REL_FIRST,
    REL_NEXT,
    REL_PARENT,
    REL_REF_ID,
    REL_SIBLING,
    REL_START_TO_FINISH,
    REL_START_TO_START,
    TODO_CANCELLED,
    TODO_COMPLETED,
    TODO_IN_PROCESS,
    TODO_NEEDS_ACTION,
    TRANSP_OPAQUE,
    TRANSP_TRANSPARENT,
    Calendar,
    Card,
    Component,
    CompType,
    EventStatus,
    JournalStatus,
    Kind,
    Param,
    Property,
    RelType,
    TodoStatus,
    Transp,
    VClass,
    equal_fold,
    parse_rel_type,
    property_equal,
)

try:
    __version__: str = _version("hop-top-vstar")
except PackageNotFoundError:  # pragma: no cover - source tree, not installed
    __version__ = "0.0.0.dev0"

__all__ = [
    "CLASS_CONFIDENTIAL",
    "CLASS_PRIVATE",
    "CLASS_PUBLIC",
    "COMP_ALARM",
    "COMP_CALENDAR",
    "COMP_EVENT",
    "COMP_FREE_BUSY",
    "COMP_JOURNAL",
    "COMP_TIMEZONE",
    "COMP_TODO",
    "DEFAULT_REL_TYPE",
    "EVENT_CANCELLED",
    "EVENT_CONFIRMED",
    "EVENT_TENTATIVE",
    "JOURNAL_CANCELLED",
    "JOURNAL_DRAFT",
    "JOURNAL_FINAL",
    "KIND_GROUP",
    "KIND_INDIVIDUAL",
    "KIND_ORG",
    "REL_CHILD",
    "REL_CONCEPT",
    "REL_DEPENDS_ON",
    "REL_FINISH_TO_FINISH",
    "REL_FINISH_TO_START",
    "REL_FIRST",
    "REL_NEXT",
    "REL_PARENT",
    "REL_REF_ID",
    "REL_SIBLING",
    "REL_START_TO_FINISH",
    "REL_START_TO_START",
    "TODO_CANCELLED",
    "TODO_COMPLETED",
    "TODO_IN_PROCESS",
    "TODO_NEEDS_ACTION",
    "TRANSP_OPAQUE",
    "TRANSP_TRANSPARENT",
    "VALUE_DATE",
    "VALUE_PARAM",
    "AlreadyClosed",
    "Calendar",
    "Card",
    "Codec",
    "CompType",
    "Component",
    "Encoder",
    "EventStatus",
    "HeaderLocked",
    "IterationCap",
    "JournalStatus",
    "Kind",
    "Malformed",
    "MissingUid",
    "NoAnchor",
    "NoTrigger",
    "Param",
    "Parser",
    "Property",
    "RelType",
    "TargetCorrupted",
    "TodoStatus",
    "Transp",
    "UnboundedExpansion",
    "UnclosedBlock",
    "UnsupportedRrule",
    "UnsupportedVersion",
    "VClass",
    "VDate",
    "VstarError",
    "__version__",
    "canonical",
    "date_of",
    "diff",
    "duration",
    "equal_fold",
    "ext",
    "format_date",
    "format_time",
    "hashing",
    "helpers",
    "parse_date",
    "parse_rel_type",
    "parse_time",
    "parse_time_with_tzid",
    "property_equal",
    "supersession",
]
