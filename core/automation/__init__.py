"""Deterministic, side-effect-free building blocks for business automations: table reading, validation,
audit analysis and report rendering. Nothing here touches the database, network or file store; the governed
tools in core.platform.tools_automation call these and own all I/O. That keeps every number reproducible
and every function unit-testable from fixtures."""
