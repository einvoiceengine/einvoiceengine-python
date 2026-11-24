"""Typed shapes of the main responses (see https://einvoiceengine.com/openapi.json).

They are ``TypedDict`` s: the client returns plain ``dict`` objects decoded from JSON, and
these types only help editors and type checkers. Fields the API adds later are kept.
"""

from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional, TypedDict, Union

Lang = Literal["en", "de", "fr", "es", "it", "pl", "nl", "pt"]
ConvertTarget = Literal[
    "ubl",
    "cii",
    "xrechnung-ubl",
    "xrechnung-cii",
    "en16931-ubl",
    "en16931-cii",
    "peppol-bis-billing",
    "zugferd-facturx",
    "facturae",
    "ksef",
]
GenerateTarget = Literal["xrechnung-ubl", "xrechnung-cii", "en16931-ubl", "en16931-cii", "peppol-bis-billing", "zugferd-facturx"]


class Location(TypedDict, total=False):
    path: str
    line: int
    column: int


class BusinessTerm(TypedDict):
    id: str
    name: str


class Source(TypedDict):
    name: str
    url: str


class Finding(TypedDict, total=False):
    severity: Literal["error", "warning", "info"]
    ruleId: str
    message: str
    messageTranslation: str
    explanation: str
    suggestion: str
    location: Location
    businessTerms: List[BusinessTerm]
    source: Source
    fields: List[str]


class Detected(TypedDict, total=False):
    format: str
    syntax: str
    documentType: str
    profile: str
    version: str
    specificationId: str
    container: Dict[str, Any]


class Summary(TypedDict):
    errors: int
    warnings: int
    infos: int


class Validation(TypedDict, total=False):
    id: str
    object: Literal["validation"]
    status: Literal["valid", "invalid", "unsupported"]
    valid: bool
    invoiceId: Optional[str]
    stored: bool
    livemode: bool
    detected: Detected
    summary: Summary
    findings: List[Finding]
    ruleset: Dict[str, str]


class ParsedInvoice(TypedDict, total=False):
    object: Literal["parsed_invoice"]
    invoiceId: Optional[str]
    livemode: bool
    stored: bool
    detected: Detected
    invoice: Dict[str, Any]
    warnings: List[Any]


class Target(TypedDict, total=False):
    format: str
    mediaType: str
    encoding: Literal["base64"]


class Conversion(TypedDict, total=False):
    id: str
    object: Literal["conversion"]
    invoiceId: Optional[str]
    livemode: bool
    stored: bool
    target: Target
    document: str
    validation: Validation
    dataLoss: Any


class GeneratedInvoice(TypedDict, total=False):
    id: str
    object: Literal["generated_invoice"]
    invoiceId: Optional[str]
    livemode: bool
    stored: bool
    target: Target
    document: str
    validation: Validation


class FixedInvoice(TypedDict, total=False):
    id: str
    object: Literal["fixed_invoice"]
    invoiceId: Optional[str]
    livemode: bool
    stored: bool
    target: Target
    document: str
    validation: Validation
    applied: List[Dict[str, Any]]
    warnings: List[Any]


class Proposal(TypedDict, total=False):
    id: str
    ruleId: str
    field: str
    current: Any
    proposed: Any
    category: str
    confidence: str
    explanation: str


class Analysis(TypedDict, total=False):
    validation: Validation
    proposals: List[Proposal]
    fixable: bool


class Job(TypedDict, total=False):
    id: str
    object: Literal["job"]
    type: str
    status: Literal["queued", "running", "succeeded", "failed"]
    createdAt: str
    statusUrl: str
    result: Any


class Change(TypedDict):
    field: str
    value: Any


JSON = Union[Dict[str, Any], List[Any], str, int, float, bool, None]
