"""Email connectors: a mock mailbox (default) and SMTP (real, opt-in).

Both validate the same things before anything is sent: well-formed addresses with no header injection, an
allow-listed recipient domain, a bounded recipient count. The SMTP connector fails closed unless a domain
allow-list is configured, and reads credentials only from the environment."""
import re
import smtplib
import socket
import ssl
import uuid
from email.message import EmailMessage as MimeMessage
from email.utils import formatdate, make_msgid

from core.connectors.base import (ConnectorInfo, EmailMessage, EmailPermanentError, EmailTransientError, EmailUnknownOutcome,
                                  SendResult)
from core.platform import config

ADDRESS = re.compile(r"^[A-Za-z0-9._%+\-]{1,64}@([A-Za-z0-9\-]{1,63}\.)+[A-Za-z]{2,24}$|^[A-Za-z0-9._%+\-]{1,64}@[A-Za-z0-9\-]{1,63}\.(test|local|example|invalid)$")
MAX_RECIPIENTS = 10


def check_message(m: EmailMessage) -> None:
    """Raises EmailPermanentError for anything that must never be handed to a provider."""
    if not m.to or len(m.to) > MAX_RECIPIENTS:
        raise EmailPermanentError(f"A message needs 1-{MAX_RECIPIENTS} recipients.")
    for a in [m.sender, *m.to]:
        if not ADDRESS.match(a or "") or any(c in a for c in "\r\n"):
            raise EmailPermanentError(f"'{a}' is not an acceptable email address.")
    if any(c in m.subject for c in "\r\n"):
        raise EmailPermanentError("Subject may not contain line breaks.")
    allowed = config.email_allowed_domains()
    if "*" not in allowed:
        for a in m.to:
            if a.rsplit("@", 1)[1].lower() not in allowed:
                raise EmailPermanentError(f"Recipient domain '{a.rsplit('@', 1)[1]}' is not on the allowed-domain list.")


class MockEmailConnector:
    """Accepts messages and delivers them nowhere. The delivery record is the mailbox. Deterministic failure
    injection (`fail_plan`) lets tests exercise retries without a network."""

    def __init__(self, fail_plan: list | None = None):
        self.fail_plan = list(fail_plan or [])
        self.sent: list[EmailMessage] = []

    def info(self) -> ConnectorInfo:
        return ConnectorInfo(id="email", kind="email", name="Mock email", mode="mock", enabled=True,
                             description="Messages are recorded but never leave this machine.", detail={})

    def send(self, message: EmailMessage) -> SendResult:
        check_message(message)
        if self.fail_plan:
            nxt = self.fail_plan.pop(0)
            if isinstance(nxt, Exception):
                raise nxt
        self.sent.append(message)
        return SendResult(message_id=f"mock-{uuid.uuid4().hex[:12]}")


class SmtpEmailConnector:
    """Real delivery. Stages are classified so retries are safe: failures before DATA are transient (nothing was
    accepted); 5xx are permanent; a drop after DATA started is an UNKNOWN outcome and is never retried."""

    def __init__(self, settings: dict | None = None):
        self.s = settings or config.smtp_settings()

    def info(self) -> ConnectorInfo:
        ready = bool(self.s["host"]) and bool(config.email_allowed_domains())
        return ConnectorInfo(id="email", kind="email", name="SMTP email", mode="real", enabled=ready,
                             description="Delivers through a real SMTP server." if ready
                             else "SMTP is selected but HACFEW_SMTP_HOST and HACFEW_EMAIL_ALLOWED_DOMAINS are not both set: sending is blocked.",
                             detail={"host": self.s["host"] or None, "port": self.s["port"], "allowed_domains": config.email_allowed_domains()})

    def send(self, message: EmailMessage) -> SendResult:
        if not self.s["host"]:
            raise EmailPermanentError("SMTP host is not configured.")
        if not config.email_allowed_domains() or "*" in config.email_allowed_domains():
            raise EmailPermanentError("Real email needs an explicit HACFEW_EMAIL_ALLOWED_DOMAINS list (no wildcard).")
        check_message(message)
        mime = MimeMessage()
        mime["From"], mime["To"], mime["Subject"] = message.sender, ", ".join(message.to), message.subject
        mime["Date"], mime["Message-ID"] = formatdate(localtime=False), make_msgid(domain="hacfew")
        mime.set_content(message.body)
        for a in message.attachments:
            maintype, _, subtype = (a.content_type or "application/octet-stream").partition("/")
            mime.add_attachment(a.data, maintype=maintype, subtype=subtype or "octet-stream", filename=a.name)
        try:
            cls = smtplib.SMTP_SSL if self.s["ssl"] else smtplib.SMTP
            smtp = cls(self.s["host"], self.s["port"], timeout=self.s["timeout"])
        except (OSError, smtplib.SMTPException, socket.timeout) as exc:
            raise EmailTransientError(f"Could not connect to the mail server: {type(exc).__name__}")
        try:
            try:
                smtp.ehlo()
                if self.s["starttls"] and not self.s["ssl"]:
                    smtp.starttls(context=ssl.create_default_context())
                    smtp.ehlo()
                if self.s["user"]:
                    smtp.login(self.s["user"], self.s["password"])
            except smtplib.SMTPAuthenticationError:
                raise EmailPermanentError("The mail server rejected the configured credentials.")
            except (smtplib.SMTPException, OSError) as exc:
                raise EmailTransientError(f"Mail server handshake failed: {type(exc).__name__}")
            try:
                smtp.send_message(mime)
            except smtplib.SMTPRecipientsRefused as exc:
                raise EmailPermanentError("The mail server refused the recipient(s).") from exc
            except smtplib.SMTPResponseException as exc:
                if 400 <= exc.smtp_code < 500:
                    raise EmailTransientError(f"Mail server asked to retry later ({exc.smtp_code}).")
                raise EmailPermanentError(f"Mail server rejected the message ({exc.smtp_code}).")
            except (smtplib.SMTPServerDisconnected, OSError, socket.timeout) as exc:
                raise EmailUnknownOutcome(f"Connection lost while sending ({type(exc).__name__}); the message may have been delivered.")
        finally:
            try:
                smtp.quit()
            except Exception:
                pass
        return SendResult(message_id=str(mime["Message-ID"]))
