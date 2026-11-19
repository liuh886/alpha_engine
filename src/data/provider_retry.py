"""Bounded retry/backoff for transient market-data provider failures.

Retry is deliberately narrow. Only transport-level failures (network, timeout,
rate limit and provider-side 5xx) are retried. Schema, identity, entitlement and
adjustment-contract failures fail immediately: retrying or swapping the source
would hide a data defect behind a different vendor.

The caller receives one evidence record per attempt so the final outcome can be
bound into the bundle/publication manifest.
"""

from __future__ import annotations

import random
import socket
import time
import urllib.error
from dataclasses import dataclass, field
from typing import Any, Callable, TypeVar

from src.data.adapters.base import (
    DataFetchError,
    ProviderContractError,
    ProviderRateLimitError,
    ProviderTimeoutError,
    ProviderTransientError,
    ProviderUnavailableError,
)

T = TypeVar("T")

_TRANSIENT_ERROR_CLASSES = frozenset(
    {
        "rate_limited",
        "timeout",
        "provider_timeout",
        "provider_unavailable",
        "provider_upstream_error",
        "transient_provider_error",
        "network_error",
    }
)
_NON_TRANSIENT_ERROR_CLASSES = frozenset(
    {
        "schema_error",
        "schema_or_reconciliation_error",
        "provider_contract_error",
        "provider_symbol_not_found",
        "credential_or_entitlement",
        "invalid_provider_response",
        "provider_not_configured",
    }
)


@dataclass(frozen=True)
class RetryPolicy:
    """Bounded exponential backoff with jitter."""

    max_attempts: int = 3
    base_delay_seconds: float = 0.5
    max_delay_seconds: float = 8.0
    max_honored_retry_after_seconds: float = 30.0
    jitter_ratio: float = 0.25

    def __post_init__(self) -> None:
        if self.max_attempts < 1:
            raise ValueError("max_attempts must be at least 1")
        if self.base_delay_seconds < 0.0:
            raise ValueError("base_delay_seconds must be non-negative")
        if self.max_delay_seconds < 0.0:
            raise ValueError("max_delay_seconds must be non-negative")
        if not 0.0 <= self.jitter_ratio < 1.0:
            raise ValueError("jitter_ratio must be in [0, 1)")


@dataclass
class RetryOutcome:
    value: T
    attempts: int
    outcome: str
    history: list[dict[str, Any]] = field(default_factory=list)


def _declared_error_class(exc: BaseException) -> str:
    return str(getattr(exc, "error_class", "") or "").strip()


def _retry_after_seconds(exc: BaseException) -> float | None:
    value = getattr(exc, "retry_after_seconds", None)
    if value is None:
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed >= 0.0 else None


def _header_retry_after(headers: Any) -> float | None:
    if headers is None:
        return None
    value = headers.get("Retry-After")
    if value is None:
        return None
    try:
        parsed = float(str(value).strip())
    except ValueError:
        return None
    return parsed if parsed >= 0.0 else None


def classify_transient(exc: BaseException) -> tuple[bool, float | None]:
    """Return ``(retryable, retry_after_seconds)`` for one provider failure.

    ``ProviderContractError`` and any declared contract/invalid-data class are
    never retryable, regardless of message text. HTTP errors are classified by
    status code so a 404 never triggers backoff.
    """

    if isinstance(exc, ProviderContractError):
        return False, None
    declared = _declared_error_class(exc)
    if declared in _NON_TRANSIENT_ERROR_CLASSES:
        return False, None
    if isinstance(exc, urllib.error.HTTPError):
        retry_after = _header_retry_after(exc.headers)
        if exc.code == 429:
            return True, retry_after
        if 500 <= int(exc.code) < 600:
            return True, retry_after
        return False, None
    if isinstance(exc, ProviderRateLimitError):
        return True, _retry_after_seconds(exc)
    if isinstance(exc, (ProviderTimeoutError, ProviderUnavailableError, ProviderTransientError)):
        return True, _retry_after_seconds(exc)
    if isinstance(exc, socket.timeout):
        return True, None
    if isinstance(exc, (TimeoutError, ConnectionError)):
        return True, None
    if isinstance(exc, urllib.error.URLError):
        return True, None
    if declared in _TRANSIENT_ERROR_CLASSES:
        return True, _retry_after_seconds(exc)
    return False, None


def _delay_for_attempt(
    *,
    attempt: int,
    retry_after_seconds: float | None,
    policy: RetryPolicy,
    random_fn: Callable[[], float],
) -> tuple[float | None, str | None]:
    """Return ``(delay, stop_reason)`` for the next retry."""

    if retry_after_seconds is not None:
        if retry_after_seconds > policy.max_honored_retry_after_seconds:
            return None, "retry_after_exceeds_bound"
        return retry_after_seconds, None
    raw = policy.base_delay_seconds * float(2 ** (attempt - 1))
    raw = min(policy.max_delay_seconds, raw)
    if policy.jitter_ratio:
        raw = raw * (1.0 + policy.jitter_ratio * (2.0 * random_fn() - 1.0))
    return max(0.0, raw), None


def call_with_retry(
    call: Callable[[], T],
    *,
    policy: RetryPolicy | None = None,
    sleep: Callable[[float], None] = time.sleep,
    random_fn: Callable[[], float] = random.random,
    evidence: dict[str, Any] | None = None,
    label: str = "provider",
) -> RetryOutcome:
    """Run ``call`` with bounded retries for transient failures only.

    On success returns the value and writes ``retry_attempts``,
    ``retry_outcome`` and ``retry_history`` into ``evidence``. On final failure
    the original exception is re-raised after the same evidence is recorded, so
    callers keep the provider's typed failure class.
    """

    resolved = policy or RetryPolicy()
    target = evidence if evidence is not None else {}
    history: list[dict[str, Any]] = []
    target["retry_policy"] = {
        "max_attempts": resolved.max_attempts,
        "base_delay_seconds": resolved.base_delay_seconds,
        "max_delay_seconds": resolved.max_delay_seconds,
        "max_honored_retry_after_seconds": resolved.max_honored_retry_after_seconds,
        "jitter_ratio": resolved.jitter_ratio,
    }

    for attempt in range(1, resolved.max_attempts + 1):
        try:
            value = call()
        except Exception as exc:  # noqa: BLE001 - provider boundary
            retryable, retry_after = classify_transient(exc)
            record: dict[str, Any] = {
                "attempt": attempt,
                "error_class": _declared_error_class(exc) or type(exc).__name__,
                "retryable": retryable,
            }
            if retry_after is not None:
                record["retry_after_seconds"] = retry_after
            if not retryable:
                record["final"] = True
                record["stop_reason"] = "non_transient"
                history.append(record)
                target["retry_attempts"] = attempt
                target["retry_outcome"] = "not_retried"
                target["retry_history"] = history
                raise
            if attempt >= resolved.max_attempts:
                record["final"] = True
                record["stop_reason"] = "attempts_exhausted"
                history.append(record)
                target["retry_attempts"] = attempt
                target["retry_outcome"] = "exhausted"
                target["retry_history"] = history
                raise
            delay, stop_reason = _delay_for_attempt(
                attempt=attempt,
                retry_after_seconds=retry_after,
                policy=resolved,
                random_fn=random_fn,
            )
            if stop_reason is not None:
                record["final"] = True
                record["stop_reason"] = stop_reason
                history.append(record)
                target["retry_attempts"] = attempt
                target["retry_outcome"] = "not_retried"
                target["retry_history"] = history
                raise
            record["delay_seconds"] = round(float(delay or 0.0), 6)
            history.append(record)
            if delay:
                sleep(float(delay))
            continue
        target["retry_attempts"] = attempt
        target["retry_outcome"] = "succeeded" if attempt == 1 else "succeeded_after_retry"
        target["retry_history"] = history
        return RetryOutcome(
            value=value,
            attempts=attempt,
            outcome=target["retry_outcome"],
            history=history,
        )

    # The loop always returns or raises; keep a defensive contract error.
    raise DataFetchError(f"{label} retry loop terminated without a result")


__all__ = [
    "RetryPolicy",
    "RetryOutcome",
    "call_with_retry",
    "classify_transient",
]
