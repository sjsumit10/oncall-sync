"""Generic OAuth 2.0 helpers.

PKCE is plain RFC 7636, not vendor machinery, so it lives here rather than in any
one provider adapter.
"""

import base64
import hashlib
import secrets

VERIFIER_BYTES = 64


def generate_pkce_pair() -> tuple[str, str]:
    """Return ``(verifier, challenge)`` for the S256 method."""
    verifier = secrets.token_urlsafe(VERIFIER_BYTES)
    digest = hashlib.sha256(verifier.encode()).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode()
    return verifier, challenge
