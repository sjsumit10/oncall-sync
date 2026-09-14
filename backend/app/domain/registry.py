"""Provider lookup.

Adding a provider is a new package plus one line in each mapping here. The API
exposes this registry directly, so the UI renders whatever is registered rather
than carrying its own hardcoded list.
"""

from app.domain.interfaces import ChatOAuthRefresh, ChatProvider, OAuthFlow, OncallProvider
from app.providers.chat.slack.provider import SlackProvider
from app.providers.chat.teams.provider import TeamsProvider
from app.providers.oncall.pagerduty.oauth import PagerDutyOAuth
from app.providers.oncall.pagerduty.provider import PagerDutyProvider

ONCALL_PROVIDERS: dict[str, OncallProvider] = {
    PagerDutyProvider.kind: PagerDutyProvider(),
}

#: Only providers that support AuthMode.OAUTH appear here.
ONCALL_OAUTH_FLOWS: dict[str, OAuthFlow] = {
    PagerDutyOAuth.kind: PagerDutyOAuth(),
}


CHAT_PROVIDERS: dict[str, ChatProvider] = {
    SlackProvider.kind: SlackProvider(),
    TeamsProvider.kind: TeamsProvider(),
}

#: Only chat providers whose installed token expires (Teams) appear here.
CHAT_OAUTH_REFRESH: dict[str, ChatOAuthRefresh] = {
    TeamsProvider.kind: TeamsProvider(),
}


def get_oncall_provider(kind: str) -> OncallProvider:
    try:
        return ONCALL_PROVIDERS[kind]
    except KeyError:
        raise LookupError(f"Unknown on-call provider: {kind}") from None


def get_oncall_oauth(kind: str) -> OAuthFlow:
    try:
        return ONCALL_OAUTH_FLOWS[kind]
    except KeyError:
        raise LookupError(f"{kind} does not support OAuth") from None


def get_chat_provider(kind: str) -> ChatProvider:
    try:
        return CHAT_PROVIDERS[kind]
    except KeyError:
        raise LookupError(f"Unknown chat provider: {kind}") from None


def get_chat_oauth_refresh(kind: str) -> ChatOAuthRefresh | None:
    """None (not a raise) for a provider whose token never expires — e.g. Slack."""
    return CHAT_OAUTH_REFRESH.get(kind)
