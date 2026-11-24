"""Python client for the E-Invoicing API (https://einvoiceengine.com)."""

__version__ = "0.1.0"

from .client import DEFAULT_BASE_URL, Document, EInvoicing, document_bytes  # noqa: E402
from .errors import (  # noqa: E402
    APIConnectionError,
    AuthenticationError,
    ConflictError,
    EInvoicingError,
    InvalidRequestError,
    NotFoundError,
    PayloadTooLargeError,
    PermissionDeniedError,
    QuotaExceededError,
    RateLimitError,
    ServerError,
)

__all__ = [
    "__version__",
    "DEFAULT_BASE_URL",
    "Document",
    "EInvoicing",
    "document_bytes",
    "EInvoicingError",
    "APIConnectionError",
    "AuthenticationError",
    "ConflictError",
    "InvalidRequestError",
    "NotFoundError",
    "PayloadTooLargeError",
    "PermissionDeniedError",
    "QuotaExceededError",
    "RateLimitError",
    "ServerError",
]
