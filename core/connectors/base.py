from dataclasses import dataclass, field
from typing import Optional, Protocol


@dataclass
class ConnectorInfo:
    id: str
    kind: str                      # file_store | email
    name: str
    mode: str                      # mock | local | real
    enabled: bool
    description: str
    detail: dict = field(default_factory=dict)   # never contains secrets


class FileStore(Protocol):
    def info(self) -> ConnectorInfo: ...
    def put(self, key: str, data: bytes) -> None: ...
    def get(self, key: str) -> bytes: ...
    def delete(self, key: str) -> None: ...


@dataclass
class Attachment:
    name: str
    content_type: str
    data: bytes


@dataclass
class EmailMessage:
    sender: str
    to: list[str]
    subject: str
    body: str
    attachments: list[Attachment] = field(default_factory=list)


@dataclass
class SendResult:
    message_id: str


class EmailTransientError(Exception):
    """Failed BEFORE the provider accepted any part of the message: safe to retry."""


class EmailPermanentError(Exception):
    """The provider refused the message (bad recipient, auth, policy). Retrying will not help."""


class EmailUnknownOutcome(Exception):
    """The connection broke after message data was sent: it may or may not have been delivered. Never auto-retried."""


class EmailConnector(Protocol):
    def info(self) -> ConnectorInfo: ...
    def send(self, message: EmailMessage) -> SendResult: ...
