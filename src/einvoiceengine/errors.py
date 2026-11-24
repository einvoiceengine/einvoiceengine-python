"""Exceptions raised by the client.

Every API error carries the HTTP status, the machine-readable ``code`` from the response body
(see https://einvoiceengine.com/docs/errors), the message, optional ``details`` and the
``request_id`` to quote when contacting support.
"""

from __future__ import annotations

from typing import Any, Dict, Optional, Type


class EInvoicingError(Exception):
    """Base class for every error raised by this package."""

    def __init__(
        self,
        message: str,
        *,
        status: int = 0,
        code: str = "error",
        details: Any = None,
        request_id: Optional[str] = None,
        docs: Optional[str] = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.status = status
        self.code = code
        self.details = details
        self.request_id = request_id
        self.docs = docs

    def __str__(self) -> str:
        parts = [f"[{self.status} {self.code}] {self.message}" if self.status else self.message]
        if self.request_id:
            parts.append(f"(request {self.request_id})")
        return " ".join(parts)


class APIConnectionError(EInvoicingError):
    """The request did not reach the API or no response came back (network, DNS, TLS, timeout)."""


class InvalidRequestError(EInvoicingError):
    """400 or 422: the request or the document could not be processed as sent."""


class AuthenticationError(EInvoicingError):
    """401: missing, unknown or revoked API key."""


class QuotaExceededError(EInvoicingError):
    """402: the plan's document allowance is used up."""


class PermissionDeniedError(EInvoicingError):
    """403: the key lacks the scope for this call, or the plan does not include it."""


class NotFoundError(EInvoicingError):
    """404: no such resource for this key's organization and mode."""


class ConflictError(EInvoicingError):
    """409: the resource is in a state that does not allow the call."""


class PayloadTooLargeError(EInvoicingError):
    """413: the document is larger than the endpoint accepts."""


class RateLimitError(EInvoicingError):
    """429: too many requests; raised after the configured retries are used up."""


class ServerError(EInvoicingError):
    """5xx: the service failed or is temporarily unavailable; raised after retries."""


_BY_STATUS: Dict[int, Type[EInvoicingError]] = {
    400: InvalidRequestError,
    401: AuthenticationError,
    402: QuotaExceededError,
    403: PermissionDeniedError,
    404: NotFoundError,
    409: ConflictError,
    413: PayloadTooLargeError,
    422: InvalidRequestError,
    429: RateLimitError,
}


def error_for(status: int) -> Type[EInvoicingError]:
    if status >= 500:
        return ServerError
    return _BY_STATUS.get(status, EInvoicingError)
