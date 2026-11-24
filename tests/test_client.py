import base64
import io
import json
import urllib.error
import urllib.request
from email.message import Message
from pathlib import Path

import pytest

import einvoiceengine
from einvoiceengine import (
    APIConnectionError,
    AuthenticationError,
    EInvoicing,
    InvalidRequestError,
    QuotaExceededError,
    RateLimitError,
    ServerError,
    document_bytes,
)

XML = '<?xml version="1.0" encoding="UTF-8"?><Invoice xmlns="urn:oasis:names:specification:ubl:schema:xsd:Invoice-2"><ID>RE-1</ID></Invoice>'
PDF = b"%PDF-1.7\n%\xe2\xe3\xcf\xd3\nfake"

VALID = {
    "id": "6f1d7c1e-0000-4000-8000-000000000001",
    "object": "validation",
    "status": "valid",
    "valid": True,
    "invoiceId": None,
    "stored": False,
    "livemode": False,
    "detected": {"format": "xrechnung", "syntax": "ubl"},
    "summary": {"errors": 0, "warnings": 0, "infos": 0},
    "findings": [],
}


class FakeResponse:
    def __init__(self, status, body, headers):
        self.status = status
        self._body = body
        self.headers = headers

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _headers(d):
    m = Message()
    for k, v in d.items():
        m[k] = v
    return m


class Server:
    """Queue of canned responses; records every request sent through urllib."""

    def __init__(self, monkeypatch):
        self.queue = []
        self.requests = []
        monkeypatch.setattr(urllib.request, "urlopen", self.urlopen)
        monkeypatch.setattr(EInvoicing, "_sleep", staticmethod(lambda s: self.sleeps.append(s)))
        self.sleeps = []

    def reply(self, status=200, body=None, headers=None, raw=None):
        h = {"Content-Type": "application/json", "X-Request-Id": "req_1"}
        h.update(headers or {})
        data = raw if raw is not None else (json.dumps(body).encode() if body is not None else b"")
        self.queue.append((status, data, h))
        return self

    def fail(self, exc):
        self.queue.append(exc)
        return self

    def urlopen(self, req, timeout=None):
        self.requests.append(req)
        item = self.queue.pop(0)
        if isinstance(item, Exception):
            raise item
        status, data, h = item
        if status >= 400:
            raise urllib.error.HTTPError(req.full_url, status, "error", _headers(h), io.BytesIO(data))
        return FakeResponse(status, data, _headers(h))

    @property
    def last(self):
        return self.requests[-1]


@pytest.fixture
def server(monkeypatch):
    return Server(monkeypatch)


@pytest.fixture
def client():
    return EInvoicing("einv_test_abc", lang="de")


def hdr(req, name):
    return {k.lower(): v for k, v in req.header_items()}.get(name.lower())


def test_requires_key(monkeypatch):
    monkeypatch.delenv("EINV_KEY", raising=False)
    with pytest.raises(ValueError):
        EInvoicing()


def test_key_from_env(monkeypatch):
    monkeypatch.setenv("EINV_KEY", "einv_test_env")
    assert EInvoicing().api_key == "einv_test_env"


def test_validate_xml_text(server, client):
    server.reply(body=VALID)
    r = client.validate(XML)
    assert r["valid"] is True
    req = server.last
    assert req.get_method() == "POST"
    assert req.full_url == "https://einvoiceengine.com/v1/invoices/validate?store=false"
    assert hdr(req, "Authorization") == "Bearer einv_test_abc"
    assert hdr(req, "Content-Type") == "application/xml"
    assert hdr(req, "Accept-Language") == "de"
    assert hdr(req, "Idempotency-Key")
    assert req.data == XML.encode()


def test_validate_pdf_path_and_rules(server, client, tmp_path):
    f = tmp_path / "invoice.pdf"
    f.write_bytes(PDF)
    server.reply(body=VALID)
    client.validate(f, rules="2026-11", store=True)
    assert hdr(server.last, "Content-Type") == "application/pdf"
    assert server.last.data == PDF
    assert "store=true" in server.last.full_url and "rules=2026-11" in server.last.full_url


def test_parse(server, client):
    server.reply(body={"object": "parsed_invoice", "invoice": {"id": "RE-1"}, "detected": {}, "warnings": []})
    r = client.parse(XML.encode())
    assert r["invoice"]["id"] == "RE-1"
    assert server.last.full_url.endswith("/v1/invoices/parse?store=false")


def test_convert_to_pdf_and_decode(server, client):
    server.reply(body={"object": "conversion", "document": base64.b64encode(PDF).decode(), "target": {"format": "zugferd-facturx", "mediaType": "application/pdf", "encoding": "base64"}, "validation": VALID})
    r = client.convert(XML, "zugferd-facturx", profile="XRECHNUNG")
    assert document_bytes(r) == PDF
    url = server.last.full_url
    assert "target=zugferd-facturx" in url and "profile=XRECHNUNG" in url and "allowDataLoss" not in url


def test_convert_xml_result(server, client):
    server.reply(body={"document": "<x/>", "target": {"format": "cii", "mediaType": "application/xml"}, "validation": VALID})
    r = client.convert(XML, "cii", allow_data_loss=True)
    assert document_bytes(r) == b"<x/>"
    assert "allowDataLoss=true" in server.last.full_url


def test_generate_sends_json(server, client):
    server.reply(body={"object": "generated_invoice", "document": "<Invoice/>", "target": {"format": "xrechnung-ubl", "mediaType": "application/xml"}, "validation": VALID})
    client.generate({"id": "RE-1", "currency": "EUR"}, "xrechnung-ubl")
    req = server.last
    assert hdr(req, "Content-Type") == "application/json"
    assert json.loads(req.data) == {"invoice": {"id": "RE-1", "currency": "EUR"}}
    assert "target=xrechnung-ubl" in req.full_url


def test_analyze_and_repair(server, client):
    server.reply(body={"proposals": [{"id": "p1", "ruleId": "BR-DE-15", "field": "buyerReference"}], "fixable": True})
    a = client.analyze(XML, "BR-DE-15 rejected")
    assert a["proposals"][0]["id"] == "p1"
    assert json.loads(server.last.data) == {"document": XML, "encoding": "utf8", "message": "BR-DE-15 rejected"}
    assert hdr(server.last, "Idempotency-Key") is None

    server.reply(body={"object": "fixed_invoice", "document": "<Invoice/>", "target": {"format": "xrechnung-ubl"}, "validation": VALID, "applied": []})
    client.repair(XML, changes=[{"field": "buyerReference", "value": "04011000-12345-34"}], accept=["p1"], confirm_amounts=True)
    body = json.loads(server.last.data)
    assert body["changes"] == [{"field": "buyerReference", "value": "04011000-12345-34"}]
    assert body["accept"] == ["p1"] and body["confirmAmounts"] is True and "applySafe" not in body
    assert server.last.full_url.endswith("/v1/invoices/fix?store=false")


def test_repair_pdf_is_base64(server, client):
    server.reply(body={"document": "x", "validation": VALID, "applied": []})
    client.fix(PDF, apply_safe=True)
    body = json.loads(server.last.data)
    assert body["encoding"] == "base64" and base64.b64decode(body["document"]) == PDF and body["applySafe"] is True


def test_compare(server, client):
    server.reply(body={"equal": True, "differences": []})
    assert client.compare(XML, XML)["equal"] is True
    assert json.loads(server.last.data)["a"]["encoding"] == "utf8"


def test_get_requests_escape_ids(server, client):
    server.reply(body={"ruleId": "BR-DE-15"})
    client.explain_rule("BR-DE-15")
    assert server.last.get_method() == "GET" and server.last.full_url.endswith("/v1/rules/BR-DE-15")
    server.reply(body={"id": "a/b", "object": "job", "status": "queued"})
    client.get_job("a/b")
    assert server.last.full_url.endswith("/v1/jobs/a%2Fb")


def test_error_mapping(server, client):
    server.reply(401, {"error": {"code": "invalid_api_key", "message": "Unknown key", "status": 401, "requestId": "req_9", "docs": "https://einvoiceengine.com/docs/errors#invalid_api_key"}})
    with pytest.raises(AuthenticationError) as e:
        client.validate(XML)
    assert e.value.code == "invalid_api_key" and e.value.request_id == "req_9" and e.value.status == 401
    assert "invalid_api_key" in str(e.value)

    server.reply(402, {"error": {"code": "quota_exceeded", "message": "Allowance used", "status": 402, "requestId": "r", "docs": ""}})
    with pytest.raises(QuotaExceededError):
        client.validate(XML)

    details = {"findings": [{"ruleId": "BR-DE-15", "fields": ["buyerReference"]}]}
    server.reply(422, {"error": {"code": "generated_document_invalid", "message": "Missing data", "status": 422, "details": details, "requestId": "r", "docs": ""}})
    with pytest.raises(InvalidRequestError) as e:
        client.generate({}, "xrechnung-ubl")
    assert e.value.details == details


def test_non_json_error(server, client):
    server.reply(400, raw=b"bad gateway text", headers={"Content-Type": "text/plain"})
    with pytest.raises(InvalidRequestError) as e:
        client.formats()
    assert e.value.code == "http_error" and e.value.request_id == "req_1"


def test_retries_429_with_retry_after_then_succeeds(server, client):
    server.reply(429, {"error": {"code": "rate_limited", "message": "slow", "status": 429, "requestId": "r", "docs": ""}}, headers={"Retry-After": "2"})
    server.reply(503, {"error": {"code": "unavailable", "message": "x", "status": 503, "requestId": "r", "docs": ""}})
    server.reply(body=VALID)
    assert client.validate(XML)["valid"]
    assert len(server.requests) == 3
    assert server.sleeps[0] == 2.0
    keys = {hdr(r, "Idempotency-Key") for r in server.requests}
    assert len(keys) == 1, "retries must reuse the idempotency key"


def test_gives_up_after_retries(server):
    c = EInvoicing("einv_test_abc", retries=1)
    for _ in range(2):
        server.reply(500, {"error": {"code": "internal", "message": "boom", "status": 500, "requestId": "r", "docs": ""}})
    with pytest.raises(ServerError):
        c.usage()
    server.reply(429, {"error": {"code": "rate_limited", "message": "x", "status": 429, "requestId": "r", "docs": ""}})
    server.reply(429, {"error": {"code": "rate_limited", "message": "x", "status": 429, "requestId": "r", "docs": ""}})
    with pytest.raises(RateLimitError):
        c.usage()


def test_connection_error(server):
    c = EInvoicing("einv_test_abc", retries=1, base_url="https://self-hosted.example/")
    server.fail(urllib.error.URLError("refused")).fail(urllib.error.URLError("refused"))
    with pytest.raises(APIConnectionError) as e:
        c.formats()
    assert "self-hosted.example/v1/formats" in str(e.value)
    assert len(server.requests) == 2


def test_204_returns_none(server, client):
    server.reply(204, raw=b"")
    assert client.request("DELETE", "/v1/invoices/x") is None


def test_bad_document_type(client):
    with pytest.raises(TypeError):
        client.validate(123)  # type: ignore[arg-type]


def test_version():
    assert einvoiceengine.__version__ == "0.1.0"
