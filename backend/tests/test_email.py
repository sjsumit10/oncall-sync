"""The SMTP wrapper: refuses to send when unconfigured, builds the message
correctly when it is."""

from typing import Any

import aiosmtplib
import pytest
from pydantic import SecretStr

from app.config import get_settings
from app.services.email import EmailNotConfigured, send_email


async def test_refuses_to_send_without_smtp_host(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = get_settings()
    monkeypatch.setattr(settings, "smtp_host", "")

    with pytest.raises(EmailNotConfigured):
        await send_email(to="ada@acme.dev", subject="Hi", body="Body")


async def test_refuses_to_send_without_a_from_address(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = get_settings()
    monkeypatch.setattr(settings, "smtp_host", "smtp.example.com")
    monkeypatch.setattr(settings, "smtp_from_email", "")

    with pytest.raises(EmailNotConfigured):
        await send_email(to="ada@acme.dev", subject="Hi", body="Body")


async def test_sends_a_correctly_addressed_message(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = get_settings()
    monkeypatch.setattr(settings, "smtp_host", "smtp.example.com")
    monkeypatch.setattr(settings, "smtp_port", 587)
    monkeypatch.setattr(settings, "smtp_username", "apikey")
    monkeypatch.setattr(settings, "smtp_password", SecretStr("secret"))
    monkeypatch.setattr(settings, "smtp_from_email", "no-reply@oncall-sync.dev")
    monkeypatch.setattr(settings, "smtp_from_name", "On-Call Sync")

    calls: list[dict[str, Any]] = []

    async def fake_send(message: Any, **kwargs: Any) -> tuple[dict[str, Any], str]:
        calls.append({"message": message, **kwargs})
        return {}, "OK"

    monkeypatch.setattr(aiosmtplib, "send", fake_send)

    await send_email(to="ada@acme.dev", subject="Reset your password", body="Click here")

    assert len(calls) == 1
    call = calls[0]
    assert call["hostname"] == "smtp.example.com"
    assert call["port"] == 587
    assert call["username"] == "apikey"
    assert call["password"] == "secret"

    message = call["message"]
    assert message["To"] == "ada@acme.dev"
    assert message["From"] == "On-Call Sync <no-reply@oncall-sync.dev>"
    assert message["Subject"] == "Reset your password"
    assert "Click here" in message.get_content()
