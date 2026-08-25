"""Message templates: the sandbox, the allowlist, and Block Kit rendering."""

from datetime import UTC, datetime

import pytest

from app.domain.types import Announcement
from app.providers.chat.slack import blocks as block_kit
from app.services import templating
from app.services.templating import SAMPLE_CONTEXT


def test_the_default_template_reads_well() -> None:
    text, problem = templating.safe_render(None, SAMPLE_CONTEXT)

    assert problem is None
    assert "<@U024BE7LH> is now on call" in text
    assert "`@devops-on-call`" in text
    assert "Thanks Grace Hopper" in text


def test_optional_sections_disappear_when_empty() -> None:
    """A first-ever sync has no outgoing person to thank."""
    context = templating.MessageContext(
        **{**SAMPLE_CONTEXT.as_dict(), "previous_name": "", "shift_end": ""}
    )
    text, _ = templating.safe_render(None, context)

    assert "Thanks" not in text
    assert "until" not in text
    assert "<@U024BE7LH> is now on call" in text


@pytest.mark.parametrize(
    "template",
    [
        "{{ oncall_mention }} is up",
        "{% if previous_name %}Bye {{ previous_name }}{% endif %}",
        "{{ schedule_name }} / {{ handle }} / {{ shift_end }}",
    ],
)
def test_valid_templates_pass_validation(template: str) -> None:
    assert templating.validate(template) == []


def test_unknown_variables_are_rejected_at_save_time() -> None:
    """Better a refused save than a blank at 3am on the actual handoff."""
    problems = templating.validate("Paging {{ oncall_manager }} now")

    assert problems
    assert "oncall_manager" in problems[0]
    assert "Available:" in problems[0]


def test_syntax_errors_are_reported() -> None:
    problems = templating.validate("{{ unclosed ")
    assert problems and "syntax error" in problems[0].lower()


def test_loops_are_refused() -> None:
    """No loop is ever needed here, and without them no template can run away."""
    problems = templating.validate("{% for x in [1,2] %}{{ x }}{% endfor %}")
    assert problems == ["Loops are not allowed in message templates"]


@pytest.mark.parametrize(
    "template",
    [
        "{{ ''.__class__ }}",
        "{{ oncall_name.__class__.__mro__ }}",
        "{{ ''.__class__.__mro__[1].__subclasses__() }}",
        "{{ oncall_name.upper() }}",
        "{{ oncall_name[0] }}",
    ],
)
def test_sandbox_escape_probes_are_refused_when_saved(template: str) -> None:
    """The classic Jinja escapes are rejected outright, not silently blanked."""
    assert templating.validate(template) != []


@pytest.mark.parametrize("template", ["{{ ''.__class__ }}", "{{ oncall_name.__class__.__mro__ }}"])
def test_the_sandbox_leaks_nothing_even_if_a_probe_is_rendered(template: str) -> None:
    """Belt and braces: validation refuses these, and the sandbox contains them anyway."""
    try:
        rendered = templating.render(template, SAMPLE_CONTEXT)
    except Exception:
        return  # raising is a perfectly good outcome
    assert "class" not in rendered
    assert "subclass" not in rendered
    assert "object" not in rendered


def test_an_overlong_template_is_refused() -> None:
    problems = templating.validate("x" * (templating.MAX_TEMPLATE_LENGTH + 1))
    assert problems and "longer than" in problems[0]


def test_a_template_that_fails_at_render_time_falls_back() -> None:
    """The membership update already happened; the message must not take it down."""
    text, problem = templating.safe_render("{{ oncall_name / 0 }}", SAMPLE_CONTEXT)

    assert problem is not None
    assert "sent the default instead" in problem
    # And what went out is still a usable handoff notice.
    assert "<@U024BE7LH> is now on call" in text


def test_rendered_output_is_capped() -> None:
    text = templating.render("{{ oncall_name }}" + "y" * 5000, SAMPLE_CONTEXT)
    assert len(text) <= templating.MAX_RENDERED_LENGTH


class TestBlockKit:
    def test_the_body_becomes_a_mrkdwn_section(self) -> None:
        blocks = block_kit.build(Announcement(text="*Ada* is on call"))

        assert blocks[0] == {
            "type": "section",
            "text": {"type": "mrkdwn", "text": "*Ada* is on call"},
        }

    def test_context_carries_schedule_handle_and_shift_end(self) -> None:
        blocks = block_kit.build(
            Announcement(
                text="body",
                schedule_name="Primary",
                handle="devops-on-call",
                shift_end=datetime(2026, 8, 26, 9, tzinfo=UTC),
            )
        )
        context = blocks[1]["elements"][0]["text"]

        assert "*Primary*" in context
        assert "`@devops-on-call`" in context
        # Rendered in each reader's own timezone, with a UTC fallback.
        assert "<!date^" in context
        assert "26 Aug, 09:00 UTC" in context

    def test_a_bare_announcement_has_no_context_block(self) -> None:
        blocks = block_kit.build(Announcement(text="just this", kind="problem"))
        assert len(blocks) == 1

    def test_the_fallback_text_stands_on_its_own(self) -> None:
        """It is what notifications and screen readers get."""
        announcement = Announcement(text="Ada is now on call for @devops-on-call")
        assert block_kit.notification_text(announcement) == announcement.text
