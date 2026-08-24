"""Slack request signature verification.

Every request from Slack is signed. Verification happens on the raw body before
any parsing, because a signature over re-serialized JSON proves nothing.
"""

import hashlib
import hmac
import time

from app.config import get_settings

SIGNATURE_HEADER = "X-Slack-Signature"
TIMESTAMP_HEADER = "X-Slack-Request-Timestamp"
VERSION = "v0"
#: Slack's recommended replay window.
MAX_SKEW_SECONDS = 60 * 5


def is_valid_signature(*, body: bytes, timestamp: str, signature: str) -> bool:
    secret = get_settings().slack_signing_secret.get_secret_value()
    if not secret or not timestamp or not signature:
        return False

    try:
        sent_at = int(timestamp)
    except ValueError:
        return False
    if abs(time.time() - sent_at) > MAX_SKEW_SECONDS:
        return False

    basestring = f"{VERSION}:{timestamp}:".encode() + body
    expected = f"{VERSION}=" + hmac.new(secret.encode(), basestring, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature)
