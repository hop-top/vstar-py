# GENERATED — do not edit.
# Source: spec/registry/ · Generator: tools/registry/gen.py
# Run `make registry-gen` after editing the registry JSON.

from __future__ import annotations

from typing import Final


#: Required common property UID is missing.
MISSING_UID: Final[str] = "VS001"

#: Required common property DTSTAMP is missing.
MISSING_DTSTAMP: Final[str] = "VS002"

#: Required common property X-VSTAR-HASH is missing.
MISSING_XVSTAR_HASH: Final[str] = "VS003"

#: X-VSTAR-HASH is present but does not match the recomputed hash.
BAD_XVSTAR_HASH: Final[str] = "VS010"

#: Property name is not on the RFC 5545/6350 allow-list and lacks the X- prefix.
UNKNOWN_PROPERTY: Final[str] = "VS020"

#: A supersession VJOURNAL (CATEGORIES contains status-supersession) is missing a required property: RELATED-TO or X-VSTAR-EFFECTIVE-STATUS.
SUPERSESSION_MISSING_PROPS: Final[str] = "VS030"

#: A supersession VJOURNAL's RELATED-TO does not resolve to any component in the same Calendar (orphan supersession).
SUPERSESSION_ORPHAN: Final[str] = "VS031"

#: VTODO requires DUE, OR STATUS=COMPLETED paired with COMPLETED.
VTODO_MISSING_DUE: Final[str] = "VS040"

#: VEVENT requires DTSTART.
VEVENT_MISSING_DTSTART: Final[str] = "VS041"

#: VFREEBUSY requires DTSTART AND DTEND.
VFREEBUSY_MISSING_TIMES: Final[str] = "VS042"

#: VCARD (modeled as Component{Type: "VCARD"}) requires VERSION AND UID.
VCARD_MISSING_REQUIRED: Final[str] = "VS043"

#: STATUS value is outside the vocabulary RFC 5545 §3.8.1.11 scopes to the component's own type.
STATUS_NOT_IN_VOCABULARY: Final[str] = "VS044"

#: RRULE value parses but uses a feature outside the RRULE parsing scope (FREQ=SECONDLY, RSCALE — see spec/03 §RRULE parsing scope).
R_RULE_UNSUPPORTED: Final[str] = "VS050"

#: RRULE value is malformed per RFC 5545 §3.3.10 (missing FREQ, INTERVAL≤0, both UNTIL+COUNT, BYMONTHDAY=0, UNTIL not in form #2, etc.).
R_RULE_MALFORMED: Final[str] = "VS051"

#: A duration-bearing property value is malformed: the DURATION property, the relative (DURATION-valued) form of TRIGGER, or a REPEAT count that is not a non-negative integer (RFC 5545 §3.3.6 / §3.8.6.2) written as a canonical decimal — no sign, no leading zeros, no whitespace (see spec/05 §8); or a TRIGGER whose VALUE parameter contradicts its value, or that carries RELATED on an absolute trigger — see spec/03 §TRIGGER conventions.
MALFORMED_DURATION: Final[str] = "VS052"

#: CLASS value is outside the RFC 5545 §3.8.1.3 vocabulary PUBLIC, PRIVATE, CONFIDENTIAL (compared case-insensitively — see spec/05 §8).
CLASS_NOT_IN_VOCABULARY: Final[str] = "VS053"

#: TRANSP value is outside the RFC 5545 §3.8.2.7 vocabulary OPAQUE, TRANSPARENT (compared case-insensitively — see spec/05 §8).
TRANSP_NOT_IN_VOCABULARY: Final[str] = "VS054"

#: An integer-valued property is not a canonical decimal (no sign, no leading zeros, no whitespace) inside its RFC 5545 domain: PRIORITY 0–9 (§3.8.1.9), PERCENT-COMPLETE 0–100 (§3.8.1.8), SEQUENCE non-negative (§3.8.7.4) — see spec/05 §8.
INTEGER_OUT_OF_DOMAIN: Final[str] = "VS055"

CODE_SEVERITIES: Final[dict[str, str]] = {
    "VS001": "error",
    "VS002": "error",
    "VS003": "error",
    "VS010": "error",
    "VS020": "warning",
    "VS030": "error",
    "VS031": "error",
    "VS040": "error",
    "VS041": "error",
    "VS042": "error",
    "VS043": "error",
    "VS044": "error",
    "VS050": "warning",
    "VS051": "error",
    "VS052": "error",
    "VS053": "error",
    "VS054": "error",
    "VS055": "error",
}

STANDARD_PROPERTIES: Final[frozenset[str]] = frozenset(
    (
        "ACTION",
        "ADR",
        "ANNIVERSARY",
        "ATTACH",
        "ATTENDEE",
        "BDAY",
        "CALADRURI",
        "CALSCALE",
        "CALURI",
        "CATEGORIES",
        "CLASS",
        "CLIENTPIDMAP",
        "COMMENT",
        "COMPLETED",
        "CONTACT",
        "CREATED",
        "DESCRIPTION",
        "DTEND",
        "DTSTAMP",
        "DTSTART",
        "DUE",
        "DURATION",
        "EMAIL",
        "EXDATE",
        "EXRULE",
        "FBURL",
        "FN",
        "FREEBUSY",
        "GENDER",
        "GEO",
        "IMPP",
        "KEY",
        "KIND",
        "LANG",
        "LAST-MODIFIED",
        "LOCATION",
        "LOGO",
        "MEMBER",
        "METHOD",
        "N",
        "NICKNAME",
        "NOTE",
        "ORG",
        "ORGANIZER",
        "PERCENT-COMPLETE",
        "PHOTO",
        "PRIORITY",
        "PRODID",
        "RDATE",
        "RECURRENCE-ID",
        "RELATED",
        "RELATED-TO",
        "REPEAT",
        "REQUEST-STATUS",
        "RESOURCES",
        "REV",
        "ROLE",
        "RRULE",
        "SEQUENCE",
        "SOUND",
        "SOURCE",
        "STATUS",
        "SUMMARY",
        "TEL",
        "TITLE",
        "TRANSP",
        "TRIGGER",
        "TZ",
        "TZID",
        "TZNAME",
        "TZOFFSETFROM",
        "TZOFFSETTO",
        "TZURL",
        "UID",
        "URL",
        "VERSION",
        "XML",
    )
)

#: The registry's STATUS vocabulary, keyed by the component type
#: RFC 5545 §3.8.1.11 scopes it to. A type absent from this mapping
#: admits no STATUS vocabulary.
#:
#: This is the cross-language table, not the port's wire constants.
#: The validator keeps deriving its table from the constants the
#: codec encodes against, and a test asserts the two agree — so the
#: table cannot drift from the codec, nor from the other ports.
STATUS_VOCABULARY: Final[dict[str, tuple[str, ...]]] = {
    "VEVENT": ("TENTATIVE", "CONFIRMED", "CANCELLED",),
    "VJOURNAL": ("DRAFT", "FINAL", "CANCELLED",),
    "VTODO": ("NEEDS-ACTION", "IN-PROCESS", "COMPLETED", "CANCELLED",),
}

#: The registry's CLASS vocabulary, RFC 5545 §3.8.1.3.
CLASS_VOCABULARY: Final[tuple[str, ...]] = (
    "PUBLIC",
    "PRIVATE",
    "CONFIDENTIAL",
)

#: The registry's TRANSP vocabulary, RFC 5545 §3.8.2.7.
TRANSP_VOCABULARY: Final[tuple[str, ...]] = (
    "OPAQUE",
    "TRANSPARENT",
)

#: The registry's registered RELTYPE vocabulary, RFC 5545 §3.2.15
#: plus RFC 9253 §11.4. Registered, not closed: RELTYPE admits IANA
#: and X- values outside it.
RELTYPE_VOCABULARY: Final[tuple[str, ...]] = (
    "PARENT",
    "CHILD",
    "SIBLING",
    "FINISHTOSTART",
    "FINISHTOFINISH",
    "STARTTOFINISH",
    "STARTTOSTART",
    "DEPENDS-ON",
    "FIRST",
    "NEXT",
    "CONCEPT",
    "REFID",
)
