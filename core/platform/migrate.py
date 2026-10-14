"""Run versioned schema migrations (Alembic). Called at API start-up and by tests.

Databases created by an earlier build with `create_all` are upgraded in place: the baseline revision
only creates tables that are missing, then 0002 adds the agent-runtime columns and tables.

SQLite cannot alter constraints in place, so the approvals table is rebuilt. That needs foreign keys
off, which a pragma can only change outside a transaction, so SQLite migrations use their own plain
connection and verify `foreign_key_check` afterwards."""
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine

ROOT = Path(__file__).resolve().parents[2]


def _config() -> Config:
    cfg = Config(str(ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(ROOT / "migrations"))
    return cfg


def upgrade(engine, revision: str = "head") -> None:
    cfg = _config()
    if engine.dialect.name == "sqlite":
        plain = create_engine(engine.url, connect_args={"timeout": 30})
        try:
            with plain.connect() as connection:
                connection.exec_driver_sql("PRAGMA foreign_keys=OFF")
                cfg.attributes["connection"] = connection
                command.upgrade(cfg, revision)
                connection.commit()
                broken = connection.exec_driver_sql("PRAGMA foreign_key_check").fetchall()
                if broken:
                    raise RuntimeError(f"Migration left {len(broken)} foreign-key violation(s): {broken[:3]}")
        finally:
            plain.dispose()
        return
    with engine.begin() as connection:
        cfg.attributes["connection"] = connection
        command.upgrade(cfg, revision)
