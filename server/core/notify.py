"""
Send alert notifications by push (ntfy) and/or email.

Channels are configured in ``server/.env``; any that are not configured are
skipped:

* **Push**: ``NTFY_URL`` (e.g. ``https://ntfy.sh/<your-secret-topic>``, or a
  self-hosted ntfy server) and optionally ``NTFY_TOKEN``. Install the ntfy app
  on a phone and subscribe to the same topic.
* **Email**: ``SMTP_HOST``, ``SMTP_PORT`` (587 uses STARTTLS, 465 SSL),
  ``SMTP_USER``, ``SMTP_PASSWORD``, ``ALERT_EMAIL_FROM``, ``ALERT_EMAIL_TO``
  (comma-separated).

With no channel configured, alerts are only logged (and shown on Home).
"""
import logging
import smtplib
from email.message import EmailMessage

from requests import post

from core import settings

log = logging.getLogger(__name__)

TIMEOUT_S = 10


def configured_channels() -> list[str]:
    """
    List the channels that have enough settings to be used.

    Returns:
        list[str]: Any of ``"ntfy"`` and ``"email"``.
    """
    channels = []
    if settings.NTFY_URL:
        channels.append("ntfy")
    if settings.SMTP_HOST and settings.ALERT_EMAIL_TO:
        channels.append("email")
    return channels


def send_ntfy(title: str, message: str, urgent: bool = False) -> bool:
    """
    Send a push notification through ntfy.

    Args:
        title (str): Notification title.
        message (str): Body text.
        urgent (bool): Use high priority (phones may alert louder).

    Returns:
        bool: True if the server accepted it.
    """
    headers = {"Title": title, "Priority": "high" if urgent else "default", "Tags": "seedling"}
    if settings.NTFY_TOKEN:
        headers["Authorization"] = f"Bearer {settings.NTFY_TOKEN}"
    try:
        response = post(settings.NTFY_URL, data=message.encode("utf-8"), headers=headers, timeout=TIMEOUT_S)
        response.raise_for_status()
    except Exception as err:
        log.error("ntfy notification failed: %s", err)
        return False
    return True


def send_email(subject: str, body: str) -> bool:
    """
    Send an email through the configured SMTP server.

    Args:
        subject (str): Subject line.
        body (str): Plain-text body.

    Returns:
        bool: True if the server accepted it.
    """
    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = settings.ALERT_EMAIL_FROM or settings.SMTP_USER or "greenhouse@localhost"
    message["To"] = settings.ALERT_EMAIL_TO
    message.set_content(body)
    try:
        if settings.SMTP_PORT == 465:
            server = smtplib.SMTP_SSL(settings.SMTP_HOST, settings.SMTP_PORT, timeout=TIMEOUT_S)
        else:
            server = smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT, timeout=TIMEOUT_S)
        with server:
            if settings.SMTP_PORT == 587:
                server.starttls()
            if settings.SMTP_USER:
                server.login(settings.SMTP_USER, settings.SMTP_PASSWORD or "")
            server.send_message(message)
    except (OSError, smtplib.SMTPException) as err:
        log.error("Email notification failed: %s", err)
        return False
    return True


def deliver(title: str, message: str, urgent: bool = False) -> bool:
    """
    Send a notification on every configured channel.

    Args:
        title (str): Short title / subject.
        message (str): Body text.
        urgent (bool): High priority where the channel supports it.

    Returns:
        bool: True if at least one channel accepted it, or if no channel is
        configured (log-only mode: nothing to retry).
    """
    channels = configured_channels()
    log.warning("ALERT %s: %s", title, message)
    if not channels:
        return True
    results = []
    if "ntfy" in channels:
        results.append(send_ntfy(title, message, urgent))
    if "email" in channels:
        results.append(send_email(f"[Greenhouse] {title}", message))
    return any(results)
