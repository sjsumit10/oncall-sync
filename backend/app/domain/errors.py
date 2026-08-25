"""Provider-neutral failures.

These are conditions the sync engine has to reason about — "the plan does not
include group handles", "we are not allowed to write this group", "the platform
refuses an empty group" — so they belong to the domain rather than to any one
adapter. Vendors raise them; nothing outside app/providers/ needs to know which
vendor did.
"""


class ChatProviderError(RuntimeError):
    """Base class for chat-platform problems the engine handles deliberately."""


class GroupsUnavailable(ChatProviderError):
    """This workspace's plan does not include mentionable group handles."""


class GroupWriteNotPermitted(ChatProviderError):
    """The workspace restricts who may manage groups, and we are not on the list."""


class EmptyMembershipRejected(ChatProviderError):
    """The platform refuses a group with no members — and so do we."""
