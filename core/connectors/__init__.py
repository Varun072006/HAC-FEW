"""Connector interfaces and implementations.

Every connector declares whether it is `mock`, `local` or `real` (`ConnectorInfo.mode`) so the UI and the audit
trail never present a simulated integration as a real one. Connectors hold no credentials in workflow
definitions: settings come from the server environment. All business actions still go through the governed
operation pipeline (core.platform.operations); a connector is only the transport behind a tool.

Planned to share this shape (none implemented yet): object stores, databases, ERP systems, HTTP APIs, MCP tools."""
from core.connectors.base import ConnectorInfo, EmailConnector, FileStore  # noqa: F401
from core.connectors.registry import get_email_connector, get_file_store, set_email_connector, set_file_store, connector_infos  # noqa: F401
