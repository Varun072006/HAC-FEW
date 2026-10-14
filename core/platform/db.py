"""Platform database (users, workflows, runs, events, approvals, audit).

Kept separate from the mock enterprise systems database on purpose: the mock DB simulates
external systems of record; this DB is the platform's own durable state."""
import threading
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker, declarative_base

from core.platform import config

Base = declarative_base()

_lock = threading.Lock()
_engine = None
_SessionLocal = None
_url = None


def _make_engine(url: str):
    kwargs = {}
    if url.startswith("sqlite"):
        kwargs["connect_args"] = {"check_same_thread": False, "timeout": 30}
    engine = create_engine(url, **kwargs)
    if url.startswith("sqlite"):
        @event.listens_for(engine, "connect")
        def _pragmas(dbapi_conn, _):
            dbapi_conn.isolation_level = None  # we emit BEGIN ourselves (below)
            cur = dbapi_conn.cursor()
            cur.execute("PRAGMA journal_mode=WAL")
            cur.execute("PRAGMA busy_timeout=30000")
            cur.execute("PRAGMA foreign_keys=ON")
            cur.close()

        @event.listens_for(engine, "begin")
        def _begin_immediate(conn):
            # Writers queue on busy_timeout instead of failing when a read transaction upgrades to a write.
            conn.exec_driver_sql("BEGIN IMMEDIATE")
    return engine


def get_engine():
    global _engine, _SessionLocal, _url
    url = config.platform_database_url()
    with _lock:
        if _engine is None or url != _url:
            _engine = _make_engine(url)
            _SessionLocal = sessionmaker(bind=_engine, autoflush=False, expire_on_commit=False)
            _url = url
        return _engine


def session_factory():
    get_engine()
    return _SessionLocal


def init_platform_db():
    """Bring the schema to the latest migration (the only supported way to change tables)."""
    from core.platform import models  # noqa: F401  (register tables)
    from core.platform import migrate
    migrate.upgrade(get_engine())


def get_session():
    db = session_factory()()
    try:
        yield db
    finally:
        db.close()
