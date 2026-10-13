"""Write the platform API's OpenAPI document. The console generates its TypeScript types from it."""
import json
import os
import sys
import tempfile
from pathlib import Path

# Importing the app must not touch real data: point the platform DB at a throwaway file.
os.environ.setdefault("PLATFORM_DATABASE_URL", f"sqlite:///{(Path(tempfile.gettempdir()) / 'hacfew_openapi.db').as_posix()}")

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from apps.api.main import app  # noqa: E402

out = Path(sys.argv[1] if len(sys.argv) > 1 else "apps/console/openapi.json")
out.write_text(json.dumps(app.openapi(), indent=2), encoding="utf-8")
print(f"wrote {out}")
