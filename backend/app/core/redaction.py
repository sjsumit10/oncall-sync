"""Keep secrets out of the logs.

Structured logging makes it easy to pass a whole dict into an event, and one day
someone will pass one containing a token. This scrubs by key name so that mistake
produces `[redacted]` rather than a credential sitting in a log aggregator for a
year.
"""

from collections.abc import Mapping, MutableMapping
from typing import Any

SENSITIVE_HINTS = (
    "token",
    "secret",
    "password",
    "authorization",
    "api_key",
    "apikey",
    "credential",
    "cookie",
    "signature",
    "code_verifier",
)

REDACTED = "[redacted]"
MAX_DEPTH = 4


def _is_sensitive(key: str) -> bool:
    lowered = key.lower()
    return any(hint in lowered for hint in SENSITIVE_HINTS)


def _scrub(value: Any, depth: int) -> Any:
    if depth > MAX_DEPTH:
        return value
    if isinstance(value, dict):
        return {
            key: REDACTED if _is_sensitive(str(key)) else _scrub(item, depth + 1)
            for key, item in value.items()
        }
    if isinstance(value, list | tuple):
        return type(value)(_scrub(item, depth + 1) for item in value)
    return value


def redact_processor(
    _logger: Any, _name: str, event_dict: MutableMapping[str, Any]
) -> Mapping[str, Any]:
    return dict(_scrub(dict(event_dict), 0))
