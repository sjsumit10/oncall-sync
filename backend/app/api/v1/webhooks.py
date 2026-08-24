"""Inbound provider webhooks.

Unauthenticated by nature: the caller is Slack, not a logged-in user. The request
signature is the only thing that establishes trust, so it is verified against the
raw body before anything else happens.
"""

from typing import Any

import structlog
from fastapi import APIRouter, Request, Response, status

from app.core.deps import DbSession
from app.db.session import bind_org
from app.providers.chat.slack.events import (
    SIGNATURE_HEADER,
    TIMESTAMP_HEADER,
    is_valid_signature,
)
from app.services import chat_connections

router = APIRouter(prefix="/webhooks", tags=["webhooks"])
log = structlog.get_logger(__name__)

SLACK_KIND = "slack"
#: Events meaning "this install is dead". Both arrive when an app is removed or
#: its tokens are revoked from the workspace's app management screen.
REVOCATION_EVENTS = frozenset({"app_uninstalled", "tokens_revoked"})


@router.post("/slack/events")
async def slack_events(request: Request, db: DbSession) -> Any:
    """Handle Slack's Events API.

    Always answers 2xx once the signature checks out. Slack retries any non-2xx
    up to three times, so returning an error for an event we simply do not act on
    would generate pointless duplicate deliveries.
    """
    body = await request.body()
    if not is_valid_signature(
        body=body,
        timestamp=request.headers.get(TIMESTAMP_HEADER, ""),
        signature=request.headers.get(SIGNATURE_HEADER, ""),
    ):
        log.warning("slack.events.bad_signature")
        return Response(status_code=status.HTTP_401_UNAUTHORIZED)

    payload = await request.json()
    event_type = payload.get("type")

    # One-time handshake when the endpoint is registered in the app config.
    if event_type == "url_verification":
        return {"challenge": payload.get("challenge", "")}

    if event_type != "event_callback":
        return Response(status_code=status.HTTP_200_OK)

    event = payload.get("event") or {}
    inner_type = event.get("type")
    team_id = payload.get("team_id") or ""

    # The lookup spans tenants because a signed Slack request identifies a
    # workspace, not an organization. Every write below binds the org first.
    connections = await chat_connections.find_by_team_id(
        db, kind=SLACK_KIND, external_team_id=team_id
    )

    if inner_type in REVOCATION_EVENTS:
        for connection in connections:
            await bind_org(db, connection.org_id)
            await chat_connections.mark_revoked(
                db, connection, f"Slack reported {inner_type}; reinstall required"
            )
        log.info("slack.events.revoked", team_id=team_id, connections=len(connections))

    elif inner_type == "subteam_updated":
        # Someone edited a user group by hand. M5 turns this into an immediate
        # reconcile; until then it is recorded so drift is at least visible.
        log.info(
            "slack.events.subteam_updated",
            team_id=team_id,
            subteam=(event.get("subteam") or {}).get("id"),
        )

    return Response(status_code=status.HTTP_200_OK)
