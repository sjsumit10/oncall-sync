"""Handoff message templates.

Templates are written by users, so they are rendered in a Jinja sandbox with a
fixed variable allowlist. Two restrictions beyond the sandbox:

* **No loops, attribute access, subscripting or calls.** A one-line handoff
  notice needs none of them, so the sandbox becomes a second line of defence
  rather than the only one.
* **Unknown variables are rejected when the template is saved**, not silently
  blanked at 3am when the handoff actually fires.

Rendering is also non-fatal by design: if a template somehow fails at run time,
the handle still gets updated and the built-in default is sent instead. A typo in
a message must never stop the group from pointing at the right person.
"""

from dataclasses import dataclass
from datetime import datetime

import structlog
from jinja2 import TemplateError, meta, nodes
from jinja2.sandbox import SandboxedEnvironment

log = structlog.get_logger(__name__)

MAX_TEMPLATE_LENGTH = 2000
MAX_RENDERED_LENGTH = 3000

DEFAULT_TEMPLATE = (
    ":pager: *On-call handoff — {{ schedule_name }}*\n"
    "{{ oncall_mention }} is now on call for `@{{ handle }}`"
    "{% if shift_end %} until {{ shift_end }}{% endif %}."
    "{% if previous_name %}\nThanks {{ previous_name }}! :wave:{% endif %}"
)

#: Everything a template may reference. Anything else is a save-time error.
ALLOWED_VARIABLES = frozenset(
    {
        "schedule_name",
        "rule_name",
        "handle",
        "oncall_mention",
        "oncall_name",
        "previous_mention",
        "previous_name",
        "shift_start",
        "shift_end",
    }
)

_env = SandboxedEnvironment(
    # Slack messages are plain text, not HTML; escaping would mangle mrkdwn.
    autoescape=False,
    trim_blocks=False,
    keep_trailing_newline=False,
)


@dataclass(frozen=True, slots=True)
class MessageContext:
    schedule_name: str
    rule_name: str
    handle: str | None
    oncall_mention: str
    oncall_name: str
    previous_mention: str
    previous_name: str
    shift_start: str
    shift_end: str

    def as_dict(self) -> dict[str, str]:
        return {
            "schedule_name": self.schedule_name,
            "rule_name": self.rule_name,
            "handle": self.handle or "",
            "oncall_mention": self.oncall_mention,
            "oncall_name": self.oncall_name,
            "previous_mention": self.previous_mention,
            "previous_name": self.previous_name,
            "shift_start": self.shift_start,
            "shift_end": self.shift_end,
        }


SAMPLE_CONTEXT = MessageContext(
    schedule_name="Primary",
    rule_name="DevOps on-call",
    handle="devops-on-call",
    oncall_mention="<@U024BE7LH>",
    oncall_name="Ada Lovelace",
    previous_mention="<@U0G9QF9C6>",
    previous_name="Grace Hopper",
    shift_start="Mon 25 Aug, 09:00 UTC",
    shift_end="Tue 26 Aug, 09:00 UTC",
)


def format_time(moment: datetime | None) -> str:
    return moment.strftime("%a %d %b, %H:%M UTC") if moment else ""


def validate(template: str) -> list[str]:
    """Return human-readable problems with a template. Empty means it is fine."""
    problems: list[str] = []
    if len(template) > MAX_TEMPLATE_LENGTH:
        problems.append(f"Template is longer than {MAX_TEMPLATE_LENGTH} characters")
        return problems

    try:
        parsed = _env.parse(template)
    except TemplateError as exc:
        return [f"Template syntax error: {exc}"]

    unknown = sorted(meta.find_undeclared_variables(parsed) - ALLOWED_VARIABLES)
    if unknown:
        available = ", ".join(sorted(ALLOWED_VARIABLES))
        problems.append(
            f"Unknown variable{'s' if len(unknown) > 1 else ''}: {', '.join(unknown)}. "
            f"Available: {available}"
        )

    if next(parsed.find_all(nodes.For), None) is not None:
        problems.append("Loops are not allowed in message templates")

    # A handoff notice only ever substitutes plain values. Refusing attribute
    # access, subscripting and calls outright means the sandbox is a second line
    # of defence rather than the only one — and a probe like {{ ''.__class__ }}
    # is refused when it is saved instead of silently rendering as nothing.
    if next(parsed.find_all((nodes.Getattr, nodes.Getitem)), None) is not None:
        problems.append("Attribute and index access are not allowed in message templates")
    if next(parsed.find_all(nodes.Call), None) is not None:
        problems.append("Function calls are not allowed in message templates")

    return problems


def render(template: str, context: MessageContext) -> str:
    rendered = _env.from_string(template).render(**context.as_dict())
    return rendered.strip()[:MAX_RENDERED_LENGTH]


def safe_render(template: str | None, context: MessageContext) -> tuple[str, str | None]:
    """Render, falling back to the default on any failure.

    Returns ``(text, problem)``. A broken template degrades the message, never the
    membership update that matters.
    """
    if template:
        try:
            return render(template, context), None
        except Exception as exc:
            log.warning("template.render_failed", error=str(exc))
            problem = f"Message template failed to render ({exc}); sent the default instead"
            try:
                return render(DEFAULT_TEMPLATE, context), problem
            except Exception:
                return _fallback(context), problem

    try:
        return render(DEFAULT_TEMPLATE, context), None
    except Exception:
        return _fallback(context), None


def _fallback(context: MessageContext) -> str:
    """Last resort, with no templating involved at all."""
    return f"{context.oncall_mention} is now on call for {context.schedule_name}."
