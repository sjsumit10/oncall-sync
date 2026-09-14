"""Microsoft identity platform OAuth 2.0 authorization code flow with PKCE.

Delegated scopes, not app-only: Graph has no application-permission variant of
ChannelMessage.Send (posting into a channel), so a signed-in user's token is
required for the one call this product cannot do without.

No ``prompt=admin_consent`` here — that value is only valid on the dedicated
``/adminconsent`` endpoint (a separate, code-less flow) and is rejected with
AADSTS901001 on the regular ``/authorize`` endpoint used below. It isn't
needed anyway: every scope requested is already marked admin-consent-required
by Graph, so a genuine tenant admin going through the normal authorize flow
gets a "Consent on behalf of your organization" checkbox, which grants it
tenant-wide on its own — the same "one admin approves, covers everyone" UX,
via the standard flow rather than a special parameter. That token expires and
needs the refresh flow below (unlike Slack's bot token, which never does).
"""

from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import urlencode

import httpx

from app.config import get_settings
from app.core.http import ProviderAuthError, request
from app.core.oauth import generate_pkce_pair
from app.domain.types import ChatInstall, OAuthTokens

AUTHORIZE_URL = "https://login.microsoftonline.com/organizations/oauth2/v2.0/authorize"
TOKEN_URL = "https://login.microsoftonline.com/organizations/oauth2/v2.0/token"  # noqa: S105
GRAPH_BASE = "https://graph.microsoft.com/v1.0"

#: offline_access is what makes the token endpoint hand back a refresh_token.
SCOPES = (
    "TeamworkTag.ReadWrite",
    "Team.ReadBasic.All",
    "Channel.ReadBasic.All",
    "ChannelMessage.Send",
    "User.Read.All",
    "offline_access",
)


def install_url(*, state: str, redirect_uri: str, code_challenge: str) -> str:
    settings = get_settings()
    query = urlencode(
        {
            "client_id": settings.teams_client_id,
            "response_type": "code",
            "redirect_uri": redirect_uri,
            "scope": " ".join(SCOPES),
            "state": state,
            "code_challenge": code_challenge,
            "code_challenge_method": "S256",
            # Force the consent screen every time rather than silently reusing
            # a prior, narrower grant — a scope added after someone already
            # consented would otherwise fail at call time instead of here.
            "prompt": "consent",
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
        "client_id": settings.teams_client_id,
        "client_secret": settings.teams_client_secret.get_secret_value(),
    }
    async with httpx.AsyncClient(timeout=httpx.Timeout(20.0)) as client:
        try:
            response = await request(client, "POST", TOKEN_URL, data=body)
        except ProviderAuthError as exc:
            raise ProviderAuthError(f"Microsoft rejected the token request: {exc}") from exc
    return _to_tokens(response.json())


async def _organization(access_token: str) -> dict[str, Any]:
    """The tenant's own organization record: id + display name.

    Graph's token response gives back a tenant id claim but not a display
    name, and we only requested Graph scopes (not OIDC id_token claims), so
    this costs one extra round trip Slack's install flow doesn't need.
    """
    async with httpx.AsyncClient(timeout=httpx.Timeout(20.0)) as client:
        response = await request(
            client,
            "GET",
            f"{GRAPH_BASE}/organization",
            headers={"Authorization": f"Bearer {access_token}"},
        )
    orgs = response.json().get("value") or []
    return dict(orgs[0]) if orgs else {}


async def complete_install(*, code: str, redirect_uri: str, code_verifier: str) -> ChatInstall:
    tokens = await _token_request(
        {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": redirect_uri,
            "code_verifier": code_verifier,
        }
    )
    org = await _organization(tokens.access_token)

    return ChatInstall(
        external_team_id=str(org.get("id", "")),
        team_name=str(org.get("displayName") or "Microsoft Teams"),
        bot_token=tokens.access_token,
        scopes=tokens.scope,
        refresh_token=tokens.refresh_token,
        token_expires_at=tokens.expires_at,
    )


async def refresh(*, refresh_token: str) -> OAuthTokens:
    return await _token_request({"grant_type": "refresh_token", "refresh_token": refresh_token})


class TeamsOAuth:
    """Object form of this module, satisfying ChatOAuthRefresh."""

    kind = "teams"

    def install_url(self, *, state: str, redirect_uri: str, code_challenge: str) -> str:
        return install_url(state=state, redirect_uri=redirect_uri, code_challenge=code_challenge)

    async def complete_install(
        self, *, code: str, redirect_uri: str, code_verifier: str
    ) -> ChatInstall:
        return await complete_install(
            code=code, redirect_uri=redirect_uri, code_verifier=code_verifier
        )

    async def refresh(self, *, refresh_token: str) -> OAuthTokens:
        return await refresh(refresh_token=refresh_token)


__all__ = [
    "AUTHORIZE_URL",
    "SCOPES",
    "TOKEN_URL",
    "TeamsOAuth",
    "complete_install",
    "generate_pkce_pair",
    "install_url",
    "refresh",
]
