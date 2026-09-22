"""Outbound email via SMTP.

One thin wrapper so nothing else in the app touches an SMTP connection
directly. An unconfigured deployment raises immediately rather than pretending
to have sent something — the same "fail loud, not silently" choice
app/core/crypto.py makes when CREDENTIAL_KEK is unset.
"""

from email.message import EmailMessage

import aiosmtplib
import certifi

from app.config import get_settings


class EmailNotConfigured(RuntimeError):
    """SMTP_HOST (or SMTP_FROM_EMAIL) is unset; nothing can be sent."""


async def send_email(*, to: str, subject: str, body: str) -> None:
    settings = get_settings()
    if not settings.smtp_host or not settings.smtp_from_email:
        raise EmailNotConfigured("SMTP is not configured; refusing to send email")

    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = f"{settings.smtp_from_name} <{settings.smtp_from_email}>"
    message["To"] = to
    message.set_content(body)

    await aiosmtplib.send(
        message,
        hostname=settings.smtp_host,
        port=settings.smtp_port,
        username=settings.smtp_username or None,
        password=settings.smtp_password.get_secret_value() or None,
        use_tls=settings.smtp_use_tls,
        # The stdlib default SSL context trusts the OS certificate store, which
        # a python.org macOS build doesn't wire up — certifi's bundle works
        # the same way everywhere instead.
        cert_bundle=certifi.where(),
    )
