"""Email sending utilities adapted for the FastAPI backend."""

from __future__ import annotations

import structlog
import os
import smtplib
import time
from dataclasses import dataclass
from email.message import EmailMessage
from typing import Optional

logger = structlog.get_logger(__name__)


@dataclass
class EmailConfig:
    """Runtime configuration for the SMTP email backend."""

    backend: str
    host: Optional[str]
    port: int
    username: Optional[str]
    password: Optional[str]
    use_tls: bool
    use_ssl: bool
    timeout: Optional[str]
    max_retries: int
    retry_delay: float
    from_address: str
    subject: str


class EmailSenderError(RuntimeError):
    """Raised when the configured email backend cannot deliver a message."""

    def __init__(self, message: str, *, original: Exception | None = None):
        super().__init__(message)
        self.original = original


def _env_bool(key: str, default: bool = False) -> bool:
    value = os.getenv(key)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _env_int(key: str, default: int) -> int:
    value = os.getenv(key)
    if value is None:
        return default
    try:
        return int(value)
    except (TypeError, ValueError):  # pragma: no cover - defensive
        logger.warning(
            "Invalid integer for %s=%s. Falling back to %s.", key, value, default
        )
        return default


def _env_float(key: str, default: float) -> float:
    value = os.getenv(key)
    if value is None:
        return default
    try:
        return float(value)
    except (TypeError, ValueError):  # pragma: no cover - defensive
        logger.warning(
            "Invalid float for %s=%s. Falling back to %s.", key, value, default
        )
        return default


def _load_email_config() -> EmailConfig:
    backend = os.getenv("EMAIL_BACKEND", "console").strip().lower()
    from_address = (
        os.getenv("EMAIL_FROM_ADDRESS")
        or os.getenv("SMTP_FROM_ADDRESS")
        or "no-reply@example.com"
    )

    subject = os.getenv("EMAIL_MAGIC_LINK_SUBJECT", "Your magic login link")

    return EmailConfig(
        backend=backend,
        host=os.getenv("SMTP_HOST"),
        port=_env_int("SMTP_PORT", 587),
        username=os.getenv("SMTP_USERNAME"),
        password=os.getenv("SMTP_PASSWORD"),
        use_tls=_env_bool("SMTP_USE_TLS", True),
        use_ssl=_env_bool("SMTP_USE_SSL", False),
        timeout=os.getenv("SMTP_TIMEOUT"),
        max_retries=max(1, _env_int("EMAIL_MAX_RETRIES", 3)),
        retry_delay=max(0.0, _env_float("EMAIL_RETRY_DELAY_SECONDS", 1.0)),
        from_address=from_address,
        subject=subject,
    )


def _maybe_cast_timeout(timeout: Optional[str]) -> Optional[float]:
    if timeout is None:
        return None
    try:
        return float(timeout)
    except (TypeError, ValueError):  # pragma: no cover - defensive
        logger.warning("Invalid SMTP_TIMEOUT=%s. Ignoring timeout.", timeout)
        return None


def _build_magic_link_message(
    email: str, magic_link: str, config: EmailConfig
) -> EmailMessage:
    message = EmailMessage()
    message["Subject"] = config.subject
    message["To"] = email
    message["From"] = config.from_address
    body = f"Use this link to sign in: {magic_link}\n"
    message.set_content(body)
    return message


def _send_smtp_email(config: EmailConfig, message: EmailMessage) -> None:
    if not config.host:
        raise EmailSenderError("SMTP host is not configured; cannot send email.")

    timeout = _maybe_cast_timeout(config.timeout)
    smtp_factory = smtplib.SMTP_SSL if config.use_ssl else smtplib.SMTP
    with smtp_factory(config.host, config.port, timeout=timeout) as server:
        if config.use_tls and not config.use_ssl:
            server.starttls()
        if config.username:
            server.login(config.username, config.password or "")
        server.send_message(message)


def describe_backend() -> dict[str, str | bool]:
    """Return a summary of the configured email backend."""

    config = _load_email_config()
    return {
        "backend": config.backend,
        "from_address": config.from_address,
        "can_send_email": config.backend == "smtp" and bool(config.host),
    }


def send_magic_link_email(
    email: str, magic_link: str, *, locale: Optional[str] = None
) -> None:  # noqa: ARG001
    """Send a one-time magic login link to ``email`` using the configured backend."""

    config = _load_email_config()
    safe_email = email or ""
    logger.info("Sending magic link to %s", safe_email)
    logger.debug("Magic link for %s: %s", safe_email, "<redacted>")

    backend = (config.backend or "console").strip().lower()

    if backend == "smtp":
        message = _build_magic_link_message(email, magic_link, config)

        for attempt in range(1, config.max_retries + 1):
            try:
                logger.info(
                    "Attempt %s/%s to send magic link email to %s via SMTP host %s",
                    attempt,
                    config.max_retries,
                    safe_email,
                    config.host,
                )
                _send_smtp_email(config, message)
                logger.info("Successfully sent magic link email to %s", safe_email)
                return
            except Exception as exc:  # pragma: no cover - SMTP environments vary
                logger.exception(
                    "Attempt %s to send magic link email to %s failed",
                    attempt,
                    safe_email,
                )
                if attempt >= config.max_retries:
                    logger.error("Exhausted email retry budget for %s", safe_email)
                    raise EmailSenderError(
                        "Unable to send magic link email. Please try again later.",
                        original=exc,
                    ) from exc
                sleep_for = config.retry_delay * (2 ** (attempt - 1))
                logger.info(
                    "Retrying magic link email to %s in %.2f seconds",
                    safe_email,
                    sleep_for,
                )
                time.sleep(sleep_for)

        return

    if backend in {"console", "log", "stdout"}:
        logger.warning(
            "EMAIL_BACKEND '%s' selected; magic links will be logged only. Configure SMTP to deliver real email.",
            backend,
        )
        logger.info("Magic link email (console backend) -> %s", magic_link)
        return

    message = (
        "EMAIL_BACKEND '%s' is not supported. Configure SMTP to deliver magic links."
        % (config.backend or "")
    )
    logger.warning(message)
    raise EmailSenderError(message)


def _build_notification_message(
    email: str, subject: str, body: str, config: EmailConfig
) -> EmailMessage:
    message = EmailMessage()
    message["Subject"] = subject
    message["To"] = email
    message["From"] = config.from_address
    message.set_content(body)
    return message


def send_notification_email(email: str, subject: str, body: str) -> None:
    """Send a bell-notification email (SRS 1I.5.1 — optional, per-type).

    Never includes credentials/tokens/secrets: callers pass only the
    notification's own title/body, which the notification layer already
    guarantees are secret-free (1I.4).
    """

    config = _load_email_config()
    backend = (config.backend or "console").strip().lower()

    if backend == "smtp":
        message = _build_notification_message(email, subject, body, config)
        try:
            _send_smtp_email(config, message)
        except Exception as exc:
            raise EmailSenderError(
                "Unable to send notification email.", original=exc
            ) from exc
        return

    if backend in {"console", "log", "stdout"}:
        logger.info("Notification email (console backend) -> %s: %s", email, subject)
        return

    logger.warning("EMAIL_BACKEND '%s' is not supported for notifications.", backend)
    raise EmailSenderError(f"EMAIL_BACKEND '{backend}' is not supported.")


__all__ = [
    "describe_backend",
    "send_magic_link_email",
    "send_notification_email",
    "EmailSenderError",
    "EmailConfig",
]
