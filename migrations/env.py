"""Alembic environment. The application passes a live connection through config.attributes
(see core/platform/migrate.py); `alembic -x url=...` from the CLI is also supported."""
from alembic import context
from sqlalchemy import create_engine

config = context.config


def run() -> None:
    connection = config.attributes.get("connection")
    if connection is None:
        from core.platform import config as platform_config
        url = context.get_x_argument(as_dictionary=True).get("url") or platform_config.platform_database_url()
        connection = create_engine(url).connect()
    context.configure(connection=connection, target_metadata=None, render_as_batch=True)
    with context.begin_transaction():
        context.run_migrations()


run()
