"""Redaction of secrets (always, before persistence) and PII (per viewer, at response time)."""
import re
from typing import Any

_SECRET_KEY = re.compile(r"(password|passwd|secret|token|api[_-]?key|authorization|credential|private[_-]?key)", re.I)
# Token *counts* (input_tokens, max_total_tokens, ...) are metrics, not credentials.
_COUNTER_KEY = re.compile(r"(^|_)(tokens?|input_tokens|output_tokens|total_tokens|prompt_tokens|completion_tokens)$|_tokens(_|$)", re.I)
PII_KEYS = {"base_salary", "salary", "bank_account", "bank_account_last4", "tax_bracket"}
MASK = "[REDACTED]"
PII_MASK = "[RESTRICTED]"


def _is_secret(key: Any) -> bool:
    k = str(key)
    if _COUNTER_KEY.search(k) and not re.search(r"(access|auth|api|bearer|refresh|secret|session|id)_?token", k, re.I) and k.lower() != "token":
        return False
    return bool(_SECRET_KEY.search(k))


def redact_secrets(value: Any) -> Any:
    if isinstance(value, dict):
        return {k: (MASK if _is_secret(k) else redact_secrets(v)) for k, v in value.items()}
    if isinstance(value, list):
        return [redact_secrets(v) for v in value]
    return value


def mask_pii(value: Any) -> Any:
    if isinstance(value, dict):
        return {k: (PII_MASK if str(k).lower() in PII_KEYS else mask_pii(v)) for k, v in value.items()}
    if isinstance(value, list):
        return [mask_pii(v) for v in value]
    return value


def view_for(value: Any, can_read_pii: bool) -> Any:
    """Final response-time filter: secrets are always masked; PII only for permitted viewers."""
    value = redact_secrets(value)
    return value if can_read_pii else mask_pii(value)
