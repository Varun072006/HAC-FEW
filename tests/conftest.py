"""Test isolation: BOTH databases are throwaway. The platform DB is a fresh file; the mock enterprise DB
(employees, expenses, tickets) is a copy of your dev file, or freshly seeded if you have none, so running
the suite never adds rows to your own data."""
import os
import shutil
import tempfile
from pathlib import Path

_tmp = Path(tempfile.mkdtemp(prefix="hacfew_tests_"))
os.environ["PLATFORM_DATABASE_URL"] = f"sqlite:///{(_tmp / 'platform.db').as_posix()}"
os.environ["HACFEW_STATE_DIR"] = str(_tmp / "state")
os.environ["HACFEW_ENV"] = "development"
os.environ["HACFEW_SYNC_EXECUTION"] = "1"
os.environ["HACFEW_ENABLE_LEGACY_API"] = "1"  # the legacy e2e tests exercise the old endpoint

_source = Path(__file__).resolve().parents[1] / "mock_enterprise.db"
os.environ["DATABASE_URL"] = f"sqlite:///{(_tmp / 'mock.db').as_posix()}"   # must be set before mock_systems is imported
if _source.exists():
    shutil.copy(_source, _tmp / "mock.db")
else:
    from mock_systems.seed import seed_database  # a fresh clone has no dev DB: seed a private one
    seed_database()
