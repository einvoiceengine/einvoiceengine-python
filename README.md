# einvoiceengine

Python client for the [E-Invoicing API](https://einvoiceengine.com): validate, parse, convert, create and repair European e-invoices — XRechnung 3.0, EN 16931 (UBL and CII), Peppol BIS Billing 3.0, ZUGFeRD / Factur-X (XML or PDF/A-3), Facturae 3.2.x and KSeF FA(3).

Validation uses the official KoSIT validator with the official rule set of each format. Technical validation does not establish legal validity.

- Python 3.9+, no dependencies (standard library only), fully typed
- Retries 429 and 5xx responses with backoff (honours `Retry-After`)
- Billable calls send an `Idempotency-Key`, so a retry is never billed twice

## Install

```bash
pip install einvoiceengine
```

Get a free sandbox key (`einv_test_…`) at <https://einvoiceengine.com/dashboard/keys>.

## Validate

```python
import os
from pathlib import Path
from einvoiceengine import EInvoicing

einv = EInvoicing(api_key=os.environ["EINV_KEY"], lang="en")

result = einv.validate(Path("invoice.xml"))        # XML file, ZUGFeRD PDF, bytes or XML text
print(result["status"], result["detected"].get("format"))
for f in result["findings"]:
    print(f["severity"], f["ruleId"], f["explanation"])
```

A `pathlib.Path` is read from disk; a `str` is treated as XML text; `bytes` may be XML or PDF.

## Parse to JSON

```python
parsed = einv.parse(Path("invoice.xml"))
invoice = parsed["invoice"]                         # canonical EN 16931 model
print(invoice["id"], invoice["totals"]["payable"])
```

## Convert

```python
from einvoiceengine import document_bytes

r = einv.convert(Path("invoice-ubl.xml"), "cii")
Path("invoice-cii.xml").write_bytes(document_bytes(r))

pdf = einv.convert(Path("invoice.xml"), "zugferd-facturx", profile="XRECHNUNG")
Path("invoice.pdf").write_bytes(document_bytes(pdf))   # base64 is decoded for you
```

Targets: `ubl`, `cii`, `xrechnung-ubl`, `xrechnung-cii`, `en16931-ubl`, `en16931-cii`, `peppol-bis-billing`, `zugferd-facturx`, `facturae`, `ksef`. Conversions that would drop data fail unless `allow_data_loss=True`.

## Create from JSON

```python
r = einv.generate(invoice_dict, "xrechnung-ubl")    # also en16931-*, peppol-bis-billing, zugferd-facturx
Path("invoice.xml").write_bytes(document_bytes(r))
```

The document is validated before it is returned. When data is missing, `InvalidRequestError` is raised and `err.details["findings"]` names the JSON fields to fill.

## Repair a rejected invoice

```python
analysis = einv.analyze(Path("rejected.xml"), "BR-DE-15: Buyer reference missing")
for p in analysis["proposals"]:
    print(p["id"], p["field"], p["category"], p["explanation"])

fixed = einv.repair(
    Path("rejected.xml"),
    changes=[{"field": "buyerReference", "value": "04011000-12345-34"}],
)
print(fixed["validation"]["status"])
Path("fixed.xml").write_bytes(document_bytes(fixed))
```

Amounts, tax data and bank or party identifiers are only changed with `confirm_amounts=True`, after a person has confirmed the new values. `accept=[...]` applies proposals by id; `apply_safe=True` applies every proposal of category `safe`.

## Errors

| Exception | HTTP |
|---|---|
| `InvalidRequestError` | 400, 422 |
| `AuthenticationError` | 401 |
| `QuotaExceededError` | 402 |
| `PermissionDeniedError` | 403 |
| `NotFoundError` | 404 |
| `ConflictError` | 409 |
| `PayloadTooLargeError` | 413 |
| `RateLimitError` | 429 (after retries) |
| `ServerError` | 5xx (after retries) |
| `APIConnectionError` | network failure |

All derive from `EInvoicingError` with `.status`, `.code`, `.message`, `.details` and `.request_id`. Codes are listed at <https://einvoiceengine.com/docs/errors>.

```python
from einvoiceengine import EInvoicingError

try:
    einv.validate(Path("invoice.xml"))
except EInvoicingError as e:
    print(e.status, e.code, e.message, e.request_id)
```

## Options

```python
EInvoicing(
    api_key=None,          # default: $EINV_KEY
    base_url=None,         # default: $EINV_BASE or https://einvoiceengine.com (self-hosted: your host)
    lang="de",             # explanations in en, de, fr, es, it, pl, nl, pt
    retries=3,
    timeout=60.0,
)
```

Other calls: `compare(a, b)`, `get_job(id)`, `explain_rule("BR-DE-15")`, `formats()`, `usage()`, `testdata(target)`, and `request(method, path, ...)` for any endpoint in the [OpenAPI document](https://einvoiceengine.com/openapi.json).

## Licence

MIT
