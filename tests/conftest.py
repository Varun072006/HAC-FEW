"""Test isolation: the platform DB is a throwaway file; the mock enterprise DB is left as-is."""
import os
import tempfile
from pathlib import Path

_tmp = Path(tempfile.mkdtemp(prefix="hacfew_tests_"))
os.environ["PLATFORM_DATABASE_URL"] = f"sqlite:///{(_tmp / 'platform.db').as_posix()}"
os.environ["HACFEW_STATE_DIR"] = str(_tmp / "state")
os.environ["HACFEW_ENV"] = "development"
os.environ["HACFEW_SYNC_EXECUTION"] = "1"
os.environ["HACFEW_ENABLE_LEGACY_API"] = "1"  # the legacy e2e tests exercise the old endpoint
