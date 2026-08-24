"""PagerDuty OAuth 2.0 authorization code flow with PKCE.

Endpoints and scope names per PagerDuty's scoped-OAuth documentation. PKCE is
used even though this is a confidential client: it costs one hash and removes
authorization-code interception from the threat model entirely.
"""

import base64
import hashlib
import secrets
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import urlencode

import httpx

from app.config import get_settings
from app.core.http import ProviderAuthError, request
from app.domain.types import OAuthTokens

AUTHORIZE_URL = "https://identity.pagerduty.com/oauth/authorize"
TOKEN_URL = "https://identity.pagerduty.com/oauth/token"  # noqa: S105 (a URL, not a secret)
#: Read-only: this product never writes to PagerDuty.
DEFAULT_SCOPES = ("schedules.read", "oncalls.read", "users.read")


def generate_pkce_pair() -> tuple[str, str]:
    """Return ``(verifier, challenge)`` for the S256 method."""
    verifier = secrets.token_urlsafe(64)
    digest = hashlib.sha256(verifier.encode()).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode()
    return verifier, challenge


def authorize_url(*, state: str, redirect_uri: str, code_challenge: str) -> str:
    settings = get_settings()
    query = urlencode(
        {
            "response_type": "code",
            "client_id": settings.pagerduty_client_id,
            "redirect_uri": redirect_uri,
            "scope": " ".join(DEFAULT_SCOPES),
            "state": state,
            "code_challenge": code_challenge,
            "code_challenge_method": "S256",
        }
    )
    return f"{AUTHORIZE_URL}?{query}"


def _to_tokens(payload: dict[str, Any]) -> OAuthTokens:
    expires_in = payload.get("expires_in")
    expires_at = (
        datetime.now(UTC) + timedelta(seconds=int(expires_in)) if expires_in is not None else None
    )
    return OAuthTokens(
        access_token=payload["access_token"],
        refresh_token=payload.get("refresh_token"),
        expires_at=expires_at,
        scope=payload.get("scope"),
    )


async def _token_request(form: dict[str, str]) -> OAuthTokens:
    settings = get_settings()
    body = {
        **form,
        "client_id": settings.pagerduty_client_id,
        "client_secret": settings.pagerduty_client_secret.get_secret_value(),
    }
    async with httpx.AsyncClient(timeout=httpx.Timeout(20.0)) as client:
        try:
            response = await request(client, "POST", TOKEN_URL, data=body)
        except ProviderAuthError as exc:
            raise ProviderAuthError(f"PagerDuty rejected the token request: {exc}") from exc
    return _to_tokens(response.json())


async def exchange_code(*, code: str, redirect_uri: str, code_verifier: str) -> OAuthTokens:
    return await _token_request(
        {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": redirect_uri,
            "code_verifier": code_verifier,
        }
    )


async def refresh(*, refresh_token: str) -> OAuthTokens:
    return await _token_request({"grant_type": "refresh_token", "refresh_token": refresh_token})


class PagerDutyOAuth:
    """Object form of this module, satisfying the OAuthFlow protocol."""

    kind = "pagerduty"

    def authorize_url(self, *, state: str, redirect_uri: str, code_challenge: str) -> str:
        return authorize_url(state=state, redirect_uri=redirect_uri, code_challenge=code_challenge)

    async def exchange_code(
        self, *, code: str, redirect_uri: str, code_verifier: str
    ) -> OAuthTokens:
        return await exchange_code(
            code=code, redirect_uri=redirect_uri, code_verifier=code_verifier
        )

    async def refresh(self, *, refresh_token: str) -> OAuthTokens:
        return await refresh(refresh_token=refresh_token)
