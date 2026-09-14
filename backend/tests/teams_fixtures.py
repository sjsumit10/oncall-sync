"""Canned Microsoft Graph API payloads."""

from typing import Any

API = "https://graph.microsoft.com/v1.0"
TOKEN_URL = "https://login.microsoftonline.com/organizations/oauth2/v2.0/token"


def err(code: str, message: str = "boom") -> dict[str, Any]:
    return {"error": {"code": code, "message": message}}


def token_response(
    *, access_token: str = "graph-access-token", with_refresh: bool = True, expires_in: int = 3600
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "token_type": "Bearer",
        "access_token": access_token,
        "expires_in": expires_in,
        "scope": "TeamworkTag.ReadWrite Team.ReadBasic.All ChannelMessage.Send",
    }
    if with_refresh:
        payload["refresh_token"] = "graph-refresh-token"
    return payload


def organization(*, tenant_id: str = "TENANT1", name: str = "Acme Corp") -> dict[str, Any]:
    return {"value": [{"id": tenant_id, "displayName": name}]}


def tag(external_id: str, name: str) -> dict[str, Any]:
    return {"id": external_id, "displayName": name}


def tags_page(items: list[dict[str, Any]]) -> dict[str, Any]:
    return {"value": items}


def tag_member(member_id: str, user_id: str) -> dict[str, Any]:
    return {"id": member_id, "userId": user_id, "tenantId": "TENANT1"}


def channel(external_id: str, name: str, *, private: bool = False) -> dict[str, Any]:
    return {
        "id": external_id,
        "displayName": name,
        "membershipType": "private" if private else "standard",
    }


def graph_user(external_id: str, name: str, email: str) -> dict[str, Any]:
    return {"id": external_id, "displayName": name, "mail": email}


def me(*, display_name: str = "Ada Lovelace", upn: str = "ada@acme.dev") -> dict[str, Any]:
    return {"displayName": display_name, "userPrincipalName": upn}
