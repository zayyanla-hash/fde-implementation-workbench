"""Bounded retry + recovery helpers.

Retries only recoverable ToolError (never FatalToolError or validation
failures). Every attempt is recorded on the ToolCall so the audit trail
shows exactly what was retried and why. No sleeping — backoff is
simulated and logged to keep demos fast and deterministic.
"""

from __future__ import annotations

from typing import Any, Callable

from .models import ToolCall
from .tools import FatalToolError, ToolError


def call_with_retry(
    tool_name: str,
    fn: Callable[[], dict[str, Any]],
    payload: dict[str, Any],
    max_attempts: int = 3,
) -> ToolCall:
    last_error: str | None = None
    attempts = 0
    for attempt in range(1, max_attempts + 1):
        attempts = attempt
        try:
            output = fn()
            return ToolCall(
                tool=tool_name,
                input=payload,
                output=output,
                status="ok" if attempt == 1 else "retrying",
                attempts=attempts,
                latency_ms=attempt * 7,  # simulated, deterministic
                error=None if attempt == 1 else f"recovered after {attempt - 1} retry(ies): {last_error}",
            )
        except FatalToolError as exc:
            return ToolCall(
                tool=tool_name,
                input=payload,
                output={},
                status="failed",
                attempts=attempts,
                latency_ms=attempt * 7,
                error=f"fatal: {exc}",
            )
        except ToolError as exc:
            last_error = str(exc)
            if attempt == max_attempts:
                return ToolCall(
                    tool=tool_name,
                    input=payload,
                    output={},
                    status="failed",
                    attempts=attempts,
                    latency_ms=attempt * 7,
                    error=f"exhausted {max_attempts} attempts: {last_error}",
                )
            continue
    raise AssertionError("unreachable")  # pragma: no cover
