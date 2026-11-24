"""Client for the E-Invoicing API (https://einvoiceengine.com). Standard library only.

    from einvoiceengine import EInvoicing

    einv = EInvoicing(api_key=os.environ["EINV_KEY"])
    result = einv.validate(Path("invoice.xml"))
    if not result["valid"]:
        for f in result["findings"]:
            print(f["ruleId"], f["explanation"])

429 and 5xx responses are retried with backoff (honouring Retry-After). Calls that create a
billable result send an Idempotency-Key, so a retried request is never billed twice.
"""

from __future__ import annotations

import base64
import json
import os
import random
import socket
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple, Union, cast

from . import __version__
from .errors import APIConnectionError, error_for
from .types import Analysis, Change, Conversion, FixedInvoice, GeneratedInvoice, Job, ParsedInvoice, Validation

DEFAULT_BASE_URL = "https://einvoiceengine.com"

#: A document: XML text (``str``), raw bytes (XML or PDF), or a path to a file (``os.PathLike``).
Document = Union[str, bytes, bytearray, "os.PathLike[str]"]

_RETRY_STATUS = {429, 500, 502, 503, 504}


def _read(doc: Document) -> bytes:
    if isinstance(doc, (bytes, bytearray)):
        return bytes(doc)
    if isinstance(doc, str):
        return doc.encode("utf-8")
    if isinstance(doc, os.PathLike):
        with open(os.fspath(doc), "rb") as fh:
            return fh.read()
    raise TypeError("document must be str (XML text), bytes, or a path (pathlib.Path)")


def _is_pdf(data: bytes) -> bool:
    return data[:4] == b"%PDF"


def _media_type(data: bytes) -> str:
    return "application/pdf" if _is_pdf(data) else "application/xml"


def _json_doc(doc: Document) -> Dict[str, str]:
    data = _read(doc)
    if _is_pdf(data):
        return {"document": base64.b64encode(data).decode("ascii"), "encoding": "base64"}
    try:
        return {"document": data.decode("utf-8"), "encoding": "utf8"}
    except UnicodeDecodeError:
        return {"document": base64.b64encode(data).decode("ascii"), "encoding": "base64"}


def document_bytes(result: Mapping[str, Any]) -> bytes:
    """Bytes of the ``document`` in a convert, generate or fix result (decodes base64 PDFs)."""
    doc = result["document"]
    target = result.get("target") or {}
    if target.get("encoding") == "base64":
        return base64.b64decode(doc)
    return str(doc).encode("utf-8")


def _clean(query: Mapping[str, Any]) -> Dict[str, str]:
    out: Dict[str, str] = {}
    for k, v in query.items():
        if v is None:
            continue
        out[k] = ("true" if v else "false") if isinstance(v, bool) else str(v)
    return out


class EInvoicing:
    """API client. One instance is safe to reuse; it keeps no connection state.

    :param api_key: ``einv_test_…`` (sandbox) or ``einv_live_…``. Defaults to ``$EINV_KEY``.
    :param base_url: API address (default ``https://einvoiceengine.com``; self-hosted: your host).
    :param lang: language of explanations and suggestions in findings.
    :param retries: retries for 429 and 5xx responses and connection errors (default 3).
    :param timeout: seconds per request (default 60).
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        *,
        base_url: Optional[str] = None,
        lang: Optional[str] = None,
        retries: int = 3,
        timeout: float = 60.0,
    ) -> None:
        key = api_key or os.environ.get("EINV_KEY")
        if not key:
            raise ValueError("api_key is required (or set EINV_KEY)")
        self.api_key = key
        self.base_url = (base_url or os.environ.get("EINV_BASE") or DEFAULT_BASE_URL).rstrip("/")
        self.lang = lang
        self.retries = max(0, retries)
        self.timeout = timeout

    # ------------------------------------------------------------------ transport

    def request(
        self,
        method: str,
        path: str,
        *,
        query: Optional[Mapping[str, Any]] = None,
        json_body: Any = None,
        body: Optional[bytes] = None,
        content_type: Optional[str] = None,
        idempotent: bool = False,
    ) -> Any:
        """Low-level call; returns decoded JSON (or text for non-JSON responses, None for 204)."""
        q = _clean(query or {})
        url = f"{self.base_url}{path}" + (f"?{urllib.parse.urlencode(q)}" if q else "")
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "User-Agent": f"einvoiceengine-python/{__version__}",
            "Accept": "application/json",
        }
        if self.lang:
            headers["Accept-Language"] = self.lang
        data: Optional[bytes] = None
        if json_body is not None:
            data = json.dumps(json_body).encode("utf-8")
            headers["Content-Type"] = "application/json"
        elif body is not None:
            data = body
            headers["Content-Type"] = content_type or _media_type(body)
        if idempotent:
            headers["Idempotency-Key"] = str(uuid.uuid4())

        attempt = 0
        while True:
            try:
                status, resp_headers, raw = self._send(method, url, headers, data)
            except APIConnectionError:
                if attempt >= self.retries:
                    raise
                self._sleep(self._delay(attempt, None))
                attempt += 1
                continue
            if status in _RETRY_STATUS and attempt < self.retries:
                self._sleep(self._delay(attempt, resp_headers.get("retry-after")))
                attempt += 1
                continue
            return self._decode(status, resp_headers, raw)

    def _send(self, method: str, url: str, headers: Dict[str, str], data: Optional[bytes]) -> Tuple[int, Dict[str, str], bytes]:
        req = urllib.request.Request(url, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                return resp.status, {k.lower(): v for k, v in resp.headers.items()}, resp.read()
        except urllib.error.HTTPError as e:
            hdrs = {k.lower(): v for k, v in (e.headers.items() if e.headers else [])}
            return e.code, hdrs, e.read() or b""
        except (urllib.error.URLError, socket.timeout, ConnectionError, TimeoutError) as e:
            raise APIConnectionError(f"Could not reach {url.split('?')[0]}: {getattr(e, 'reason', e)}") from e

    @staticmethod
    def _delay(attempt: int, retry_after: Optional[str]) -> float:
        try:
            seconds = float(retry_after) if retry_after is not None else 0.0
        except ValueError:
            seconds = 0.0
        if seconds > 0:
            return min(seconds, 60.0)
        return min(0.5 * (2**attempt), 8.0) + random.uniform(0, 0.25)

    @staticmethod
    def _sleep(seconds: float) -> None:
        time.sleep(seconds)

    @staticmethod
    def _decode(status: int, headers: Mapping[str, str], raw: bytes) -> Any:
        ctype = headers.get("content-type", "")
        payload: Any
        if status == 204 or not raw:
            payload = None
        elif "json" in ctype:
            try:
                payload = json.loads(raw.decode("utf-8"))
            except ValueError:
                payload = raw.decode("utf-8", "replace")
        else:
            payload = raw.decode("utf-8", "replace")
        if 200 <= status < 300:
            return payload
        err = payload.get("error") if isinstance(payload, dict) and isinstance(payload.get("error"), dict) else {}
        cls = error_for(status)
        raise cls(
            err.get("message") or f"HTTP {status}",
            status=status,
            code=err.get("code") or "http_error",
            details=err.get("details"),
            request_id=err.get("requestId") or headers.get("x-request-id"),
            docs=err.get("docs"),
        )

    # ------------------------------------------------------------------ operations

    def validate(self, document: Document, *, store: bool = False, rules: Optional[str] = None, async_: Optional[bool] = None) -> Validation:
        """Validate with the official rules of the detected format (XML or ZUGFeRD / Factur-X PDF).

        Returns the validation, or a :class:`Job` (``object == "job"``) for background processing
        (``async_=True`` or documents above 2 MB); poll it with :meth:`get_job`.
        """
        data = _read(document)
        return cast(
            Validation,
            self.request("POST", "/v1/invoices/validate", body=data, query={"store": store, "rules": rules, "async": async_}, idempotent=True),
        )

    def parse(self, document: Document, *, store: bool = False) -> ParsedInvoice:
        """Parse into the canonical EN 16931 JSON model (``result["invoice"]``)."""
        data = _read(document)
        return cast(ParsedInvoice, self.request("POST", "/v1/invoices/parse", body=data, query={"store": store}, idempotent=True))

    def convert(
        self,
        document: Document,
        target: str,
        *,
        allow_data_loss: bool = False,
        profile: Optional[str] = None,
        store: bool = False,
    ) -> Conversion:
        """Convert, e.g. ``target="cii"``, ``"ubl"``, ``"peppol-bis-billing"``, ``"zugferd-facturx"``.

        The converted document is validated and round-trip checked. Use :func:`document_bytes` to get
        the file (PDF targets come back base64-encoded).
        """
        data = _read(document)
        query = {"target": target, "allowDataLoss": allow_data_loss or None, "profile": profile, "store": store}
        return cast(Conversion, self.request("POST", "/v1/invoices/convert", body=data, query=query, idempotent=True))

    def generate(self, invoice: Mapping[str, Any], target: str, *, profile: Optional[str] = None, store: bool = False) -> GeneratedInvoice:
        """Create XRechnung, EN 16931, Peppol BIS or a ZUGFeRD / Factur-X PDF from canonical JSON.

        The result is validated before it is returned; missing data raises
        :class:`InvalidRequestError` with the findings in ``details``.
        """
        query = {"target": target, "profile": profile, "store": store}
        return cast(GeneratedInvoice, self.request("POST", "/v1/invoices/generate", json_body={"invoice": dict(invoice)}, query=query, idempotent=True))

    def analyze(self, document: Document, rejection_message: Optional[str] = None) -> Analysis:
        """Explain a rejection: findings, rule ids from a pasted message, and repair proposals."""
        body: Dict[str, Any] = _json_doc(document)
        if rejection_message:
            body["message"] = rejection_message
        return cast(Analysis, self.request("POST", "/v1/invoices/fix/analyze", json_body=body))

    def repair(
        self,
        document: Document,
        *,
        changes: Optional[Iterable[Union[Change, Mapping[str, Any]]]] = None,
        accept: Optional[Sequence[str]] = None,
        apply_safe: bool = False,
        confirm_amounts: bool = False,
        allow_data_loss: bool = False,
        store: bool = False,
    ) -> FixedInvoice:
        """Apply field changes or accepted proposals and return the same format, validated.

        Amounts, tax data and bank or party identifiers are only changed with
        ``confirm_amounts=True``, after a person confirmed the new values.
        """
        body: Dict[str, Any] = _json_doc(document)
        if changes is not None:
            body["changes"] = [dict(c) for c in changes]
        if accept:
            body["accept"] = list(accept)
        if apply_safe:
            body["applySafe"] = True
        if confirm_amounts:
            body["confirmAmounts"] = True
        if allow_data_loss:
            body["allowDataLoss"] = True
        return cast(FixedInvoice, self.request("POST", "/v1/invoices/fix", json_body=body, query={"store": store}, idempotent=True))

    #: Alias matching the endpoint name.
    fix = repair

    def compare(self, a: Document, b: Document) -> Dict[str, Any]:
        """Business-level comparison of two invoices (not billed)."""
        return cast(Dict[str, Any], self.request("POST", "/v1/invoices/compare", json_body={"a": _json_doc(a), "b": _json_doc(b)}))

    def get_job(self, job_id: str) -> Job:
        """Status and result of a background job."""
        return cast(Job, self.request("GET", f"/v1/jobs/{urllib.parse.quote(job_id, safe='')}"))

    def explain_rule(self, rule_id: str) -> Dict[str, Any]:
        """Explanation and suggested fix for a rule id, e.g. ``BR-DE-15``."""
        return cast(Dict[str, Any], self.request("GET", f"/v1/rules/{urllib.parse.quote(rule_id, safe='')}"))

    def formats(self) -> Dict[str, Any]:
        """Supported formats, versions and limitations."""
        return cast(Dict[str, Any], self.request("GET", "/v1/formats"))

    def usage(self) -> Dict[str, Any]:
        """Documents used and remaining in the current period."""
        return cast(Dict[str, Any], self.request("GET", "/v1/usage"))

    def testdata(self, target: str, cases: Optional[List[str]] = None) -> Dict[str, Any]:
        """Synthetic test invoices with their expected validation result (not billed)."""
        body: Dict[str, Any] = {"target": target}
        if cases:
            body["cases"] = cases
        return cast(Dict[str, Any], self.request("POST", "/v1/testdata", json_body=body))
