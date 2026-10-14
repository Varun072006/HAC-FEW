from typing import Optional

from core.connectors.base import ConnectorInfo, EmailConnector, FileStore
from core.connectors.email import MockEmailConnector, SmtpEmailConnector
from core.connectors.local_files import LocalFileStore
from core.platform import config

_file_store: Optional[FileStore] = None
_email: Optional[EmailConnector] = None


def get_file_store() -> FileStore:
    return _file_store or LocalFileStore(config.files_dir())


def get_email_connector() -> EmailConnector:
    """An explicitly installed connector wins (tests); otherwise HACFEW_EMAIL_MODE picks mock or smtp. Mock is the default."""
    global _email
    if _email is not None:
        return _email
    return SmtpEmailConnector() if config.email_mode() == "smtp" else _default_mock()


_mock: Optional[MockEmailConnector] = None


def _default_mock() -> MockEmailConnector:
    global _mock
    if _mock is None:
        _mock = MockEmailConnector()
    return _mock


def set_file_store(s: Optional[FileStore]) -> None:
    global _file_store
    _file_store = s


def set_email_connector(c: Optional[EmailConnector]) -> None:
    global _email
    _email = c


def connector_infos() -> list[ConnectorInfo]:
    return [get_file_store().info(), get_email_connector().info()]
